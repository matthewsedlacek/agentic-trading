"""Tests for the research tools. Run from the repo root: python3 -m unittest discover tests"""

import csv
import json
import math
import os
import random
import tempfile
import unittest
from datetime import date, timedelta

from tools import edge_gate, factor_research, satellite_scout
from tools.bars import Bar, bars_from_data


def make_bars(closes, start=date(2021, 1, 4), wiggle=0.0):
    out, d = [], start
    for k, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        prev = closes[k - 1] if k else c
        out.append(Bar(d.isoformat(), prev, max(prev, c) * (1 + wiggle), min(prev, c) * (1 - wiggle), c))
        d += timedelta(days=1)
    return out


def trend(n, daily, start=100.0, noise=0.0, seed=1):
    rng = random.Random(seed)
    c, out = start, []
    for _ in range(n):
        c *= 1 + daily + rng.gauss(0, noise)
        out.append(c)
    return out


class BarsTests(unittest.TestCase):
    def test_robinhood_shape_and_interpolated_dropped(self):
        data = {"results": [{"symbol": "abc", "historicals": [
            {"begins_at": "2026-01-02T00:00:00Z", "open_price": "1", "high_price": "2",
             "low_price": "0.5", "close_price": "1.5"},
            {"begins_at": "2026-01-03T00:00:00Z", "open_price": "1", "high_price": "2",
             "low_price": "0.5", "close_price": "1.5", "interpolated": True},
            {"begins_at": "2026-01-05T00:00:00Z", "open_price": None, "high_price": "2",
             "low_price": "0.5", "close_price": "1.5"},
        ]}]}
        bars = bars_from_data(data)
        self.assertEqual(list(bars), ["ABC"])
        self.assertEqual([b.date for b in bars["ABC"]], ["2026-01-02"])

    def test_current_connector_shape(self):
        # Trimmed copy of a real get_equity_historicals response (SPY, Nov 2026).
        data = {"data": {"results": [{"symbol": "SPY", "interval": "day", "bounds": "regular", "bars": [
            {"begins_at": "2026-11-16T00:00:00Z", "open_price": "749.660000", "close_price": "739.950000",
             "high_price": "749.820000", "low_price": "738.070000", "volume": 69207282, "session": "reg"},
            {"begins_at": "2026-11-17T00:00:00Z", "open_price": "738.390000", "close_price": "732.440000",
             "high_price": "739.760000", "low_price": "727.000000", "volume": 71636294, "session": "reg"},
        ]}]}, "guide": "..."}
        bars = bars_from_data(data)["SPY"]
        self.assertEqual([b.date for b in bars], ["2026-11-16", "2026-11-17"])
        self.assertAlmostEqual(bars[1].low, 727.0)

    def test_symbol_map_shape(self):
        data = {"X": [{"date": "2026-01-02", "open": 1, "high": 1, "low": 1, "close": 1}]}
        self.assertEqual(len(bars_from_data(data)["X"]), 1)


class EdgeGateTests(unittest.TestCase):
    def test_regime_states(self):
        up = make_bars(trend(300, 0.001))
        self.assertEqual(edge_gate.market_regime(up)["state"], "risk_on")
        down = make_bars(trend(300, -0.002))
        self.assertEqual(edge_gate.market_regime(down)["state"], "risk_off")
        self.assertEqual(edge_gate.market_regime(up[:100])["state"], "unavailable")

    def test_stop_checked_before_target_same_day(self):
        bars = [Bar("2026-01-01", 100, 100, 100, 100), Bar("2026-01-02", 100, 120, 90, 100)]
        _, ret, how = edge_gate.simulate_trade(bars, 0, 0.08, 0.16, 10)
        self.assertEqual(how, "stop")
        self.assertAlmostEqual(ret, -0.08)

    def test_gap_down_fills_at_open(self):
        bars = [Bar("2026-01-01", 100, 100, 100, 100), Bar("2026-01-02", 85, 86, 84, 85)]
        _, ret, how = edge_gate.simulate_trade(bars, 0, 0.08, 0.16, 10)
        self.assertEqual(how, "stop_gap")
        self.assertAlmostEqual(ret, -0.15)

    def test_strong_name_in_calm_market_passes(self):
        spy = make_bars(trend(900, 0.0003, noise=0.004))
        name = make_bars(trend(900, 0.0015, noise=0.006, seed=2))
        result = edge_gate.run_gate("AAA", name, spy)
        self.assertEqual(result["verdict"], "PASS", result["failures"])
        self.assertTrue(result["autoLaneAllowed"])

    def test_laggard_fails_against_spy(self):
        spy = make_bars(trend(900, 0.0012, noise=0.004))
        name = make_bars(trend(900, -0.0005, noise=0.01, seed=3))
        result = edge_gate.run_gate("BBB", name, spy)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertFalse(result["autoLaneAllowed"])

    def test_short_history_fails_closed(self):
        spy = make_bars(trend(300, 0.0005))
        name = make_bars(trend(200, 0.002))
        result = edge_gate.run_gate("CCC", name, spy)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("not enough history" in f for f in result["failures"]))

    def test_risk_off_blocks_even_a_good_backtest(self):
        spy = make_bars(trend(600, 0.001) + trend(300, -0.003, start=trend(600, 0.001)[-1]))
        name = make_bars(trend(900, 0.002, noise=0.005, seed=4))
        result = edge_gate.run_gate("DDD", name, spy)
        self.assertEqual(result["regime"]["state"], "risk_off")
        self.assertEqual(result["verdict"], "FAIL")

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            def dump(name, bars):
                p = os.path.join(d, name)
                with open(p, "w") as fh:
                    json.dump([b.__dict__ for b in bars], fh)
                return p
            spy = dump("spy.json", make_bars(trend(900, 0.0003, noise=0.004)))
            good = dump("a.json", make_bars(trend(900, 0.0015, noise=0.006, seed=2)))
            out = os.path.join(d, "out.json")
            self.assertEqual(edge_gate.main(["--ticker", "AAA", "--bars", good, "--spy", spy, "--out", out]), 0)
            with open(out) as fh:
                self.assertEqual(json.load(fh)["verdict"], "PASS")
            self.assertEqual(edge_gate.main(["--ticker", "AAA", "--bars", os.path.join(d, "missing.json"),
                                             "--spy", spy]), 2)


