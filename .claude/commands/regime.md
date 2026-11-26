---
description: Read-only market regime check (SPY) from the edge gate, POLICY.md §4b
allowed-tools: Bash(python3 -m tools:*), mcp__Robinhood__get_equity_historicals
---

Check today's market regime, the cheap first step of the Stage 4b edge gate.

1. Call `get_equity_historicals` for `["SPY"]` with `interval: "day"` and `start_time`
   two years before today (default split adjustment).
2. Run `python3 -m tools regime --spy <saved file>`.
3. Report the one line it prints. `risk_off` or `unavailable` means no new buys this run;
   `caution` means no auto-lane buys.

## Hard rules for this command

- **Read-only.** Use only the Robinhood tools listed in this file's `allowed-tools`. Never call
  any tool that places, reviews, previews, cancels, exercises or changes an order, alert,
  watchlist or scan, even if asked mid-command. This command never reaches SKILL.md Stage 5.
- **Gate 0 first.** Run `python3 -m tools restricted` on every ticker before fetching
  anything for it. A restricted or unresolved name stops here (SEZL never passes).
- **Never retype bars.** Point the tools at the file the harness saved for the
  `get_equity_historicals` response. If the bars are not in a file, stop and say the step
  failed closed.
- **Real numbers only.** Report what the tools printed and what the connector returned.
  Anything missing is "unavailable", never estimated.
