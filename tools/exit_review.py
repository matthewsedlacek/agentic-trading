"""Nightly exit review: propose exits on open positions for the operator's yes.

Reads files a run already saved (nothing here fetches data, estimates a
missing number, or places, stages, changes or cancels an order):

  * positions   data/live.json (tickers, shares, avg buy price, prices)
  * exit plans  trades/*.md and executed proposals/*.md (stop, target,
                horizon, thesis-break written at entry)
  * fills       data/fills.json (entry dates when a plan has none)
  * snapshots   data/snapshots/*.json (portfolio peak, for the breaker)
  * bars        optional saved get_equity_historicals for the holdings
                (peak since entry) and for SPY (market regime)

and writes a proposal report. Each position gets one action:

  SELL    the written plan says exit: close at/below the stop, or at/above
          the target. Proposed for the whole position.
  REVIEW  a judgement call for the operator: past the time horizon, gave
          back most of a big gain, or a losing position in a risk-off market.
  WATCH   nothing to do yet: near the stop or target, horizon close, or a
          losing position while SPY is in caution.
  HOLD    none of the above.
  SKIP    no proposal possible: restricted name, or a price/plan it can't
          source (fail closed).

The thresholds below are starting guesses, not tested rules. Change them in
POLICY.md §4d first, then here, so the policy and the code agree.

Usage (from the repo root):
  python3 -m tools.exit_review [--positions data/live.json] [--fills data/fills.json] \
      [--plans trades proposals] [--snapshots data/snapshots] \
      [--bars holdings.json] [--spy SPY.json] [--as-of YYYY-MM-DD] [--out reviews/exits]

Exit code 0 = report written (with or without proposals), 2 = bad input.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

try:
    from tools.bars import load_bars
    from tools.edge_gate import market_regime
except ImportError:  # run as a plain script: python3 tools/exit_review.py
    sys.path.insert(0, os.path.dirname(__file__))
    from bars import load_bars  # type: ignore
    from edge_gate import market_regime  # type: ignore

# Mirrors POLICY.md §0. A restricted holding is read for context only.
RESTRICTED = {"SEZL"}

# Policy defaults (POLICY.md §4), used when a position has no written plan.
DEFAULT_STOP_PCT = 0.08
DEFAULT_TARGET_PCT = 0.16
DEFAULT_HORIZON_DAYS = 183        # calendar days, ~126 trading days

# Starting guesses (POLICY.md §4d).
NEAR_STOP_PCT = 0.02              # WATCH when the close is within 2% above the stop
NEAR_TARGET_PCT = 0.03            # WATCH when within 3% below the target
HORIZON_WARN_DAYS = 14            # WATCH when the horizon ends within 14 days
GIVEBACK_PEAK_GAIN = 0.10         # REVIEW if it was up >= 10% since entry ...
GIVEBACK_FLOOR_GAIN = 0.02        # ... and is now up <= 2%
BREAKER_DRAWDOWN = 0.10           # portfolio down 10% from its recent peak
STALE_HOURS = 36                  # positions file older than this is flagged

ACTIONS = ("SELL", "REVIEW", "WATCH", "HOLD", "SKIP")


# ---------------------------------------------------------------- plans

_MONEY = r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
_LABELS = {
    "stop": re.compile(r"^\s*[-*]?\s*\**\s*(?:stop(?:-loss| level| loss)?)\s*:?\**\s*:?\s*" + _MONEY, re.I),
    "target": re.compile(r"^\s*[-*]?\s*\**\s*(?:(?:profit |price )?target)\s*:?\**\s*:?\s*" + _MONEY, re.I),
    "horizon": re.compile(r"^\s*[-*]?\s*\**\s*(?:time )?horizon\s*:?\**\s*:?\s*(.+)$", re.I),
    "thesisBreak": re.compile(r"^\s*[-*]?\s*\**\s*thesis[- ]break(?: condition)?\s*:?\**\s*:?\s*(.+)$", re.I),
}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}
_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})-([A-Za-z.]+)\.md$")


def horizon_days(text):
    """'3–6 months (...)' -> 183. Takes the upper bound; None if unreadable."""
    m = re.search(r"(\d+)\s*(?:[–—-]\s*(\d+)\s*)?(day|week|month|year)s?", text or "", re.I)
    if not m:
        return None
    n = int(m.group(2) or m.group(1))
    return int(round(n * _UNIT_DAYS[m.group(3).lower()]))


def parse_plan(text):
    plan = {}
    for line in text.splitlines():
        for key, rx in _LABELS.items():
            if key in plan:
                continue
            m = rx.match(line)
            if not m:
                continue
            value = m.group(1).strip()
            if key in ("stop", "target"):
                plan[key] = float(value.replace(",", ""))
            elif key == "horizon":
                plan["horizonText"] = value
                plan["horizonDays"] = horizon_days(value)
            else:
                plan[key] = value
    return plan


def _executed_proposal(text):
    m = re.search(r"status\W*\s*(.*)", text, re.I)
    return bool(m and "EXECUTED" in m.group(1).upper())


def load_plans(dirs):
    """Return {TICKER: plan} from trade logs and executed proposals; newest file wins."""
    plans = {}
    for d in dirs or []:
        for path in sorted(glob.glob(os.path.join(d, "*.md"))):
            m = _FILE.search(os.path.basename(path))
            if not m:
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if os.path.basename(os.path.normpath(d)) == "proposals" and not _executed_proposal(text):
                continue
            plan = parse_plan(text)
            if "stop" not in plan and "target" not in plan:
                continue
            ticker = m.group(2).upper()
            plan.update(date=m.group(1), source=path)
            if ticker not in plans or plans[ticker]["date"] <= plan["date"]:
                plans[ticker] = plan
    return plans


# ---------------------------------------------------------------- inputs

def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def entry_dates(fills):
    """First buy date per symbol after its last sell (the current holding's start)."""
    out = {}
    for f in sorted((fills or {}).get("fills", []), key=lambda f: f.get("timestamp") or f.get("date", "")):
        sym = str(f.get("symbol", "")).upper()
        if f.get("side") == "sell":
            out.pop(sym, None)
        elif f.get("side") == "buy" and sym not in out:
            out[sym] = f.get("date")
    return out


def portfolio_peak(snapshot_dir):
    best = None
    for path in sorted(glob.glob(os.path.join(snapshot_dir or "", "*.json"))):
        try:
            snap = load_json(path)
        except (OSError, ValueError):
            continue
        v = snap.get("portfolioValueUsd")
        if isinstance(v, (int, float)) and (best is None or v > best["value"]):
            best = {"value": v, "date": snap.get("date")}
    return best


def _price(pos):
    for key in ("sessionClose", "price"):
        v = pos.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v), key
    return None, None


