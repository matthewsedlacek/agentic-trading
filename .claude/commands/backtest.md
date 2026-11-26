---
description: Read-only edge gate backtest for one ticker (Gate 0 + SKILL.md Stage 4b)
argument-hint: TICKER [stop] [target] [horizon-days]
allowed-tools: Bash(python3 -m tools:*), mcp__Robinhood__get_equity_historicals
---

Run the Stage 4b edge gate on `$1`. Optional exit plan: stop `$2` (default 0.08),
target `$3` (default 0.16), horizon `$4` trading days (default 126).

1. `python3 -m tools restricted $1`. If it is not clear, stop and report Gate 0.
2. Call `get_equity_historicals` for `["$1", "SPY"]` in one call: `interval: "day"`,
   `start_time` five years before today, default split adjustment.
3. Run `python3 -m tools gate --ticker $1 --bars <saved file> --spy <saved file>`, adding
   `--stop`, `--target` and `--horizon` only if they were given.
4. Report the edge gate line and every failure it lists. Say plainly that a FAIL means the
   funnel makes no buy proposal for this name.

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
