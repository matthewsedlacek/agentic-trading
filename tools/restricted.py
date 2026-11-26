"""Gate 0: is this ticker on the restricted list? Fails closed.

Reads the list straight from POLICY.md section 0 (the bullets that start with a
bold ticker, e.g. "- **SEZL — Sezzle Inc.**"), so the policy file stays the one
place the list lives. Anything that can't be resolved cleanly counts as
restricted: an unreadable POLICY.md, an empty list, or a ticker that doesn't
look like a plain US equity symbol.

Usage (from the repo root):
  python3 -m tools restricted TICKER [TICKER ...] [--policy POLICY.md]

Exit code 0 = every ticker is clear, 1 = at least one is restricted or
unresolved, 2 = bad input.
"""

import argparse
import os
import re
import sys

DEFAULT_POLICY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "POLICY.md")
_TICKER = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")
_BULLET = re.compile(r"^\s*-\s+\*\*([A-Z][A-Z.\-]{0,7})\b")


def load_restricted(policy_path=DEFAULT_POLICY):
    """Return the set of restricted tickers from POLICY.md section 0.

    Raises ValueError if the section or its list can't be found, so callers fail closed.
    """
    with open(policy_path, encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r"^## 0\..*?$(.*?)^(---|## )", text, flags=re.S | re.M)
    if not match:
        raise ValueError("POLICY.md has no section 0 restricted list")
    tickers = set()
    for line in match.group(1).splitlines():
        hit = _BULLET.match(line)
        if hit:
            tickers.add(hit.group(1))
    if not tickers:
        raise ValueError("restricted list in POLICY.md section 0 is empty or unreadable")
    return tickers


def check(ticker, restricted):
    """Return (status, reason). status is 'clear', 'restricted' or 'unresolved'."""
    sym = (ticker or "").strip().upper()
    if not _TICKER.match(sym):
        return "unresolved", f"'{ticker}' is not a clean ticker symbol; treated as restricted"
    # Options and share classes count too: SEZL, SEZL.B, SEZL-W all block.
    root = re.split(r"[.\-]", sym)[0]
    if sym in restricted or root in restricted:
        return "restricted", f"{sym} is on the restricted list (POLICY.md section 0)"
    return "clear", f"{sym} is not on the restricted list"


def gate0(tickers, policy_path=DEFAULT_POLICY):
    """Check several tickers. A policy that can't be read makes every ticker unresolved."""
    try:
        restricted = load_restricted(policy_path)
    except (OSError, ValueError) as exc:
        return {t.upper(): ("unresolved", f"cannot read restricted list ({exc}); failing closed") for t in tickers}
    return {t.strip().upper(): check(t, restricted) for t in tickers}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m tools restricted", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tickers", nargs="+")
    p.add_argument("--policy", default=DEFAULT_POLICY)
    a = p.parse_args(argv)
    results = gate0(a.tickers, a.policy)
    for sym, (status, reason) in results.items():
        print(f"Gate 0 {sym}: {status} · {reason}")
    return 0 if all(s == "clear" for s, _ in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