# ---------------------------------------------------------------- rules

def review_position(pos, plan, entry_date, as_of, regime_state, bars=None):
    ticker = str(pos.get("ticker", "")).upper()
    shares = pos.get("shares")
    row = {"ticker": ticker, "shares": shares, "action": "HOLD", "reasons": [], "notes": []}

    if not ticker:
        row.update(action="SKIP", reasons=["position has no ticker"])
        return row
    if ticker in RESTRICTED:
        row.update(action="SKIP", reasons=["restricted name (POLICY §0): read for context only, never a sell proposal"])
        return row

    close, price_key = _price(pos)
    avg = pos.get("avgBuyPrice")
    avg = float(avg) if isinstance(avg, (int, float)) and avg > 0 else None
    if close is None:
        row.update(action="SKIP", reasons=["no price in the positions file; not estimating one"])
        return row
    row.update(close=close, priceField=price_key, avgBuyPrice=avg)

    plan = dict(plan or {})
    if plan:
        row["planSource"] = plan.get("source")
    elif avg is not None:
        row["notes"].append("no exit plan on file; using policy defaults (-8% / +16% from avg cost, ~6 months)")
    if "stop" not in plan and avg is not None:
        plan["stop"] = round(avg * (1 - DEFAULT_STOP_PCT), 2)
        plan["stopIsDefault"] = True
    if "target" not in plan and avg is not None:
        plan["target"] = round(avg * (1 + DEFAULT_TARGET_PCT), 2)
        plan["targetIsDefault"] = True
    if plan.get("horizonDays") is None:
        plan["horizonDays"] = DEFAULT_HORIZON_DAYS
        plan["horizonIsDefault"] = True
    if "stop" not in plan or "target" not in plan:
        row.update(action="SKIP", reasons=["no exit plan and no average cost to derive one"])
        return row

    stop, target = plan["stop"], plan["target"]
    row.update(stop=stop, target=target, thesisBreak=plan.get("thesisBreak"))
    gain = close / avg - 1 if avg else None
    row["gainPct"] = round(gain, 4) if gain is not None else None
    if isinstance(shares, (int, float)):
        row["valueAtCloseUsd"] = round(shares * close, 2)

    start = entry_date or plan.get("date")
    horizon_end = None
    if start:
        horizon_end = date.fromisoformat(start[:10]) + timedelta(days=plan["horizonDays"])
        row.update(entryDate=start[:10], horizonEnd=horizon_end.isoformat())
    else:
        row["notes"].append("entry date unknown; time exit not checked")

    sell, review, watch = [], [], []
    if close <= stop:
        sell.append(f"close ${close:,.2f} is at or below the stop ${stop:,.2f}")
    elif close <= stop * (1 + NEAR_STOP_PCT):
        watch.append(f"close ${close:,.2f} is within {NEAR_STOP_PCT:.0%} of the stop ${stop:,.2f}")
    if close >= target:
        sell.append(f"close ${close:,.2f} is at or above the target ${target:,.2f}")
    elif close >= target * (1 - NEAR_TARGET_PCT):
        watch.append(f"close ${close:,.2f} is within {NEAR_TARGET_PCT:.0%} of the target ${target:,.2f}")

    if horizon_end is not None:
        days_left = (horizon_end - as_of).days
        if days_left < 0:
            review.append(f"held past its time horizon (ended {horizon_end.isoformat()})")
        elif days_left <= HORIZON_WARN_DAYS:
            watch.append(f"time horizon ends {horizon_end.isoformat()} ({days_left} days)")

    if gain is not None and gain < 0:
        if regime_state == "risk_off":
            review.append(f"market is risk-off and the position is down {gain:.1%}")
        elif regime_state == "caution":
            watch.append(f"market is in caution and the position is down {gain:.1%}")

    if bars and avg and start:
        since = [b.close for b in bars if b.date >= start[:10]]
        if since:
            peak_gain = max(since) / avg - 1
            row["peakGainPct"] = round(peak_gain, 4)
            if peak_gain >= GIVEBACK_PEAK_GAIN and gain is not None and gain <= GIVEBACK_FLOOR_GAIN:
                review.append(f"was up {peak_gain:.1%} since entry and is now up only {gain:.1%}")

    if sell:
        row.update(action="SELL", reasons=sell + review + watch,
                   proposal={"side": "sell", "shares": shares, "orderType": "market (fractional)",
                             "why": "stop" if close <= stop else "target"})
    elif review:
        row.update(action="REVIEW", reasons=review + watch)
    elif watch:
        row.update(action="WATCH", reasons=watch)
    for k in ("stopIsDefault", "targetIsDefault", "horizonIsDefault"):
        if plan.get(k):
            row.setdefault("defaults", []).append(k.replace("IsDefault", ""))
    return row


