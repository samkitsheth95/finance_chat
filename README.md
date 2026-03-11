# india-markets MCP

An MCP (Model Context Protocol) server that gives Claude live access to Indian
financial market data via Zerodha Kite Connect. Ask questions about NSE/BSE
stocks, indices, and historical price data directly inside Cursor or Claude Code.

## What you can ask (Layer 1)

```
"How is the market doing today?"
"What is the current price of Reliance?"
"How has Infosys performed over the last 3 months?"
"What is India VIX right now?"
"Show me BankNifty's intraday movement today."
"What is the 52-week high and low range for HDFC Bank?"
"Compare Nifty IT vs Nifty Bank performance this month."
```

## Roadmap

| Layer | Data | Status |
|-------|------|--------|
| 1 | Live quotes, indices, historical OHLC (Kite) | ✅ Done |
| 2 | FII/DII institutional flows (NSE public) | Planned |
| 3 | Option chain, Greeks, PCR, Max Pain (Kite) | Planned |
| 4 | Global macro — crude, DXY, US markets, GIFT Nifty | Planned |
| 5 | News and geopolitical sentiment | Planned |
| 6 | Signal scoring and weighting framework | Planned |

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/finance_chat.git
cd finance_chat
pip install -r requirements.txt
```

### 2. Get your Kite Connect credentials

1. Log in at [developers.kite.trade](https://developers.kite.trade)
2. Create an app → copy your **API Key** and **API Secret**
3. Each morning, generate a fresh **Access Token** via the Kite login URL:
   ```
   https://kite.trade/connect/login?api_key=YOUR_API_KEY&v=3
   ```
   After logging in, you'll be redirected to your redirect URL with a
   `request_token` in the query string. Exchange it for an access token:
   ```python
   from kiteconnect import KiteConnect
   kite = KiteConnect(api_key="YOUR_API_KEY")
   data = kite.generate_session("REQUEST_TOKEN_FROM_URL", api_secret="YOUR_SECRET")
   print(data["access_token"])  # paste this into .env
   ```

### 3. Configure your .env file

```bash
cp .env.example .env
```

Edit `.env`:
```
KITE_API_KEY=your_api_key_here
KITE_ACCESS_TOKEN=your_fresh_access_token_here
```

> **Note:** The access token expires at the end of each trading day.
> You need to regenerate it each morning before using the MCP server.

---

## Add to Cursor

The `.cursor/mcp.json` in this project is already configured. Cursor picks it
up automatically when you open this folder.

To verify it's running:
  1. Top menu → Cursor → Settings → Cursor Settings
  2. Look for the MCP section in the left sidebar
  3. `india-markets` should appear with a green dot

Alternatively: Cmd+Shift+P → type "MCP" → "Cursor: Open MCP Settings"

## Add to Claude Code

```bash
# From the project directory:
claude mcp add --scope project india-markets python mcp_server.py
```

Or add globally so it's available in all projects:
```bash
claude mcp add india-markets python /full/path/to/finance_chat/mcp_server.py
```

---

## Sharing with others

Each person needs:
1. A Zerodha account with [Kite Connect API](https://kite.trade/pricing) access
2. Their own `KITE_API_KEY`, `KITE_ACCESS_TOKEN`, in a `.env` file
3. Python 3.10+ and `pip install -r requirements.txt`

Everything else (code, `.mcp.json`, tools) is in the repo.

---

## Project structure

```
finance_chat/
├── mcp_server.py          ← MCP server entry point
├── tools/
│   └── kite_tools.py      ← Layer 1: quote, indices, historical OHLC
├── core/
│   └── kite_client.py     ← Kite Connect session + instrument cache
├── .mcp.json              ← Cursor / Claude Code MCP config
├── .env.example           ← API key template
├── .env                   ← Your keys (gitignored)
└── requirements.txt
```
