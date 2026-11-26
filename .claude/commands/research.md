---
description: Read-only research pass on one ticker - Gate 0, screen metrics, regime, edge gate, factor evidence, Satellite Scout
argument-hint: TICKER
allowed-tools: Bash(python3 -m tools:*), Write(research/screen/**), mcp__Robinhood__get_equity_historicals, mcp__Robinhood__get_equity_fundamentals, mcp__Robinhood__get_equity_quotes
---

Research `$1` through the read-only parts of the funnel.

1. `python3 -m tools restricted $1`. If it is not clear, stop: report "FAIL at Gate 0".
2. Screen metrics: call `get_equity_fundamentals` and `get_equity_quotes` for `["$1"]`,
   save both to `research/screen/` (the harness file if it saved one, otherwise a verbatim
   copy of the raw JSON), and run
   `python3 -m tools screen --fundamentals <file> --quotes <file>`.
3. Call `get_equity_historicals` for `["$1", "SPY"]` in one call: `interval: "day"`,
   `start_time` five years before today, default split adjustment.
4. Run `python3 -m tools research --ticker $1 --bars <saved file>`. It prints the regime,
   factor evidence, Satellite Scout and edge gate lines from the SKILL.md output template.
5. Report in the SKILL.md output template, filling only what the tools and the connector
   gave you. Leave Thesis, Falsifier, Valuation, Risk/sizing and Entry/Exit plan as
   "not run (read-only research)" unless the operator asks for that Stage 2 work, and
   end with "Next action: none from this command". Never offer to simulate or place an order.

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