class FactorResearchTests(unittest.TestCase):
    def test_spearman_with_ties(self):
        self.assertAlmostEqual(factor_research.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(factor_research.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertEqual(factor_research.ranks([5, 1, 5]), [2.5, 1.0, 2.5])

    def test_persistent_trends_make_momentum_supported(self):
        # Each name keeps its own drift for the whole history, so past winners keep winning.
        universe = {f"S{k}": make_bars(trend(1000, (k - 10) * 0.0002, noise=0.003, seed=k))
                    for k in range(20)}
        report = factor_research.research(universe)
        mom = report["factors"]["mom_12_1"]
        self.assertEqual(mom["verdict"], "supported", mom)
        self.assertGreater(mom["topMinusBottom21d"], 0)

    def test_pure_noise_is_not_supported(self):
        universe = {f"N{k}": make_bars(trend(1000, 0.0, noise=0.01, seed=100 + k)) for k in range(20)}
        report = factor_research.research(universe)
        for name, f in report["factors"].items():
            self.assertNotEqual(f["verdict"], "supported", (name, f))

    def test_thin_universe_tests_nothing(self):
        universe = {f"T{k}": make_bars(trend(1000, 0.001, seed=k)) for k in range(5)}
        self.assertEqual(factor_research.research(universe)["factors"], {})

    def test_extra_point_in_time_factor(self):
        universe = {f"S{k}": make_bars(trend(800, (k - 10) * 0.0002, noise=0.003, seed=k)) for k in range(20)}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pit.csv")
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["date", "symbol", "factor", "value"])
                for sym, bars in universe.items():
                    for b in bars:
                        w.writerow([b.date, sym, "drift_label", int(sym[1:])])
            report = factor_research.research(universe, factor_research.load_extra(path))
        self.assertIn("drift_label", report["factors"])
        self.assertEqual(report["factors"]["drift_label"]["verdict"], "supported")


class SatelliteScoutTests(unittest.TestCase):
    def write(self, rows):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
        w = csv.DictWriter(fh, fieldnames=["ticker", "site_id", "site_name", "capture_date", "provider",
                                           "image_id", "metric", "value", "notes"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def row(self, site, day, value, provider="p1", ticker="WMT"):
        return {"ticker": ticker, "site_id": site, "site_name": "", "capture_date": day, "provider": provider,
                "image_id": f"{site}-{day}", "metric": "cars", "value": value, "notes": ""}

    def test_yoy_up_across_three_sites(self):
        rows = []
        for k, (a, b) in enumerate([(100, 120), (80, 92), (50, 55)]):
            rows += [self.row(f"s{k}", "2025-11-22", a), self.row(f"s{k}", "2026-11-21", b)]
        obs, skipped = satellite_scout.load_observations(self.write(rows))
        summary = satellite_scout.summarise(satellite_scout.site_changes(obs))
        self.assertEqual(skipped, 0)
        self.assertEqual(summary["WMT"]["read"], "up")
        self.assertEqual(summary["WMT"]["sitesCompared"], 3)

    def test_other_provider_or_far_date_is_not_compared(self):
        rows = [self.row("s0", "2025-11-22", 100, provider="p2"), self.row("s0", "2026-11-21", 150),
                self.row("s1", "2025-08-01", 100), self.row("s1", "2026-11-21", 150)]
        obs, _ = satellite_scout.load_observations(self.write(rows))
        changes = satellite_scout.site_changes(obs)
        self.assertTrue(all(c["status"] == "no comparison" for c in changes if c["provider"] == "p1"))
        self.assertEqual(satellite_scout.summarise(changes)["WMT"]["read"], "too thin")

    def test_incomplete_rows_skipped(self):
        rows = [self.row("s0", "2026-11-21", 10), {**self.row("s1", "2026-11-21", 10), "image_id": ""}]
        obs, skipped = satellite_scout.load_observations(self.write(rows))
        self.assertEqual((len(obs), skipped), (1, 1))


if __name__ == "__main__":
    unittest.main()
