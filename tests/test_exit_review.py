"""Tests for the nightly exit review. Run from the repo root: python3 -m unittest discover tests"""

import ast
import json
import os
import tempfile
import unittest
from datetime import date

from tools import exit_review as er
from tools.bars import Bar

AS_OF = date(2026, 11, 26)


def doc(*positions, generated="2026-11-26T02:00:00Z", value=1000.0):
    return {"generatedAt": generated, "portfolioValueUsd": value, "positions": list(positions)}


def pos(ticker, close, avg=100.0, shares=1.0):
    return {"ticker": ticker, "shares": shares, "avgBuyPrice": avg, "price": close, "sessionClose": close}


def plan(stop=92.0, target=116.0, start="2026-11-01", horizon=183, thesis="EPS miss"):
    return {"stop": stop, "target": target, "date": start, "horizonDays": horizon,
            "thesisBreak": thesis, "source": f"trades/{start}-X.md"}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def by_ticker(result):
    return {r["ticker"]: r for r in result["positions"]}


class PlanParsingTests(unittest.TestCase):
    def test_trade_log_formats(self):
        text = ("## Exit Plan\n\n- **Stop:** $1,220.39 (-8% from fill)\n"
                "- **Target:** $277.88 (+16% from fill)\n- **Horizon:** 3–6 months (through Q3)\n"
                "- **Thesis-break:** Q2 earnings miss\n")
        p = er.parse_plan(text)
        self.assertEqual((p["stop"], p["target"], p["horizonDays"]), (1220.39, 277.88, 183))
        self.assertEqual(p["thesisBreak"], "Q2 earnings miss")

    def test_proposal_formats(self):
        text = ("- Stop-loss: $43.48 (-8% from fill)\n- Profit target: $54.82\n"
                "- Time horizon: 6–8 weeks\n- **Thesis-break condition:** dividend cut\n")
        p = er.parse_plan(text)
        self.assertEqual((p["stop"], p["target"], p["horizonDays"]), (43.48, 54.82, 56))
        self.assertEqual(p["thesisBreak"], "dividend cut")

    def test_only_executed_proposals_and_newest_log_count(self):
        with tempfile.TemporaryDirectory() as d:
            trades, props = os.path.join(d, "trades"), os.path.join(d, "proposals")
            os.makedirs(trades)
            os.makedirs(props)
            for name, body in {
                "trades/2026-06-01-ABC.md": "- **Stop:** $10\n- **Target:** $20\n",
                "trades/2026-07-01-ABC.md": "- **Stop:** $11\n- **Target:** $21\n",
                "proposals/2026-06-02-DEF.md": "**Status:** EXECUTED (auto-lane)\n- Stop-loss: $5\n- Profit target: $9\n",
                "proposals/2026-06-02-GHI.md": "**Status:** Pending manual review\n- Stop-loss: $5\n- Profit target: $9\n",
            }.items():
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write(body)
            plans = er.load_plans([trades, props])
        self.assertEqual(sorted(plans), ["ABC", "DEF"])
        self.assertEqual(plans["ABC"]["stop"], 11.0)


