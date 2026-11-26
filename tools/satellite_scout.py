"""Satellite Scout: turn dated satellite-image observations into a year-over-year read.

You (or the operator) look at dated imagery of a company's physical sites,
such as store parking lots or a delivery lot, and log one row per image in a
CSV (see research/satellite/observations.example.csv). This tool compares
each site's latest count with the same site about a year earlier, from the
same imagery provider, and summarises the change per ticker.

It never looks at images, never fetches anything and never guesses a count:
a site with no matching year-ago image is reported as "no comparison".

Usage (from the repo root):
  python3 -m tools.satellite_scout --obs research/satellite/observations.csv [--ticker WMT] [--out ...json]
"""

import argparse
import csv
import json
import statistics
import sys
from datetime import date

REQUIRED = ("ticker", "site_id", "capture_date", "provider", "image_id", "metric", "value")
MATCH_WINDOW_DAYS = 21      # year-ago image must be within ±21 days of one year earlier
MIN_SITES = 3
FLAT_BAND = 0.05


def load_observations(path):
    rows, skipped = [], 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                if any(not (row.get(k) or "").strip() for k in REQUIRED):
                    raise ValueError
                rows.append({
                    "ticker": row["ticker"].strip().upper(),
                    "site": row["site_id"].strip(),
                    "date": date.fromisoformat(row["capture_date"].strip()[:10]),
                    "provider": row["provider"].strip(),
                    "image": row["image_id"].strip(),
                    "metric": row["metric"].strip(),
                    "value": float(row["value"]),
                })
            except ValueError:
                skipped += 1
    return rows, skipped


def site_changes(rows):
    """Latest vs year-ago value per (ticker, site, metric, provider)."""
    groups = {}
    for r in rows:
        groups.setdefault((r["ticker"], r["site"], r["metric"], r["provider"]), []).append(r)
    out = []
    for (ticker, site, metric, provider), obs in sorted(groups.items()):
        obs.sort(key=lambda r: r["date"])
        latest = obs[-1]
        try:
            anchor = latest["date"].replace(year=latest["date"].year - 1)
        except ValueError:  # Feb 29
            anchor = latest["date"].replace(year=latest["date"].year - 1, day=28)
        candidates = [r for r in obs[:-1] if abs((r["date"] - anchor).days) <= MATCH_WINDOW_DAYS]
        entry = {"ticker": ticker, "site": site, "metric": metric, "provider": provider,
                 "latest": {"date": latest["date"].isoformat(), "value": latest["value"], "image": latest["image"]}}
        if not candidates:
            entry["status"] = "no comparison"
        else:
            # closest date first; prefer the same weekday, since lots fill differently by day
            prior = min(candidates, key=lambda r: (r["date"].weekday() != latest["date"].weekday(),
                                                   abs((r["date"] - anchor).days)))
            entry["prior"] = {"date": prior["date"].isoformat(), "value": prior["value"], "image": prior["image"]}
            if prior["value"] <= 0:
                entry["status"] = "no comparison"
            else:
                entry["status"] = "compared"
                entry["yoy"] = round(latest["value"] / prior["value"] - 1, 4)
                entry["sameWeekday"] = prior["date"].weekday() == latest["date"].weekday()
        out.append(entry)
    return out


def summarise(changes, ticker=None):
    by_ticker = {}
    for c in changes:
        if ticker and c["ticker"] != ticker.upper():
            continue
        by_ticker.setdefault(c["ticker"], []).append(c)
    summary = {}
    for t, items in sorted(by_ticker.items()):
        compared = [c for c in items if c["status"] == "compared"]
        yoys = [c["yoy"] for c in compared]
        if len(compared) < MIN_SITES:
            read = "too thin"
        else:
            med = statistics.median(yoys)
            read = "up" if med > FLAT_BAND else "down" if med < -FLAT_BAND else "flat"
        summary[t] = {
            "read": read,
            "sitesCompared": len(compared),
            "sitesLogged": len({c["site"] for c in items}),
            "medianYoY": round(statistics.median(yoys), 4) if yoys else None,
            "sitesUp": sum(1 for y in yoys if y > 0),
            "sitesDown": sum(1 for y in yoys if y < 0),
            "latestImage": max(c["latest"]["date"] for c in items),
            "providers": sorted({c["provider"] for c in items}),
        }
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--obs", required=True)
    p.add_argument("--ticker")
    p.add_argument("--out")
    a = p.parse_args(argv)
    try:
        rows, skipped = load_observations(a.obs)
    except OSError as exc:
        print(f"Satellite Scout: bad input ({exc})", file=sys.stderr)
        return 2
    changes = site_changes(rows)
    summary = summarise(changes, a.ticker)
    result = {"summary": summary, "sites": [c for c in changes if not a.ticker or c["ticker"] == a.ticker.upper()],
              "rowsSkipped": skipped,
              "caveats": ["Context only, never a buy trigger.",
                          "Counts are only as good as the logged images; compare like with like (same provider, weekday, time of day)."]}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
    if not summary:
        print("Satellite Scout: no observations for that ticker")
    for t, s in summary.items():
        med = f"{s['medianYoY']:+.1%}" if s["medianYoY"] is not None else "n/a"
        print(f"Satellite Scout {t}: {s['read']} · median YoY {med} across "
              f"{s['sitesCompared']} of {s['sitesLogged']} sites · latest image {s['latestImage']}")
    if skipped:
        print(f"  ({skipped} incomplete rows skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
