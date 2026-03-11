"""
Layer 3 — Derivatives Mechanics
Option chain (all strikes, OI, Greeks), PCR, Max Pain, and India VIX.
Auth and instrument caching live in core/kite_client.py.

Key outputs:
  - option_chain: full strike-by-strike OI + Greeks, PCR, Max Pain, OI walls
  - vix:          India VIX with regime label and options strategy guidance

Data freshness: live during market hours (09:15–15:30 IST); stale after.
"""

from datetime import datetime, date as date_type
from core.kite_client import get_kite, get_instruments


# ── Lot sizes (exchange-published; updated periodically by SEBI) ─────────────
# Used as fallback when instrument data doesn't carry lot_size for a strike.
_LOT_SIZE_FALLBACK: dict[str, int] = {
    "NIFTY":      75,
    "BANKNIFTY":  35,
    "FINNIFTY":   65,
    "MIDCPNIFTY": 120,
    "SENSEX":     20,
    "BANKEX":     20,
}

# Kite quote symbol for the underlying spot price
_UNDERLYING_SPOT: dict[str, str] = {
    "NIFTY":      "NSE:NIFTY 50",
    "BANKNIFTY":  "NSE:NIFTY BANK",
    "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
    "SENSEX":     "BSE:SENSEX",
    "BANKEX":     "BSE:BANKEX",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pcr_signal(pcr: float) -> str:
    if pcr >= 1.3:
        return "strongly_bullish"
    if pcr >= 1.0:
        return "bullish"
    if pcr >= 0.7:
        return "neutral"
    if pcr >= 0.5:
        return "bearish"
    return "strongly_bearish"


def _pcr_note(pcr: float) -> str:
    if pcr >= 1.3:
        return (
            f"PCR {pcr:.2f} — extreme put loading. Contrarian bullish: "
            "option sellers (writers) expect the market to hold or bounce."
        )
    if pcr >= 1.0:
        return (
            f"PCR {pcr:.2f} — above 1.0; more put OI than call OI. "
            "Market leans bullish (put writers defending lower levels)."
        )
    if pcr >= 0.7:
        return (
            f"PCR {pcr:.2f} — balanced range. Neither bulls nor bears dominate."
        )
    if pcr >= 0.5:
        return (
            f"PCR {pcr:.2f} — below 0.7; relatively more calls than puts. "
            "Market may be topping out — watch for reversal signals."
        )
    return (
        f"PCR {pcr:.2f} — extreme call loading. "
        "Excessive call buying signals complacency — strong bearish warning."
    )


def _max_pain_note(spot: float | None, max_pain_strike: int) -> str:
    if spot is None:
        return f"Max pain at {max_pain_strike}."
    diff = spot - max_pain_strike
    if abs(diff) < 30:
        return (
            f"Spot ({spot:.0f}) is at max pain ({max_pain_strike}). "
            "Market is exactly where option writers want it — minimal directional pull."
        )
    if diff > 0:
        return (
            f"Spot ({spot:.0f}) is {diff:.0f} pts above max pain ({max_pain_strike}). "
            "Gravitational pull downward; option writers benefit if spot drifts lower by expiry."
        )
    return (
        f"Spot ({spot:.0f}) is {abs(diff):.0f} pts below max pain ({max_pain_strike}). "
        "Gravitational pull upward; option writers benefit if spot drifts higher by expiry."
    )


def _compute_max_pain(strikes_data: dict, lot_size: int) -> int:
    """
    Max Pain = expiry price at which total payout to ALL option buyers is minimised.

    At candidate expiry price X:
      ITM calls (strike K < X) : payout = (X − K) × CE_OI × lot_size
      ITM puts  (strike K > X) : payout = (K − X) × PE_OI × lot_size

    Returns the strike that minimises the total payout (best for writers).
    """
    sorted_strikes = sorted(strikes_data.keys())
    min_pain      = float("inf")
    max_pain_str  = sorted_strikes[len(sorted_strikes) // 2]  # safe default

    for candidate in sorted_strikes:
        total = 0.0
        for strike, data in strikes_data.items():
            call_oi = data.get("CE", {}).get("oi", 0)
            put_oi  = data.get("PE", {}).get("oi", 0)
            if candidate > strike and call_oi:
                total += (candidate - strike) * call_oi * lot_size
            if candidate < strike and put_oi:
                total += (strike - candidate) * put_oi * lot_size
        if total < min_pain:
            min_pain     = total
            max_pain_str = candidate

    return int(max_pain_str)


# ── Core functions ────────────────────────────────────────────────────────────

def get_option_chain(underlying: str = "NIFTY", expiry: str = "near") -> dict:
    """
    Fetch the full option chain for an index/stock F&O with derived signals.

    Args:
        underlying: Underlying name — "NIFTY", "BANKNIFTY", "FINNIFTY",
                    "MIDCPNIFTY", or any stock F&O name.
        expiry:     "near" for nearest weekly/monthly expiry, or
                    date string in DD-MMM-YYYY format, e.g. "27-Mar-2026".

    Returns:
        spot, ATM strike, days_to_expiry, lot_size
        pcr:            Put-Call Ratio, signal, note
        max_pain:       strike, distance from spot, interpretation note
        call_oi_wall:   highest OI call strike (key resistance)
        put_oi_wall:    highest OI put strike (key support)
        top_call/put_strikes: top 5 by OI
        atm_chain:      ±10 strikes from ATM with LTP, OI, IV, Delta for CE and PE
        available_expiries: next 5–6 expiry dates
    """
    kite       = get_kite()
    underlying = underlying.upper()

    try:
        nfo_instruments = get_instruments("NFO")
    except Exception as exc:
        return {"error": f"Failed to load NFO instruments: {exc}"}

    # Filter to options for this underlying
    options = [
        i for i in nfo_instruments
        if i["name"] == underlying
        and i["instrument_type"] in ("CE", "PE")
        and i.get("expiry")
    ]

    if not options:
        return {
            "error": (
                f"No options found for '{underlying}' in NFO. "
                "Try 'NIFTY', 'BANKNIFTY', 'FINNIFTY', or a stock F&O name."
            )
        }

    today              = date_type.today()
    available_expiries = sorted({i["expiry"] for i in options if i["expiry"] >= today})

    if not available_expiries:
        return {"error": f"No upcoming expiries found for {underlying}."}

    # Resolve target expiry
    if expiry == "near":
        target_expiry = available_expiries[0]
    else:
        try:
            target_expiry = datetime.strptime(expiry, "%d-%b-%Y").date()
        except ValueError:
            return {
                "error": (
                    f"Invalid expiry format '{expiry}'. "
                    "Use 'near' or 'DD-MMM-YYYY' (e.g. '27-Mar-2026')."
                ),
                "available_expiries": [str(e) for e in available_expiries[:6]],
            }

    expiry_options = [i for i in options if i["expiry"] == target_expiry]
    if not expiry_options:
        return {
            "error": f"No options found for {underlying} expiring {target_expiry}.",
            "available_expiries": [str(e) for e in available_expiries[:6]],
        }

    # Lot size from instruments data (fallback to hardcoded table)
    lot_size = (
        expiry_options[0].get("lot_size")
        or _LOT_SIZE_FALLBACK.get(underlying, 1)
    )

    # Fetch spot price
    spot = None
    spot_symbol = _UNDERLYING_SPOT.get(underlying)
    if spot_symbol:
        try:
            sq = kite.quote([spot_symbol])
            spot = sq.get(spot_symbol, {}).get("last_price")
        except Exception:
            pass  # non-fatal; PCR and max pain still work without spot

    # Batch-fetch option quotes (Kite cap: 500 per request)
    option_symbols = [f"NFO:{i['tradingsymbol']}" for i in expiry_options]
    quotes: dict = {}
    for start in range(0, len(option_symbols), 500):
        chunk = option_symbols[start : start + 500]
        try:
            quotes.update(kite.quote(chunk))
        except Exception as exc:
            return {"error": f"Failed to fetch option quotes: {exc}"}

    # Build strike-keyed dict  {strike_float → {"CE": {...}, "PE": {...}}}
    strikes_data: dict[float, dict] = {}
    for inst in expiry_options:
        sym      = f"NFO:{inst['tradingsymbol']}"
        q        = quotes.get(sym) or {}
        strike   = float(inst["strike"])
        opt_type = inst["instrument_type"]  # "CE" or "PE"

        if strike not in strikes_data:
            strikes_data[strike] = {}

        greeks = q.get("greeks") or {}
        depth  = q.get("depth") or {}
        bids   = (depth.get("buy")  or [{}])
        asks   = (depth.get("sell") or [{}])

        strikes_data[strike][opt_type] = {
            "ltp":    q.get("last_price", 0),
            "oi":     q.get("oi", 0),
            "volume": q.get("volume", 0),
            "iv":     greeks.get("iv"),
            "delta":  greeks.get("delta"),
            "theta":  greeks.get("theta"),
            "gamma":  greeks.get("gamma"),
            "vega":   greeks.get("vega"),
            "bid":    bids[0].get("price"),
            "ask":    asks[0].get("price"),
        }

    # ── PCR ──────────────────────────────────────────────────────────────────
    total_call_oi = sum(v.get("CE", {}).get("oi", 0) for v in strikes_data.values())
    total_put_oi  = sum(v.get("PE", {}).get("oi", 0) for v in strikes_data.values())
    pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None

    # ── Max Pain ─────────────────────────────────────────────────────────────
    max_pain_strike = _compute_max_pain(strikes_data, lot_size)

    # ── ATM strike ───────────────────────────────────────────────────────────
    sorted_strike_list = sorted(strikes_data.keys())
    atm_strike: float | None = None
    if spot and sorted_strike_list:
        atm_strike = min(sorted_strike_list, key=lambda k: abs(k - spot))

    # ── ATM chain ±10 strikes ────────────────────────────────────────────────
    atm_chain: list[dict] = []
    if atm_strike is not None:
        atm_idx    = sorted_strike_list.index(atm_strike)
        lo         = max(0, atm_idx - 10)
        hi         = min(len(sorted_strike_list), atm_idx + 11)
        for s in sorted_strike_list[lo:hi]:
            d = strikes_data[s]
            atm_chain.append({
                "strike":     int(s),
                "call_ltp":   d.get("CE", {}).get("ltp"),
                "call_oi":    d.get("CE", {}).get("oi"),
                "call_iv":    d.get("CE", {}).get("iv"),
                "call_delta": d.get("CE", {}).get("delta"),
                "put_ltp":    d.get("PE", {}).get("ltp"),
                "put_oi":     d.get("PE", {}).get("oi"),
                "put_iv":     d.get("PE", {}).get("iv"),
                "put_delta":  d.get("PE", {}).get("delta"),
            })

    # ── OI walls ─────────────────────────────────────────────────────────────
    call_by_oi = sorted(
        [(int(s), d.get("CE", {}).get("oi", 0)) for s, d in strikes_data.items() if "CE" in d],
        key=lambda x: -x[1],
    )
    put_by_oi = sorted(
        [(int(s), d.get("PE", {}).get("oi", 0)) for s, d in strikes_data.items() if "PE" in d],
        key=lambda x: -x[1],
    )

    # ── Assemble result ──────────────────────────────────────────────────────
    max_pain_distance = round(max_pain_strike - spot, 0) if spot else None
    max_pain_pct      = round((max_pain_strike - spot) / spot * 100, 2) if spot else None

    return {
        "underlying":     underlying,
        "expiry":         str(target_expiry),
        "days_to_expiry": (target_expiry - today).days,
        "spot":           spot,
        "atm_strike":     int(atm_strike) if atm_strike is not None else None,
        "lot_size":       lot_size,
        "total_strikes":  len(strikes_data),
        "pcr": {
            "value":         pcr,
            "total_call_oi": total_call_oi,
            "total_put_oi":  total_put_oi,
            "signal":        _pcr_signal(pcr) if pcr is not None else "unknown",
            "note":          _pcr_note(pcr)   if pcr is not None else "Insufficient OI data.",
        },
        "max_pain": {
            "strike":           max_pain_strike,
            "distance_from_spot": max_pain_distance,
            "distance_pct":     max_pain_pct,
            "note":             _max_pain_note(spot, max_pain_strike),
        },
        "call_oi_wall": (
            {"strike": call_by_oi[0][0], "oi": call_by_oi[0][1]}
            if call_by_oi else None
        ),
        "put_oi_wall": (
            {"strike": put_by_oi[0][0], "oi": put_by_oi[0][1]}
            if put_by_oi else None
        ),
        "top_call_strikes": [{"strike": s, "oi": o} for s, o in call_by_oi[:5]],
        "top_put_strikes":  [{"strike": s, "oi": o} for s, o in put_by_oi[:5]],
        "atm_chain":          atm_chain,
        "available_expiries": [str(e) for e in available_expiries[:6]],
        "as_of":              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_vix() -> dict:
    """
    Fetch India VIX with volatility regime label and options strategy guidance.

    India VIX is computed by NSE using the Black-Scholes model applied to
    near- and next-month Nifty options. It represents the annualised expected
    volatility over the next 30 calendar days.

    Returns:
        vix, day OHLC, change, regime label, interpretation, weekly 1σ move %.
    """
    kite = get_kite()

    try:
        raw = kite.quote(["NSE:INDIA VIX"])
    except Exception as exc:
        return {"error": str(exc)}

    q = raw.get("NSE:INDIA VIX") or {}
    if not q:
        return {"error": "No data returned for India VIX."}

    vix       = q["last_price"]
    ohlc      = q.get("ohlc") or {}
    prev_close = ohlc.get("close") or vix
    change     = round(vix - prev_close, 2)
    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

    # Expected weekly move (1σ): annualised vol ÷ √52
    weekly_1sigma_pct = round(vix / (52 ** 0.5), 2)

    # Regime classification + actionable guidance
    if vix < 12:
        regime = "very_low"
        interpretation = (
            f"VIX {vix:.1f} — extreme complacency. Options are historically cheap. "
            "Strong edge for option buyers (long straddle / strangle) before any catalyst. "
            "Writers earn minimal premium for the risk they carry."
        )
    elif vix < 16:
        regime = "low"
        interpretation = (
            f"VIX {vix:.1f} — calm market. Options priced cheaply; "
            "buying debit spreads or naked options offers good risk/reward. "
            "Selling covered calls on longs still viable but premiums are thin."
        )
    elif vix < 20:
        regime = "normal"
        interpretation = (
            f"VIX {vix:.1f} — normal volatility. Balanced conditions: "
            "iron condors, credit spreads, and defined-risk strategies work well. "
            "ATM straddles are fairly priced — neither buyers nor sellers have a clear edge."
        )
    elif vix < 25:
        regime = "elevated"
        interpretation = (
            f"VIX {vix:.1f} — elevated fear. Options premiums are fat; "
            "selling (writing) earns good credit but risk is meaningful. "
            "Prefer defined-risk spreads over naked positions. "
            "Avoid buying unless you expect a large directional move."
        )
    elif vix < 30:
        regime = "high"
        interpretation = (
            f"VIX {vix:.1f} — high fear. Buying puts for portfolio protection is cheap "
            "relative to downside risk. Buyers of calls get leverage into any bounce. "
            "Naked option writing is very risky — use spreads only."
        )
    else:
        regime = "extreme"
        interpretation = (
            f"VIX {vix:.1f} — extreme fear / possible dislocation. "
            "VIX spikes historically mean-revert sharply; selling volatility "
            "(short straddles, iron condors) after the spike peaks can be profitable. "
            "Wait for VIX to start falling before initiating short-vol trades."
        )

    return {
        "vix":                    vix,
        "prev_close":             prev_close,
        "change":                 change,
        "change_pct":             change_pct,
        "day_high":               ohlc.get("high"),
        "day_low":                ohlc.get("low"),
        "regime":                 regime,
        "interpretation":         interpretation,
        "weekly_move_1sigma_pct": weekly_1sigma_pct,
        "note": (
            f"Market is pricing a ~{weekly_1sigma_pct}% weekly 1σ move. "
            "Use option_chain() to see actual ATM straddle price vs this implied range."
        ),
        "as_of": str(q.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    }
