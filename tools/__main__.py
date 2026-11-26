"""One command line for the funnel's read-only research steps.

Claude Code (or you) runs these directly from the repo root. Each reads files a run
saved from the Robinhood connector; none fetches data, and none can place, stage,
change or cancel an order. That is by design: there is no order code in tools/.

  python3 -m tools restricted TICKER ...        Gate 0, from POLICY.md section 0
  python3 -m tools screen   --fundamentals F --quotes Q     Stage 1, POLICY section 4a
  python3 -m tools regime   --spy SPY.json                  market regime only (cheap first check)
  python3 -m tools gate     --ticker T --bars B --spy S     Gate 0 + Stage 4b edge gate
  python3 -m tools factors  --bars UNIVERSE.json --out ...  monthly factor research
  python3 -m tools satellite --obs OBS.csv --ticker T       Stage 2b Satellite Scout
  python3 -m tools research --ticker T --bars B --spy S     all of the above for one name,
                                                            printed as the output template lines

Run `python3 -m tools <command> --help` for each command's options.
"""

import argparse
import glob
import json
import os
import sys
from datetime import date

from tools import edge_gate, factor_research, restricted, satellite_scout, screen
from tools.bars import load_bars

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OBS = os.path.join(REPO, "research", "satellite", "observations.csv")
DEFAULT_FACTORS = os.path.join(REPO, "research", "factors")
STALE_IMAGE_DAYS = 60


def cmd_regime(argv):
    p = argparse.ArgumentParser(prog="python3 -m tools regime",
                                description="Market regime from SPY daily bars (POLICY section 4b). "
                                            "Exit 0 = risk_on, 1 = caution, risk_off or unavailable, 2 = bad input.")
    p.add_argument("--spy", required=True, help="saved get_equity_historicals output for SPY")
    a = p.parse_args(argv)
    try:
        spy = load_bars(a.spy, symbol="SPY").get("SPY", [])
    except (OSError, ValueError) as exc:
        print(f"Regime: bad input ({exc})", file=sys.stderr)
        return 2
    r = edge_gate.market_regime(spy)
    print(regime_line(r))
    return 0 if r["state"] == "risk_on" else 1


def regime_line(r):
    if r["state"] == "unavailable":
        return f"Regime: unavailable (counts as risk_off) · {r['reason']}"
    effect = {"risk_on": "buys allowed", "caution": "no auto-lane buys",
              "risk_off": "no new buys this run"}[r["state"]]
    return (f"Regime: {r['state']} as of {r['asOf']} · {effect} · SPY {r['spyClose']} vs 200d {r['sma200']}, "
            f"20d vol {r['vol20']:.0%} · {r['reason']}")


def cmd_gate(argv):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--ticker")
    known, _ = pre.parse_known_args(argv)
    if known.ticker:
        status, reason = restricted.gate0([known.ticker])[known.ticker.strip().upper()]
        if status != "clear":
            print(f"Gate 0: {status} · {reason}. Stopping before the edge gate.")
            return 1
    return edge_gate.main(argv)


def latest_factor_report(factors_dir=DEFAULT_FACTORS):
    files = sorted(glob.glob(os.path.join(factors_dir, "*.json")))
    if not files:
        return None, None
    with open(files[-1], encoding="utf-8") as fh:
        return os.path.basename(files[-1])[:-5], json.load(fh)


def factor_line(factors_dir=DEFAULT_FACTORS):
    try:
        name, report = latest_factor_report(factors_dir)
    except (OSError, ValueError):
        return "Factor evidence: latest report unreadable; treat every factor as unproven"
    if not report or not report.get("factors"):
        return "Factor evidence: no report yet"
    groups = {}
    for factor, info in report["factors"].items():
        groups.setdefault(info.get("verdict", "unproven"), []).append(factor)
    parts = [f"{v}: {', '.join(sorted(groups[v]))}" for v in ("supported", "contrary", "unproven") if v in groups]
    return f"Factor evidence: report {name} · " + " · ".join(parts)


