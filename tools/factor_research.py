"""Factor research: which signals actually predicted returns, before they feed the funnel.

Takes daily bars for a universe of tickers (saved from the Robinhood
connector's get_equity_historicals) and, every 21 trading days, ranks the
universe on each factor and checks how well that ranking lined up with the
next 21 trading days of returns (Spearman rank "information coefficient", IC).
A factor earns "supported" only if its average IC is positive, statistically
meaningful (t >= 2), and holds in both halves of the history.

Built-in factors use prices only, because those can be rebuilt as of any past
date. Fundamentals (P/E, P/B) cannot: the connector only serves today's values,
and testing today's P/E against past returns is look-ahead bias. Point-in-time
values you do have can be supplied with --extra (CSV: date,symbol,factor,value).

Usage (from the repo root):
  python3 -m tools.factor_research --bars universe.json [--extra pit.csv] \
      [--out research/factors/2026-11-26]   # writes .json and .md
"""

import argparse
import csv
import json
import math
import statistics
import sys

try:
    from tools.bars import load_bars
except ImportError:
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    from bars import load_bars  # type: ignore

FWD_DAYS = 21
LOOKBACK = 252
MIN_NAMES = 10
MIN_PERIODS = 24
T_SUPPORTED = 2.0

FACTOR_NOTES = {
    "mom_12_1": "12-month momentum, skipping the latest month",
    "rev_1m": "1-month reversal (last month's losers ranked high)",
    "near_52w_high": "price as a share of its 52-week high",
    "low_vol_60d": "low 60-day volatility ranked high",
    "trend_200d": "distance above the 200-day average",
}


def price_factors(bars, t):
    """Factor values for one symbol as of index t (needs LOOKBACK bars before t)."""
    c = [b.close for b in bars]
    rets = [c[k] / c[k - 1] - 1 for k in range(t - 59, t + 1)]
    return {
        "mom_12_1": c[t - 21] / c[t - LOOKBACK] - 1,
        "rev_1m": -(c[t] / c[t - 21] - 1),
        "near_52w_high": c[t] / max(b.high for b in bars[t - LOOKBACK + 1:t + 1]),
        "low_vol_60d": -statistics.pstdev(rets),
        "trend_200d": c[t] / (sum(c[t - 199:t + 1]) / 200) - 1,
    }


def ranks(values):
    order = sorted(range(len(values)), key=lambda k: values[k])
    out = [0.0] * len(values)
    k = 0
    while k < len(order):
        m = k
        while m + 1 < len(order) and values[order[m + 1]] == values[order[k]]:
            m += 1
        avg = (k + m) / 2 + 1
        for idx in order[k:m + 1]:
            out[idx] = avg
        k = m + 1
    return out