class RuleTests(unittest.TestCase):
    def review(self, *positions, plans=None, **kw):
        return er.run_review(doc(*positions), plans or {}, as_of=AS_OF, **kw)

    def test_stop_and_target_propose_sells(self):
        r = by_ticker(self.review(pos("LOW", 91.0), pos("HIGH", 117.0),
                                  plans={"LOW": plan(), "HIGH": plan()}))
        self.assertEqual(r["LOW"]["action"], "SELL")
        self.assertEqual(r["LOW"]["proposal"]["why"], "stop")
        self.assertEqual(r["HIGH"]["action"], "SELL")
        self.assertEqual(r["HIGH"]["proposal"]["why"], "target")

    def test_stop_breach_trips_the_breaker_alert(self):
        res = self.review(pos("LOW", 91.0), plans={"LOW": plan()})
        self.assertTrue(any("breached its stop" in a for a in res["portfolio"]["alerts"]))

    def test_near_levels_and_horizon_are_watch(self):
        r = by_ticker(self.review(pos("NS", 93.5), pos("NT", 113.0), pos("HZ", 100.0),
                                  plans={"NS": plan(), "NT": plan(),
                                         "HZ": plan(start="2026-06-01", horizon=180)}))
        self.assertEqual(r["NS"]["action"], "WATCH")
        self.assertEqual(r["NT"]["action"], "WATCH")
        self.assertEqual(r["HZ"]["action"], "WATCH")  # horizon ends 2026-11-28

    def test_past_horizon_is_review_not_sell(self):
        r = by_ticker(self.review(pos("OLD", 104.0), plans={"OLD": plan(start="2026-05-01", horizon=91)}))
        self.assertEqual(r["OLD"]["action"], "REVIEW")
        self.assertNotIn("proposal", r["OLD"])

    def test_regime_only_flags_losers(self):
        plans = {"DN": plan(), "UP": plan()}
        positions = (pos("DN", 97.0), pos("UP", 104.0))
        off = by_ticker(self.review(*positions, plans=plans,
                                    spy_bars=_spy(down=True)))
        self.assertEqual(off["DN"]["action"], "REVIEW")
        self.assertEqual(off["UP"]["action"], "HOLD")
        calm = by_ticker(self.review(*positions, plans=plans, spy_bars=_spy(down=False)))
        self.assertEqual(calm["DN"]["action"], "HOLD")

    def test_giveback_needs_bars(self):
        bars = {"GB": [Bar("2026-11-05", 100, 100, 100, 100), Bar("2026-11-12", 112, 112, 112, 112),
                       Bar("2026-11-25", 101, 101, 101, 101)]}
        r = by_ticker(self.review(pos("GB", 101.0), plans={"GB": plan()}, bars=bars))
        self.assertEqual(r["GB"]["action"], "REVIEW")
        self.assertAlmostEqual(r["GB"]["peakGainPct"], 0.12)
        r = by_ticker(self.review(pos("GB", 101.0), plans={"GB": plan()}))
        self.assertEqual(r["GB"]["action"], "HOLD")

    def test_no_plan_uses_policy_defaults(self):
        r = by_ticker(self.review(pos("DEF", 91.9, avg=100.0)))["DEF"]
        self.assertEqual((r["stop"], r["target"]), (92.0, 116.0))
        self.assertEqual(r["action"], "SELL")
        self.assertIn("stop", r["defaults"])

    def test_restricted_never_gets_a_proposal(self):
        r = by_ticker(self.review(pos("SEZL", 1.0), plans={"SEZL": plan()}))["SEZL"]
        self.assertEqual(r["action"], "SKIP")
        self.assertNotIn("proposal", r)

    def test_missing_price_or_cost_fails_closed(self):
        r = by_ticker(self.review({"ticker": "NOP", "shares": 1, "avgBuyPrice": 10},
                                  {"ticker": "NOC", "shares": 1, "price": 10}))
        self.assertEqual(r["NOP"]["action"], "SKIP")
        self.assertEqual(r["NOC"]["action"], "SKIP")

    def test_stale_positions_downgrade_sells(self):
        res = er.run_review(doc(pos("LOW", 91.0), generated="2026-07-07T02:00:00Z"),
                            {"LOW": plan()}, as_of=AS_OF)
        self.assertIsNotNone(res["stale"])
        row = by_ticker(res)["LOW"]
        self.assertEqual(row["action"], "REVIEW")
        self.assertEqual(row["proposal"]["blockedBy"], "stale data")

    def test_drawdown_breaker(self):
        res = er.run_review(doc(value=880.0), {}, peak={"value": 1000.0, "date": "2026-10-01"}, as_of=AS_OF)
        self.assertTrue(any("circuit breaker" in a for a in res["portfolio"]["alerts"]))

    def test_entry_date_resets_after_a_sell(self):
        fills = {"fills": [{"symbol": "T", "side": "buy", "date": "2026-01-02"},
                           {"symbol": "T", "side": "sell", "date": "2026-02-02"},
                           {"symbol": "T", "side": "buy", "date": "2026-03-02"},
                           {"symbol": "T", "side": "buy", "date": "2026-04-02"}]}
        self.assertEqual(er.entry_dates(fills), {"T": "2026-03-02"})


class ReportAndSafetyTests(unittest.TestCase):
    def test_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            positions = os.path.join(d, "live.json")
            with open(positions, "w", encoding="utf-8") as fh:
                json.dump(doc(pos("LOW", 91.0)), fh)
            out = os.path.join(d, "out")
            code = er.main(["--positions", positions, "--fills", "", "--plans", "--snapshots", d,
                            "--as-of", "2026-11-26", "--out", out])
            self.assertEqual(code, 0)
            md = read(os.path.join(out, "2026-11-26.md"))
            self.assertIn("1 need your yes", md)
            self.assertIn("Nothing was placed", md)
            self.assertEqual(json.loads(read(os.path.join(out, "2026-11-26.json")))["counts"]["SELL"], 1)
            self.assertEqual(er.main(["--positions", os.path.join(d, "missing.json")]), 2)

    def test_module_imports_nothing_that_could_trade(self):
        src = read(er.__file__)
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        allowed = {"argparse", "glob", "json", "os", "re", "sys", "datetime", "tools", "bars", "edge_gate", ""}
        self.assertLessEqual(imported, allowed)
        for word in ("urllib", "http", "socket", "subprocess", "requests"):
            self.assertNotIn(word, imported)


def _spy(down):
    from tests.test_tools import make_bars, trend
    closes = trend(260, -0.002 if down else 0.0008, start=500.0)
    return make_bars(closes)


if __name__ == "__main__":
    unittest.main()
