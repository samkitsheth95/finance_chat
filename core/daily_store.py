"""
Daily Snapshot Store

Saves and loads daily market snapshots to data/daily/YYYY-MM-DD.json.
Each snapshot captures the end-of-day state across all signal layers,
enabling multi-day lookbacks, trend persistence scoring, and historical
pattern matching.

Schema is intentionally flat — optimized for filtering and aggregation,
not for display. Display-level detail stays in the tool outputs.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "daily"


def _ensure_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path_for(dt: date) -> Path:
    return _DATA_DIR / f"{dt.isoformat()}.json"


def save(snapshot: dict, dt: date | None = None) -> Path:
    """Write a snapshot dict to data/daily/YYYY-MM-DD.json. Returns the file path."""
    _ensure_dir()
    dt = dt or date.today()
    path = _path_for(dt)
    snapshot["_saved_at"] = datetime.now().isoformat()
    snapshot["date"] = dt.isoformat()
    path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    return path


def load(dt: date) -> dict | None:
    """Load a single day's snapshot, or None if it doesn't exist."""
    path = _path_for(dt)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_range(start: date, end: date) -> list[dict]:
    """Load all snapshots between start and end (inclusive), sorted by date."""
    results = []
    current = start
    while current <= end:
        snap = load(current)
        if snap is not None:
            results.append(snap)
        current += timedelta(days=1)
    return results


def load_recent(days: int = 5) -> list[dict]:
    """Load the most recent N available snapshots (not calendar days)."""
    _ensure_dir()
    files = sorted(_DATA_DIR.glob("*.json"), reverse=True)
    results = []
    for f in files[:days]:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    results.reverse()
    return results


def available_dates() -> list[str]:
    """List all dates that have saved snapshots, sorted ascending."""
    _ensure_dir()
    return sorted(f.stem for f in _DATA_DIR.glob("*.json"))