def spearman(x, y):
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def load_extra(path):
    """{(date, SYMBOL): {factor: value}} from a point-in-time CSV."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (row["date"][:10], row["symbol"].strip().upper())
            out.setdefault(key, {})[row["factor"].strip()] = value
    return out


def cross_sections(universe, extra=None):
    """Yield (date, {factor: [(value, fwd_return), ...]}) every FWD_DAYS on a shared calendar."""
    index = {sym: {b.date: k for k, b in enumerate(bars)} for sym, bars in universe.items()}
    calendar = sorted(set().union(*[set(ix) for ix in index.values()])) if index else []
    for pos in range(LOOKBACK, len(calendar) - FWD_DAYS, FWD_DAYS):
        date = calendar[pos]
        section = {}
        for sym, bars in universe.items():
            t = index[sym].get(date)
            if t is None or t < LOOKBACK or t + FWD_DAYS >= len(bars):
                continue
            fwd = bars[t + FWD_DAYS].close / bars[t].close - 1
            values = price_factors(bars, t)
            if extra:
                values.update(extra.get((date, sym), {}))
            for name, value in values.items():
                section.setdefault(name, []).append((value, fwd))
        yield date, section


def _stats(ics):
    if len(ics) < 2:
        return {"periods": len(ics), "meanIC": ics[0] if ics else None, "t": None}
    mean, sd = statistics.fmean(ics), statistics.stdev(ics)
    return {"periods": len(ics), "meanIC": round(mean, 4),
            "t": round(mean / (sd / math.sqrt(len(ics))), 2) if sd else None}


def research(universe, extra=None):
    per_factor = {}
    dates = []
    for date, section in cross_sections(universe, extra):
        dates.append(date)
        for name, pairs in section.items():
            if len(pairs) < MIN_NAMES:
                continue
            xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
            ic = spearman(xs, ys)
            if ic is None:
                continue
            ordered = sorted(pairs, key=lambda p: p[0])
            q = max(1, len(ordered) // 5)
            spread = statistics.fmean(p[1] for p in ordered[-q:]) - statistics.fmean(p[1] for p in ordered[:q])
            per_factor.setdefault(name, []).append((date, ic, spread))

    results = {}
    for name, rows in sorted(per_factor.items()):
        ics = [r[1] for r in rows]
        half = len(ics) // 2
        overall, early, recent = _stats(ics), _stats(ics[:half]), _stats(ics[half:])
        if overall["periods"] < MIN_PERIODS or overall["t"] is None:
            verdict = "unproven"
            why = f"only {overall['periods']} periods (need {MIN_PERIODS})"
        elif overall["t"] >= T_SUPPORTED and early["meanIC"] > 0 and recent["meanIC"] > 0:
            verdict, why = "supported", "positive IC, t >= 2, positive in both halves"
        elif overall["t"] <= -T_SUPPORTED:
            verdict, why = "contrary", "IC reliably negative: the signal pointed the wrong way"
        else:
            verdict = "unproven"
            why = "IC not reliably positive" if overall["t"] < T_SUPPORTED else "not stable across both halves"
        results[name] = {
            "verdict": verdict, "why": why, "note": FACTOR_NOTES.get(name, "supplied point-in-time factor"),
            **overall, "earlyMeanIC": early["meanIC"], "recentMeanIC": recent["meanIC"],
            "hitRate": round(sum(1 for i in ics if i > 0) / len(ics), 3),
            "topMinusBottom21d": round(statistics.fmean(r[2] for r in rows), 4),
        }
    last_bars = [bars[-1].date for bars in universe.values() if bars]
    return {
        "dataThrough": max(last_bars) if last_bars else None,
        "universe": sorted(universe),
        "names": len(universe),
        "periods": len(dates),
        "from": dates[0] if dates else None,
        "to": dates[-1] if dates else None,
        "forwardDays": FWD_DAYS,
        "factors": results,
        "caveats": [
            "Universe is today's tickers, so names that were delisted are missing (survivorship bias).",
            "Price factors only unless point-in-time values were supplied; current fundamentals are never back-tested.",
            "A supported factor shows past predictive power, not a guarantee; re-run monthly.",
        ],
    }


def to_markdown(report, title_date):
    lines = [f"# Factor research — {title_date}", "",
             f"{report['names']} tickers, {report['periods']} monthly cross-sections "
             f"(formed {report['from']} to {report['to']}), {report['forwardDays']}-day forward returns, "
             f"data through {report['dataThrough']}.", "",
             "Verdicts: **supported** = may be cited as evidence in a thesis; **unproven** = no evidence "
             "either way; **contrary** = it pointed the wrong way here, so flag any thesis leaning on it.", "",
             "| Factor | Verdict | Mean IC | t | Early / recent IC | Hit rate | Top − bottom quintile |",
             "|---|---|---|---|---|---|---|"]
    for name, f in report["factors"].items():
        lines.append(f"| {name} — {f['note']} | **{f['verdict']}** | {f['meanIC']} | {f['t']} | "
                     f"{f['earlyMeanIC']} / {f['recentMeanIC']} | {f['hitRate']:.0%} | {f['topMinusBottom21d']:+.2%} |")
    lines += ["", "Caveats:"] + [f"- {c}" for c in report["caveats"]] + [""]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bars", required=True, help="saved get_equity_historicals output for the universe")
    p.add_argument("--extra", help="optional point-in-time CSV: date,symbol,factor,value")
    p.add_argument("--out", help="path prefix; writes <out>.json and <out>.md")
    p.add_argument("--date", help="report date for the title (default: last bar date)")
    a = p.parse_args(argv)
    try:
        universe = {s: b for s, b in load_bars(a.bars).items() if b}
        extra = load_extra(a.extra) if a.extra else None
    except (OSError, ValueError, KeyError) as exc:
        print(f"Factor research: bad input ({exc})", file=sys.stderr)
        return 2
    report = research(universe, extra)
    title = a.date or report["dataThrough"] or "no data"
    if a.out:
        with open(a.out + ".json", "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        with open(a.out + ".md", "w", encoding="utf-8") as fh:
            fh.write(to_markdown(report, title))
    for name, f in report["factors"].items():
        print(f"{name}: {f['verdict']} (mean IC {f['meanIC']}, t {f['t']}, {f['periods']} periods)")
    if not report["factors"]:
        print(f"No factor had {MIN_NAMES}+ names with {LOOKBACK + FWD_DAYS}+ bars; nothing tested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