def run_review(positions_doc, plans, fills=None, peak=None, spy_bars=None, bars=None, as_of=None):
    as_of = as_of or datetime.now(timezone.utc).date()
    regime = market_regime(spy_bars) if spy_bars else {"state": "unavailable", "reason": "no SPY bars supplied"}
    entries = entry_dates(fills)
    rows = []
    for pos in positions_doc.get("positions", []):
        t = str(pos.get("ticker", "")).upper()
        rows.append(review_position(pos, plans.get(t), entries.get(t), as_of, regime["state"],
                                    (bars or {}).get(t)))
    order = {a: i for i, a in enumerate(ACTIONS)}
    rows.sort(key=lambda r: (order[r["action"]], r["ticker"]))

    portfolio = {"valueUsd": positions_doc.get("portfolioValueUsd"), "peak": peak, "alerts": []}
    v = portfolio["valueUsd"]
    if isinstance(v, (int, float)) and peak and peak["value"] > 0:
        dd = v / peak["value"] - 1
        portfolio["drawdownPct"] = round(dd, 4)
        if dd <= -BREAKER_DRAWDOWN:
            portfolio["alerts"].append(f"portfolio is {dd:.1%} from its peak (${peak['value']:,.2f} on "
                                       f"{peak['date']}): circuit breaker, pause new buys (POLICY §4)")
    if any(r["action"] == "SELL" and r.get("proposal", {}).get("why") == "stop" for r in rows):
        portfolio["alerts"].append("a position breached its stop: circuit breaker, pause new buys (POLICY §4)")

    stale = None
    gen = positions_doc.get("generatedAt")
    if gen:
        try:
            gen_dt = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            as_of_dt = datetime.combine(as_of, datetime.max.time(), tzinfo=timezone.utc)
            hours = (as_of_dt - gen_dt).total_seconds() / 3600
            if hours > STALE_HOURS:
                stale = f"positions file is from {gen} ({hours / 24:.0f} days before {as_of}); refresh it first"
        except ValueError:
            stale = f"could not read generatedAt ({gen})"
    else:
        stale = "positions file has no generatedAt; freshness unknown"

    if stale:  # fail closed: never propose a sell off a price that may be old
        for r in rows:
            if r["action"] == "SELL":
                r["action"] = "REVIEW"
                r["reasons"].insert(0, "positions file is stale, so re-check the live price before acting")
                r["proposal"]["blockedBy"] = "stale data"
        rows.sort(key=lambda r: (order[r["action"]], r["ticker"]))

    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ACTIONS}
    return {"asOf": as_of.isoformat(), "positionsAsOf": gen, "stale": stale, "regime": regime,
            "portfolio": portfolio, "counts": counts, "positions": rows,
            "caveats": ["Proposals only: this review never places, changes or cancels an order.",
                        "Rules are starting guesses (POLICY §4d); thesis-break conditions are listed, not judged.",
                        "Values use the last close in the positions file; a live quote can differ."]}


