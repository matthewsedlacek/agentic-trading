---
description: Read-only monthly factor research on a universe of tickers (SKILL.md "Factor research")
argument-hint: TICKER TICKER ... (30 to 75 names)
allowed-tools: Bash(python3 -m tools:*), mcp__Robinhood__get_equity_historicals
---

Test which price factors predicted returns across this universe: $ARGUMENTS

1. `python3 -m tools restricted $ARGUMENTS` and drop every name that is not clear. If fewer
   than 30 clear names are left, say so and stop: the test needs at least 30.
2. Call `get_equity_historicals` for the clear names (75 per call at most): `interval: "day"`,
   `start_time` five years before today, default split adjustment.
3. Run `python3 -m tools factors --bars <saved file> --out research/factors/YYYY-MM-DD`
   with today's date.
4. Report each factor's verdict (supported, unproven, contrary) and the survivorship-bias
   caveat. Leave the report files uncommitted and ask the operator whether to commit them.

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
