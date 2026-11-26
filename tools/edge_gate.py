"""Edge gate: a name must show an edge before the funnel proposes a buy.

Two checks, both computed from real daily bars the run pulled from the
Robinhood connector (nothing here estimates or fetches anything):

1. Market regime (SPY). Risk-off blocks every new buy proposal; caution
   blocks the auto lane only. This is the "refuse to trade" part.
2. Bracket backtest (the ticker). Replays the exact exit plan the funnel
   will use (-8% stop, +16% target, time horizon) from many past entry
   dates on this ticker, and asks whether that plan made money, beat simply
   holding SPY over the same windows, and held up in both halves of the
   history (a cheap out-of-sample check against a lucky stretch).

Usage (from the repo root):
  python3 -m tools.edge_gate --ticker WFC --bars WFC.json --spy SPY.json \
      [--stop 0.08] [--target 0.16] [--horizon 126] [--out research/edge-gate/...json]

Exit code 0 = PASS, 1 = FAIL (including not enough data), 2 = bad input.
"""

import argparse
import json
import math
import statistics
import sys

try:
    from tools.bars import load_bars
except ImportError:  # run as a plain script: python3 tools/edge_gate.py
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    from bars import load_bars  # type: ignore

# Defaults mirror POLICY.md §4 and §4b. Change them there first, then here.
STOP_PCT = 0.08
TARGET_PCT = 0.16
HORIZON_DAYS = 126          # ~6 months of trading days
ENTRY_STEP = 10             # a new hypothetical entry every 10 trading days
MIN_TRADES = 20
COST_BPS = 10               # round-trip spread/slippage allowance
REGIME_MIN_BARS = 220
VOL_CAUTION = 0.22          # SPY 20-day realised vol, annualised
VOL_RISK_OFF = 0.30


def _sma(values, n):
    return sum(values[-n:]) / n


def realised_vol(closes, n=20):
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    return statistics.pstdev(rets) * math.sqrt(252)


def market_regime(spy_bars):
    """Classify the market from SPY daily bars: risk_on, caution or risk_off."""
    if len(spy_bars) < REGIME_MIN_BARS:
        return {"state": "unavailable", "reason": f"need {REGIME_MIN_BARS} SPY bars, have {len(spy_bars)}",
                "asOf": spy_bars[-1].date if spy_bars else None}
    closes = [b.close for b in spy_bars]
    close, sma50, sma200 = closes[-1], _sma(closes, 50), _sma(closes, 200)
    vol = realised_vol(closes, 20)
    reasons = []
    if (close < sma200 and sma50 < sma200) or vol > VOL_RISK_OFF:
        state = "risk_off"
        if close < sma200 and sma50 < sma200:
            reasons.append("SPY below its 200-day average and the 50-day is below the 200-day")
        if vol > VOL_RISK_OFF:
            reasons.append(f"SPY 20-day volatility {vol:.0%} above {VOL_RISK_OFF:.0%}")
    elif close < sma200 or vol > VOL_CAUTION:
        state = "caution"
        if close < sma200:
            reasons.append("SPY below its 200-day average")
        if vol > VOL_CAUTION:
            reasons.append(f"SPY 20-day volatility {vol:.0%} above {VOL_CAUTION:.0%}")
    else:
        state = "risk_on"
        reasons.append("SPY above its 200-day average with normal volatility")
    return {"state": state, "asOf": spy_bars[-1].date, "spyClose": round(close, 2),
            "sma50": round(sma50, 2), "sma200": round(sma200, 2),
            "vol20": round(vol, 4), "reason": "; ".join(reasons)}


def simulate_trade(bars, i, stop_pct, target_pct, horizon):
    """Buy at bars[i].close, exit on stop, target or horizon. Returns (exit_index, return, how)."""
    entry = bars[i].close
    stop, target = entry * (1 - stop_pct), entry * (1 + target_pct)
    last = min(i + horizon, len(bars) - 1)
    for j in range(i + 1, last + 1):
        bar = bars[j]
        if bar.open <= stop:
            return j, bar.open / entry - 1, "stop_gap"
        if bar.open >= target:
            return j, bar.open / entry - 1, "target_gap"
        if bar.low <= stop:  # stop checked first: if both touch in one day, assume the worse
            return j, stop / entry - 1, "stop"
        if bar.high >= target:
            return j, target / entry - 1, "target"
    return last, bars[last].close / entry - 1, "horizon"


def bracket_backtest(bars, spy_bars, stop_pct=STOP_PCT, target_pct=TARGET_PCT,
                     horizon=HORIZON_DAYS, step=ENTRY_STEP, cost_bps=COST_BPS):
    spy_close = {b.date: b.close for b in spy_bars}
    cost = cost_bps / 10000
    trades = []
    for i in range(0, len(bars) - horizon, step):
        j, ret, how = simulate_trade(bars, i, stop_pct, target_pct, horizon)
        ret -= cost
        entry_d, exit_d = bars[i].date, bars[j].date
        spy_ret = None
        if entry_d in spy_close and exit_d in spy_close:
            spy_ret = spy_close[exit_d] / spy_close[entry_d] - 1
        trades.append({"entry": entry_d, "exit": exit_d, "ret": ret, "how": how, "spyRet": spy_ret})
    return trades