# ---------------------------------------------------------------- report

def _pct(x):
    return "n/a" if x is None else f"{x:+.1%}"


def to_markdown(result):
    c = result["counts"]
    asks = c["SELL"] + c["REVIEW"]
    lines = [f"# Exit review — {result['asOf']}", ""]
    if asks:
        lines.append(f"**{asks} need your yes** ({c['SELL']} sell, {c['REVIEW']} review), "
                     f"{c['WATCH']} to watch, {c['HOLD']} hold, {c['SKIP']} skipped.")
    else:
        lines.append(f"**Nothing needs you.** {c['WATCH']} to watch, {c['HOLD']} hold, {c['SKIP']} skipped.")
    lines.append("")
    lines.append("Proposals only. Nothing was placed, changed or cancelled. Approve an exit in an "
                 "interactive session, where the funnel reviews the sell order and asks you to "
                 "confirm each one.")
    lines.append("")
    if result["stale"]:
        lines += [f"> ⚠️ Data: {result['stale']}.", ""]
    r = result["regime"]
    lines.append(f"- **Market regime (SPY):** {r['state']}" + (f" — {r['reason']}" if r.get("reason") else ""))
    p = result["portfolio"]
    if p.get("valueUsd") is not None:
        dd = f", {_pct(p.get('drawdownPct'))} from peak" if p.get("drawdownPct") is not None else ""
        lines.append(f"- **Portfolio:** ${p['valueUsd']:,.2f}{dd}")
    for a in p["alerts"]:
        lines.append(f"- **Alert:** {a}")
    lines.append("")

    for action, title in (("SELL", "Proposed sells"), ("REVIEW", "Needs your judgement"),
                          ("WATCH", "Watch"), ("SKIP", "Skipped")):
        rows = [x for x in result["positions"] if x["action"] == action]
        if not rows:
            continue
        lines += [f"## {title}", ""]
        for x in rows:
            head = f"- **{x['ticker']}**"
            if x.get("close") is not None:
                head += f" ${x['close']:,.2f} ({_pct(x.get('gainPct'))} vs cost)"
            if action == "SELL":
                head += f" — sell all {x['shares']} sh (~${x.get('valueAtCloseUsd', 0):,.2f} at last close)"
            lines.append(head + ": " + "; ".join(x["reasons"]) + ".")
            if action in ("SELL", "REVIEW", "WATCH"):
                plan = f"stop ${x['stop']:,.2f} · target ${x['target']:,.2f}"
                if x.get("horizonEnd"):
                    plan += f" · horizon ends {x['horizonEnd']}"
                if x.get("defaults"):
                    plan += f" (policy default: {', '.join(x['defaults'])})"
                lines.append(f"  - Plan: {plan}")
                if x.get("thesisBreak"):
                    lines.append(f"  - Thesis-break to check: {x['thesisBreak']}")
        lines.append("")

    holds = [x for x in result["positions"] if x["action"] == "HOLD"]
    if holds:
        lines += ["## Hold", "", "| Ticker | Close | vs cost | Stop | Target | Horizon ends |",
                  "|---|---|---|---|---|---|"]
        for x in holds:
            lines.append(f"| {x['ticker']} | ${x['close']:,.2f} | {_pct(x.get('gainPct'))} | "
                         f"${x['stop']:,.2f} | ${x['target']:,.2f} | {x.get('horizonEnd', 'n/a')} |")
        lines.append("")
    notes = [(x["ticker"], n) for x in result["positions"] for n in x["notes"]]
    if notes:
        lines += ["## Notes", ""] + [f"- {t}: {n}" for t, n in notes] + [""]
    lines += ["## Caveats", ""] + [f"- {c}" for c in result["caveats"]] + [""]
    return "\n".join(lines)


