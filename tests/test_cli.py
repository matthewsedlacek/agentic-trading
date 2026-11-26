"""Tests for the read-only command line (python3 -m tools) and the Claude Code commands."""

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import date

from tools import __main__ as cli
from tools import restricted, screen
from tests.test_tools import make_bars, trend

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMANDS_DIR = os.path.join(REPO, ".claude", "commands")


def fund(symbol, **over):
    """A get_equity_fundamentals row in the connector's real shape (strings), WFC-like by default."""
    row = {"symbol": symbol, "market_cap": "242939762744.78", "pe_ratio": "11.408034", "pb_ratio": "1.531260",
           "average_volume": "11067224.56", "average_volume_30_days": "12111962.56", "sector": "Finance"}
    row.update(over)
    return row


def quote(symbol, price, **over):
    q = {"symbol": symbol, "last_trade_price": str(price), "has_traded": True, "state": "active"}
    q.update(over)
    return {"quote": q, "close": {"symbol": symbol, "price": str(price)}}


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(argv)
    return code, out.getvalue()


class RestrictedTests(unittest.TestCase):
    def test_reads_sezl_from_policy(self):
        self.assertIn("SEZL", restricted.load_restricted())

    def test_restricted_share_class_and_unclean_symbols_block(self):
        names = {"SEZL"}
        self.assertEqual(restricted.check("sezl", names)[0], "restricted")
        self.assertEqual(restricted.check("SEZL.W", names)[0], "restricted")
        self.assertEqual(restricted.check("Sezzle Inc", names)[0], "unresolved")
        self.assertEqual(restricted.check("", names)[0], "unresolved")
        self.assertEqual(restricted.check("BRK.B", names)[0], "clear")

    def test_unreadable_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            empty = os.path.join(d, "POLICY.md")
            with open(empty, "w") as fh:
                fh.write("# no restricted section here\n")
            for path in (empty, os.path.join(d, "missing.md")):
                status, _ = restricted.gate0(["WFC"], path)["WFC"]
                self.assertEqual(status, "unresolved")

    def test_cli_exit_codes(self):
        self.assertEqual(run(["restricted", "WFC", "KO"])[0], 0)
        code, out = run(["restricted", "WFC", "SEZL"])
        self.assertEqual(code, 1)
        self.assertIn("SEZL: restricted", out)