def summarise(trades):
    if not trades:
        return {"n": 0}
    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    excess = [t["ret"] - t["spyRet"] for t in trades if t["spyRet"] is not None]
    gross_loss = -sum(losses)
    return {
        "n": len(rets),
        "winRate": round(len(wins) / len(rets), 4),
        "expectancy": round(statistics.fmean(rets), 4),
        "medianReturn": round(statistics.median(rets), 4),
        "worst": round(min(rets), 4),
        "profitFactor": round(sum(wins) / gross_loss, 3) if gross_loss > 0 else None,
        "excessVsSpy": round(statistics.fmean(excess), 4) if excess else None,
        "benchmarkedTrades": len(excess),
        "exits": {k: sum(1 for t in trades if t["how"] == k)
                  for k in ("target", "target_gap", "stop", "stop_gap", "horizon")},
    }


def run_gate(ticker, bars, spy_bars, stop_pct=STOP_PCT, target_pct=TARGET_PCT, horizon=HORIZON_DAYS):
    regime = market_regime(spy_bars)
    trades = bracket_backtest(bars, spy_bars, stop_pct, target_pct, horizon)
    half = len(trades) // 2
    stats = summarise(trades)
    first, second = summarise(trades[:half]), summarise(trades[half:])

    failures = []
    if regime["state"] in ("risk_off", "unavailable"):
        failures.append(f"market regime {regime['state']}: {regime['reason']}")
    if stats["n"] < MIN_TRADES:
        failures.append(f"only {stats['n']} test entries (need {MIN_TRADES}); not enough history")
    else:
        if stats["expectancy"] <= 0:
            failures.append(f"exit plan lost money on average ({stats['expectancy']:+.2%} per trade)")
        if stats["excessVsSpy"] is None:
            failures.append("could not line up SPY dates to benchmark")
        elif stats["excessVsSpy"] <= 0:
            failures.append(f"did not beat holding SPY over the same windows ({stats['excessVsSpy']:+.2%})")
        if first.get("expectancy", 0) <= 0 or second.get("expectancy", 0) <= 0:
            failures.append("edge not present in both halves of the history "
                            f"(early {first.get('expectancy', 0):+.2%}, recent {second.get('expectancy', 0):+.2%})")

    verdict = "PASS" if not failures else "FAIL"
    return {
        "ticker": ticker.upper(),
        "verdict": verdict,
        "autoLaneAllowed": verdict == "PASS" and regime["state"] == "risk_on",
        "failures": failures,
        "regime": regime,
        "plan": {"stopPct": stop_pct, "targetPct": target_pct, "horizonDays": horizon,
                 "entryStep": ENTRY_STEP, "costBps": COST_BPS},
        "history": {"bars": len(bars), "from": bars[0].date if bars else None,
                    "to": bars[-1].date if bars else None},
        "backtest": stats,
        "earlyHalf": first,
        "recentHalf": second,
        "caveats": [
            "Backtest replays the exit plan on past prices; it does not test the written thesis.",
            "Split-adjusted closes, no dividends; fills assumed at stop/target or the open on a gap.",
        ],
    }


def one_line(result):
    b = result["backtest"]
    if b.get("n", 0) == 0:
        core = "no test entries"
    else:
        exc = b["excessVsSpy"]
        core = (f"{b['n']} entries, win {b['winRate']:.0%}, expectancy {b['expectancy']:+.2%}, "
                f"vs SPY {exc:+.2%}" if exc is not None else
                f"{b['n']} entries, win {b['winRate']:.0%}, expectancy {b['expectancy']:+.2%}")
    return f"Edge gate: {result['verdict']} · regime {result['regime']['state']} · {core}"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticker", required=True)
    p.add_argument("--bars", required=True, help="saved get_equity_historicals output for the ticker")
    p.add_argument("--spy", required=True, help="saved get_equity_historicals output for SPY")
    p.add_argument("--stop", type=float, default=STOP_PCT)
    p.add_argument("--target", type=float, default=TARGET_PCT)
    p.add_argument("--horizon", type=int, default=HORIZON_DAYS)
    p.add_argument("--out", help="write the full result as JSON here")
    a = p.parse_args(argv)
    try:
        bars = load_bars(a.bars, symbol=a.ticker).get(a.ticker.upper(), [])
        spy = load_bars(a.spy, symbol="SPY").get("SPY", [])
    except (OSError, ValueError) as exc:
        print(f"Edge gate: bad input ({exc})", file=sys.stderr)
        return 2
    result = run_gate(a.ticker, bars, spy, a.stop, a.target, a.horizon)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
    print(one_line(result))
    for f in result["failures"]:
        print(f"  - {f}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
