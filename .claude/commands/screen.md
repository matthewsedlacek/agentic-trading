---
description: Read-only Stage 1 screen of named tickers against POLICY.md §4a
argument-hint: TICKER [TICKER ...] (up to 20)
allowed-tools: Bash(python3 -m tools:*), Write(research/screen/**), mcp__Robinhood__get_equity_fundamentals, mcp__Robinhood__get_equity_quotes
---

Screen these tickers against the §4a gates: $ARGUMENTS

1. `python3 -m tools restricted $ARGUMENTS`. Drop every name that is not clear, and do not
   fetch anything for it. Report only how many were excluded, not which.
2. Call `get_equity_fundamentals` and `get_equity_quotes` for the clear names (20 per call
   at most).
3. Save each response to `research/screen/` exactly as the connector returned it. If the
   harness already saved it to a file, use that path. If you copy a short response into a
   file, copy the raw JSON verbatim and change nothing.
4. Run `python3 -m tools screen --fundamentals <file> --quotes <file>`.
5. Check two or three printed figures against the connector response, then report the
   shortlist with its metrics and the dropped names with their reasons. A shortlist is
   never a buy: survivors still go through Stage 2 onward.

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
