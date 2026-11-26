"""Load daily OHLC bars saved from the Robinhood connector.

The funnel saves the raw output of `get_equity_historicals` (interval "day",
adjustment_type "split") to a JSON file, then points these tools at it. This
module turns that file into a clean, date-sorted list of bars per symbol.

Accepted shapes (whatever the connector returned, saved as-is):
  * {"data": {"results": [{"symbol": "X", "bars": [bar, ...]}, ...]}}
    (what get_equity_historicals returns today)
  * {"results": [{"symbol": "X", "historicals": [bar, ...]}, ...]}
  * {"X": [bar, ...], "Y": [bar, ...]}
  * [{"symbol": "X", "historicals": [...]}, ...]
  * [bar, ...]  (single symbol; pass symbol= explicitly)

A bar may use Robinhood keys (begins_at, open_price, high_price, low_price,
close_price) or short keys (date, open, high, low, close). Bars flagged
`interpolated: true` carry no new information and are dropped.

Nothing here fetches data or estimates a missing value: a bar missing any
OHLC field is dropped, and callers see how many bars they actually have.
"""

import json
from dataclasses import dataclass

_KEYS = {
    "date": ("date", "begins_at", "timestamp", "time"),
    "open": ("open", "open_price"),
    "high": ("high", "high_price"),
    "low": ("low", "low_price"),
    "close": ("close", "close_price"),
}


@dataclass(frozen=True)
class Bar:
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float


def _pick(raw, field):
    for key in _KEYS[field]:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def parse_bar(raw):
    """Return a Bar, or None if the bar is interpolated or incomplete."""
    if not isinstance(raw, dict) or raw.get("interpolated") is True:
        return None
    date = _pick(raw, "date")
    if date is None:
        return None
    values = {}
    for field in ("open", "high", "low", "close"):
        value = _pick(raw, field)
        try:
            values[field] = float(value)
        except (TypeError, ValueError):
            return None
        if values[field] <= 0:
            return None
    return Bar(date=str(date)[:10], **values)


def _clean(raw_bars):
    by_date = {}
    for raw in raw_bars or []:
        bar = parse_bar(raw)
        if bar is not None:
            by_date[bar.date] = bar  # last one wins on duplicate dates
    return [by_date[d] for d in sorted(by_date)]


def load_bars(path, symbol=None):
    """Return {SYMBOL: [Bar, ...]} from a saved connector response."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return bars_from_data(data, symbol=symbol)


_SERIES_KEYS = ("bars", "historicals")


def _series(entry):
    for key in _SERIES_KEYS:
        if isinstance(entry, dict) and isinstance(entry.get(key), list):
            return entry[key]
    return None


def bars_from_data(data, symbol=None):
    out = {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data, dict) and "results" in data:
        data = data["results"]
    if isinstance(data, list):
        if data and _series(data[0]) is not None:
            for entry in data:
                sym = str(entry.get("symbol") or symbol or "").upper()
                if sym:
                    out[sym] = _clean(_series(entry))
        else:
            if not symbol:
                raise ValueError("a bare list of bars needs symbol=")
            out[symbol.upper()] = _clean(data)
    elif isinstance(data, dict):
        for sym, value in data.items():
            if _series(value) is not None:
                value = _series(value)
            if isinstance(value, list):
                out[str(sym).upper()] = _clean(value)
    else:
        raise ValueError("unrecognised bars file")
    return out