class ScreenTests(unittest.TestCase):
    def test_gates(self):
        fundamentals = {
            "WFC": fund("WFC"),
            "KO": fund("KO", pb_ratio="11.2339", pe_ratio="28.78", sector="Consumer Non-Durables"),
            "LOSS": fund("LOSS", pe_ratio="-4.0"),
            "TINY": fund("TINY", market_cap="900000000"),
            "THIN": fund("THIN", average_volume_30_days="120000", average_volume="120000"),
            "NOPE": fund("NOPE", pe_ratio=None),
            "BANK": fund("BANK", pe_ratio="9.0"),
            "SEZL": fund("SEZL", sector="Technology Services"),
        }
        prices = {"WFC": 80.93, "KO": 97.65, "LOSS": 20, "TINY": 20, "THIN": 20, "NOPE": 20, "BANK": 450, "SEZL": 140}
        result = screen.run_screen(fundamentals, prices)
        self.assertEqual([r["symbol"] for r in result["shortlist"]], ["WFC"])
        self.assertTrue(result["shortlist"][0]["sectorPick"])
        reasons = {r["symbol"]: "; ".join(r["failures"]) for r in result["dropped"]}
        self.assertIn("P/B 11.2 above 8", reasons["KO"])
        self.assertIn("P/E -4.0 outside 0-40", reasons["LOSS"])
        self.assertIn("market cap", reasons["TINY"])
        self.assertIn("average volume", reasons["THIN"])
        self.assertEqual(reasons["NOPE"], "P/E unavailable")
        self.assertIn("price $450.00", reasons["BANK"])
        # The restricted name is counted, never listed.
        self.assertEqual(result["restrictedExcluded"], 1)
        self.assertNotIn("SEZL", json.dumps(result))

    def test_missing_price_is_unavailable_and_one_pick_per_sector(self):
        fundamentals = {"AAA": fund("AAA", pe_ratio="15"), "BBB": fund("BBB", pe_ratio="10"), "CCC": fund("CCC")}
        result = screen.run_screen(fundamentals, {"AAA": 50, "BBB": 60})
        self.assertEqual([(r["symbol"], r["sectorPick"]) for r in result["shortlist"]],
                         [("BBB", True), ("AAA", False)])
        self.assertEqual([(r["symbol"], r["failures"]) for r in result["dropped"]], [("CCC", ["price unavailable"])])

    def test_cli_reads_real_connector_shapes(self):
        with tempfile.TemporaryDirectory() as d:
            f, q = os.path.join(d, "f.json"), os.path.join(d, "q.json")
            with open(f, "w") as fh:
                json.dump({"data": {"results": [fund("WFC")]}}, fh)
            with open(q, "w") as fh:
                json.dump({"data": {"results": [quote("WFC", 80.93), quote("XYZ", 5, state="inactive")]}}, fh)
            self.assertEqual(screen.load_prices(q), {"WFC": 80.93})
            code, out = run(["screen", "--fundamentals", f, "--quotes", q])
            self.assertEqual(code, 0)
            self.assertIn("PASS WFC: $80.93", out)
            self.assertEqual(run(["screen", "--fundamentals", os.path.join(d, "x.json"), "--quotes", q])[0], 2)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        spy = make_bars(trend(900, 0.0003, noise=0.004))
        good = make_bars(trend(900, 0.0015, noise=0.006, seed=2))
        self.both = os.path.join(d, "both.json")
        with open(self.both, "w") as fh:
            json.dump({"data": {"results": [{"symbol": "AAA", "bars": [b.__dict__ for b in good]},
                                            {"symbol": "SPY", "bars": [b.__dict__ for b in spy]}]}}, fh)
        self.factors = os.path.join(d, "factors")
        os.mkdir(self.factors)

    def test_help_and_unknown(self):
        self.assertEqual(run(["--help"])[0], 0)
        self.assertEqual(run([])[0], 2)
        self.assertEqual(run(["buy"])[0], 2)

    def test_regime(self):
        code, out = run(["regime", "--spy", self.both])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("Regime: risk_on"))

    def test_gate_runs_gate0_first(self):
        code, out = run(["gate", "--ticker", "SEZL", "--bars", self.both, "--spy", self.both])
        self.assertEqual(code, 1)
        self.assertIn("Gate 0: restricted", out)
        code, out = run(["gate", "--ticker", "AAA", "--bars", self.both, "--spy", self.both])
        self.assertEqual(code, 0, out)

    def test_research_prints_template_lines(self):
        with open(os.path.join(self.factors, "2026-11-01.json"), "w") as fh:
            json.dump({"factors": {"mom_12_1": {"verdict": "supported"}, "low_vol_60d": {"verdict": "contrary"},
                                   "rev_1m": {"verdict": "unproven"}}}, fh)
        code, out = run(["research", "--ticker", "aaa", "--bars", self.both, "--factors-dir", self.factors,
                         "--obs", os.path.join(self.tmp.name, "none.csv")])
        self.assertEqual(code, 0, out)
        self.assertIn("AAA    edge gate PASS", out)
        self.assertIn("Restricted check: clear", out)
        self.assertIn("Factor evidence: report 2026-11-01 · supported: mom_12_1 · contrary: low_vol_60d", out)
        self.assertIn("Satellite: no observations", out)
        self.assertRegex(out, r"Edge gate: +PASS · regime risk_on")

    def test_research_stops_at_gate0_and_without_reports(self):
        code, out = run(["research", "--ticker", "SEZL", "--bars", self.both])
        self.assertEqual(code, 1)
        self.assertIn("FAIL at Gate 0", out)
        self.assertNotIn("Edge gate", out)
        self.assertEqual(cli.factor_line(self.factors), "Factor evidence: no report yet")

    def test_stale_satellite_imagery_is_flagged(self):
        obs = os.path.join(self.tmp.name, "obs.csv")
        with open(obs, "w") as fh:
            fh.write("ticker,site_id,capture_date,provider,image_id,metric,value\n")
            for k in range(3):
                fh.write(f"AAA,s{k},2025-06-02,prov,img{k}a,cars,100\nAAA,s{k},2026-06-01,prov,img{k}b,cars,110\n")
        line = cli.satellite_line("AAA", obs, today=date(2026, 11, 26))
        self.assertIn("Satellite: up", line)
        self.assertIn("stale", line)


ORDER_WORDS = re.compile(r"place_|review_|preview_|cancel_|exercise_|create_|update_|delete_|remove_|add_to|"
                         r"decline_|follow_|mark_alerts", re.I)


class ReadOnlyTests(unittest.TestCase):
    """Guards that keep these commands research-only."""

    def test_commands_allow_only_read_tools(self):
        files = sorted(f for f in os.listdir(COMMANDS_DIR) if f.endswith(".md"))
        self.assertEqual(files, ["backtest.md", "factor-research.md", "regime.md", "research.md", "screen.md"])
        for name in files:
            with open(os.path.join(COMMANDS_DIR, name)) as fh:
                text = fh.read()
            allowed = re.search(r"^allowed-tools:(.*)$", text, re.M).group(1)
            tools = [t.strip() for t in allowed.split(",")]
            for tool in tools:
                self.assertFalse(ORDER_WORDS.search(tool), f"{name} allows {tool}")
                self.assertTrue(tool.startswith(("Bash(python3 -m tools", "Write(research/", "mcp__Robinhood__get_")),
                                f"{name} allows {tool}")
            self.assertIn("Read-only", text)
            self.assertIn("python3 -m tools restricted", text)

    def test_tools_have_no_network_or_order_code(self):
        tools_dir = os.path.join(REPO, "tools")
        for name in os.listdir(tools_dir):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(tools_dir, name)) as fh:
                src = fh.read()
            self.assertNotRegex(src, r"^\s*(import|from)\s+(urllib|http|socket|requests|subprocess)\b",
                                f"{name} imports network or process code")
            self.assertNotRegex(src, r"place_equity_order|place_option_order|cancel_equity_order", name)
        self.assertEqual(set(cli.COMMANDS),
                         {"restricted", "screen", "regime", "gate", "factors", "satellite", "research"})


if __name__ == "__main__":
    unittest.main()
