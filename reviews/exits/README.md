# Nightly exit review

One report per night: `<date>.md` (for the operator) and `<date>.json` (for later runs).
Rules and thresholds live in POLICY.md §4d.

## Runbook for the nightly run

Read-only. The run may call only the Robinhood connector's read tools listed below. It
never places, reviews, changes or cancels an order, and never calls an order tool.

1. Refresh `data/live.json` from `get_equity_positions` and `get_equity_quotes`
   (keep `generatedAt`, `avgBuyPrice`, `sessionClose`).
2. Save `get_equity_historicals` (interval `day`, about 1 year, split-adjusted) for SPY
   and for the holdings to two files in a scratch folder.
3. Run, from the repo root:

   ```
   python3 -m tools.exit_review --bars <holdings.json> --spy <SPY.json> --out reviews/exits
   ```

4. Commit the two report files on a branch and tell the operator how many positions need
   a yes. "Nothing needs you" is the normal result.

The operator approves exits in an interactive session, where the `trading-funnel` skill
simulates each sell and asks for a confirmation per order.
