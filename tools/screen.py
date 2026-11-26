"""Stage 1 screen: apply the POLICY.md section 4a gates to saved connector data.

Reads two files a run saved from the Robinhood connector:
  * get_equity_fundamentals output (market cap, P/E, P/B, average volume, sector)
  * get_equity_quotes output (last trade price), because fundamentals carry no price

Every gate must be sourced. A name with any required figure missing is dropped
with "unavailable", never estimated. Restricted names (Gate 0) are excluded before
anything else, so they never appear in the shortlist.

The shortlist is ordered by P/E, lowest first, only so it reads in a stable order;
the order is not a buy signal. POLICY allows at most one new name per sector per
cycle, so the first survivor in each sector is marked as that sector's pick.

Usage (from the repo root):
  python3 -m tools screen --fundamentals fund.json --quotes quotes.json [--out shortlist.json]

Exit code 0 = ran (even if nothing passed), 2 = bad input.
"""

import argparse
import json
import sys

try:
    from tools.restricted import DEFAULT_POLICY, gate0
except ImportError:
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    from restricted import DEFAULT_POLICY, gate0  # type: ignore

# Mirrors POLICY.md section 4a. Change them there first, then here.
PRICE_MIN, PRICE_MAX = 2.0, 400.0
MARKET_CAP_MIN = 2_000_000_000
AVG_VOLUME_MIN = 500_000
PE_MIN, PE_MAX = 0.0, 40.0          # P/E must be > 0 and <= 40
PB_MAX = 8.0


def _results(data):
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        data = data["results"]
    if not isinstance(data, list):
        raise ValueError("expected a connector response with a results list")
    return data


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def load_fundamentals(path):
    with open(path, encoding="utf-8") as fh:
        rows = _results(json.load(fh))
    out = {}
    for row in rows:
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def load_prices(path):
    """Return {SYMBOL: last regular-session trade price} from saved get_equity_quotes output."""
    with open(path, encoding="utf-8") as fh:
        rows = _results(json.load(fh))
    out = {}
    for row in rows:
        quote = row.get("quote", row) if isinstance(row, dict) else None
        if not isinstance(quote, dict) or not quote.get("symbol"):
            continue
        if quote.get("state") not in (None, "active") or quote.get("has_traded") is False:
            continue  # not tradable or no trade: price stays unavailable
        price = _num(quote.get("last_trade_price"))
        if price is not None and price > 0:
            out[str(quote["symbol"]).upper()] = price
    return out


def screen_one(symbol, fund, price):
    """Return (metrics, failures) for one name against the section 4a gates."""
    metrics = {
        "price": price,
        "marketCap": _num(fund.get("market_cap")),
        "avgVolume": _num(fund.get("average_volume_30_days") or fund.get("average_volume")),
        "pe": _num(fund.get("pe_ratio")),
        "pb": _num(fund.get("pb_ratio")),
        "sector": fund.get("sector") or None,
    }
    failures = []
    for key, label in (("price", "price"), ("marketCap", "market cap"), ("avgVolume", "average volume"),
                       ("pe", "P/E"), ("pb", "P/B")):
        if metrics[key] is None:
            failures.append(f"{label} unavailable")
    if failures:
        return metrics, failures
    if not PRICE_MIN <= metrics["price"] <= PRICE_MAX:
        failures.append(f"price ${metrics['price']:.2f} outside ${PRICE_MIN:.0f}-${PRICE_MAX:.0f}")
    if metrics["marketCap"] < MARKET_CAP_MIN:
        failures.append(f"market cap ${metrics['marketCap'] / 1e9:.2f}B below $2B")
    if metrics["avgVolume"] < AVG_VOLUME_MIN:
        failures.append(f"average volume {metrics['avgVolume']:,.0f} below {AVG_VOLUME_MIN:,}")
    if not (PE_MIN < metrics["pe"] <= PE_MAX):
        failures.append(f"P/E {metrics['pe']:.1f} outside 0-40")
    if metrics["pb"] > PB_MAX:
        failures.append(f"P/B {metrics['pb']:.1f} above {PB_MAX:.0f}")
    return metrics, failures


def run_screen(fundamentals, prices, symbols=None, policy_path=DEFAULT_POLICY):
    symbols = sorted(set(symbols or fundamentals) | set(fundamentals))
    gate = gate0(symbols, policy_path)
    passed, dropped, excluded = [], [], []
    for sym in symbols:
        status, reason = gate[sym]
        if status != "clear":
            excluded.append({"symbol": sym, "reason": reason})
            continue
        if sym not in fundamentals:
            dropped.append({"symbol": sym, "failures": ["fundamentals unavailable"]})
            continue
        metrics, failures = screen_one(sym, fundamentals[sym], prices.get(sym))
        (dropped if failures else passed).append({"symbol": sym, **metrics, **({"failures": failures} if failures else {})})
    passed.sort(key=lambda r: (r["pe"], r["symbol"]))
    seen_sectors = set()
    for row in passed:
        sector = row["sector"] or "unknown"
        row["sectorPick"] = sector not in seen_sectors
        seen_sectors.add(sector)
    return {
        "gates": {"price": [PRICE_MIN, PRICE_MAX], "marketCapMin": MARKET_CAP_MIN,
                  "avgVolumeMin": AVG_VOLUME_MIN, "pe": [PE_MIN, PE_MAX], "pbMax": PB_MAX},
        "shortlist": passed,
        "dropped": dropped,
        # Only the count is reported, so a restricted name never shows up as a candidate.
        "restrictedExcluded": len(excluded),
        "caveats": ["A shortlist, never a buy. Every survivor still goes through Stage 2 onward.",
                    "Ordered by P/E only for a stable read; the order is not a ranking of merit."],
    }


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m tools screen", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fundamentals", required=True, help="saved get_equity_fundamentals output")
    p.add_argument("--quotes", required=True, help="saved get_equity_quotes output (for price)")
    p.add_argument("--policy", default=DEFAULT_POLICY)
    p.add_argument("--out", help="write the full result as JSON here")
    a = p.parse_args(argv)
    try:
        fundamentals = load_fundamentals(a.fundamentals)
        prices = load_prices(a.quotes)
    except (OSError, ValueError) as exc:
        print(f"Screen: bad input ({exc})", file=sys.stderr)
        return 2
    result = run_screen(fundamentals, prices, policy_path=a.policy)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
    print(f"Screen: {len(result['shortlist'])} passed, {len(result['dropped'])} dropped, "
          f"{result['restrictedExcluded']} restricted excluded")
    for r in result["shortlist"]:
        pick = " · sector pick" if r["sectorPick"] else ""
        print(f"  PASS {r['symbol']}: ${r['price']:.2f}, cap ${r['marketCap'] / 1e9:.1f}B, "
              f"P/E {r['pe']:.1f}, P/B {r['pb']:.2f}, vol {r['avgVolume']:,.0f}, {r['sector'] or 'sector unknown'}{pick}")
    for r in result["dropped"]:
        print(f"  DROP {r['symbol']}: {'; '.join(r['failures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