def one_line(result):
    c = result["counts"]
    return (f"Exit review {result['asOf']}: {c['SELL']} sell, {c['REVIEW']} review, {c['WATCH']} watch, "
            f"{c['HOLD']} hold, {c['SKIP']} skipped · regime {result['regime']['state']}"
            + (" · STALE DATA" if result["stale"] else ""))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--positions", default="data/live.json")
    p.add_argument("--fills", default="data/fills.json")
    p.add_argument("--plans", nargs="*", default=["trades", "proposals"])
    p.add_argument("--snapshots", default="data/snapshots")
    p.add_argument("--bars", help="saved get_equity_historicals output for the holdings (optional)")
    p.add_argument("--spy", help="saved get_equity_historicals output for SPY (optional)")
    p.add_argument("--as-of", help="review date, YYYY-MM-DD (default: today, UTC)")
    p.add_argument("--out", help="directory to write <date>.md and <date>.json")
    a = p.parse_args(argv)
    try:
        positions = load_json(a.positions)
        fills = load_json(a.fills) if a.fills and os.path.exists(a.fills) else None
        bars = load_bars(a.bars) if a.bars else None
        spy = load_bars(a.spy, symbol="SPY").get("SPY", []) if a.spy else None
        as_of = date.fromisoformat(a.as_of) if a.as_of else None
    except (OSError, ValueError) as exc:
        print(f"Exit review: bad input ({exc})", file=sys.stderr)
        return 2
    result = run_review(positions, load_plans(a.plans), fills, portfolio_peak(a.snapshots), spy, bars, as_of)
    md = to_markdown(result)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        base = os.path.join(a.out, result["asOf"])
        with open(base + ".md", "w", encoding="utf-8") as fh:
            fh.write(md)
        with open(base + ".json", "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
        print(one_line(result))
        print(f"Wrote {base}.md and {base}.json")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