def satellite_line(ticker, obs_path=DEFAULT_OBS, today=None):
    if not obs_path or not os.path.exists(obs_path):
        return "Satellite: no observations"
    try:
        rows, _ = satellite_scout.load_observations(obs_path)
    except OSError:
        return "Satellite: observations file unreadable"
    summary = satellite_scout.summarise(satellite_scout.site_changes(rows), ticker).get(ticker.upper())
    if not summary:
        return "Satellite: no observations"
    med = f"{summary['medianYoY']:+.0%}" if summary["medianYoY"] is not None else "n/a"
    line = (f"Satellite: {summary['read']} · median YoY {med} across {summary['sitesCompared']} of "
            f"{summary['sitesLogged']} sites · latest image {summary['latestImage']}")
    age = ((today or date.today()) - date.fromisoformat(str(summary["latestImage"]))).days
    if age > STALE_IMAGE_DAYS:
        line += f" (stale: {age} days old)"
    return line


def cmd_research(argv):
    p = argparse.ArgumentParser(prog="python3 -m tools research",
                                description="Gate 0, regime, edge gate, factor evidence and Satellite Scout for "
                                            "one ticker, printed as the SKILL.md output template lines. Exit 0 = "
                                            "edge gate PASS, 1 = restricted or FAIL, 2 = bad input.")
    p.add_argument("--ticker", required=True)
    p.add_argument("--bars", required=True, help="saved get_equity_historicals output (may also hold SPY)")
    p.add_argument("--spy", help="saved SPY bars, if not in the --bars file")
    p.add_argument("--stop", type=float, default=edge_gate.STOP_PCT)
    p.add_argument("--target", type=float, default=edge_gate.TARGET_PCT)
    p.add_argument("--horizon", type=int, default=edge_gate.HORIZON_DAYS)
    p.add_argument("--obs", default=DEFAULT_OBS, help="Satellite Scout observations CSV")
    p.add_argument("--factors-dir", default=DEFAULT_FACTORS)
    p.add_argument("--out", help="write the edge gate JSON here")
    a = p.parse_args(argv)
    ticker = a.ticker.strip().upper()

    status, reason = restricted.gate0([ticker])[ticker]
    if status != "clear":
        print(f"{ticker}    FAIL at Gate 0\nRestricted check: {status} · {reason}")
        return 1
    try:
        bars = load_bars(a.bars, symbol=ticker).get(ticker, [])
        spy = load_bars(a.spy or a.bars, symbol="SPY").get("SPY", [])
    except (OSError, ValueError) as exc:
        print(f"Research: bad input ({exc})", file=sys.stderr)
        return 2
    result = edge_gate.run_gate(ticker, bars, spy, a.stop, a.target, a.horizon)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
    verdict = "edge gate PASS" if result["verdict"] == "PASS" else "FAIL at Stage 4b"
    lines = [
        f"{ticker}    {verdict}",
        "Restricted check: clear",
        regime_line(result["regime"]),
        factor_line(a.factors_dir),
        satellite_line(ticker, a.obs),
        edge_gate.one_line(result).replace("Edge gate: ", "Edge gate:        ", 1),
    ]
    lines += [f"  - {f}" for f in result["failures"]]
    lines.append(f"History: {result['history']['bars']} bars, {result['history']['from']} to {result['history']['to']}")
    lines.append("Read-only research: thesis, sizing and any order stay with the funnel and the operator.")
    print("\n".join(lines))
    return 0 if result["verdict"] == "PASS" else 1


COMMANDS = {
    "restricted": restricted.main,
    "screen": screen.main,
    "regime": cmd_regime,
    "gate": cmd_gate,
    "factors": factor_research.main,
    "satellite": satellite_scout.main,
    "research": cmd_research,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if argv else 2
    cmd = COMMANDS.get(argv[0])
    if cmd is None:
        print(f"Unknown command '{argv[0]}'. Commands: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    return cmd(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
