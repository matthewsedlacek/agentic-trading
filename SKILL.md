---
name: trading-funnel
description: Run the disciplined equity research-and-execution funnel against the connected Robinhood MCP, optionally seeded by congressional/government trade disclosures via the FMP connector. Use this whenever the operator wants to find buy candidates, research a specific ticker, review congressional/government trades as candidate ideas, build a buy thesis with an exit plan, size a position, or stage/place a real trade — even if they don't say "run the funnel." Also use whenever a trade or order is about to be placed, to enforce the restricted-list check, data-grounding, simulation-first, and human confirmation. Trigger on phrases like "research TICKER", "find me something to buy", "screen for", "what did congress buy", "government trades", "should I buy", "place the order", "set my stop".
---

# Trading Funnel

A staged procedure for turning a research idea into a confirmed, risk-bounded trade
through the Robinhood connector. Every stage gates the next: a name advances only if it
clears the one before. Nothing reaches an order without real data, a predefined exit,
and explicit human confirmation.

**Operating policy lives in `POLICY.md`** alongside this file (restricted list, the
$25/$50 spend caps, data-grounding, risk guardrails). Treat POLICY.md as binding for
every run; this skill is the procedure, POLICY.md is the law.

## Precondition — market must be open (autonomous runs, check FIRST)

Before anything else in an autonomous run, confirm the U.S. regular trading session is
actually open right now. Verify it against the connector — check session/tradability
status or that live quotes are updating — rather than trusting the clock alone.

If the session is not open (weekend, holiday, early close, pre/post-market, or any
schedule drift), exit immediately with no action and no trade. This connector-based check
is what catches market holidays and half-days that a fixed schedule cannot know about.
When in doubt about whether the session is open, treat it as closed and exit.

## Gate 0 — Restricted-list check (run this FIRST, every time)

Before screening, researching, simulating, or placing anything, resolve the ticker and
check it against the restricted list in the project instructions (currently **SEZL /
Sezzle Inc.**).

- If the name is restricted: stop. Do not analyze it as a trade target, do not screen it
  in, do not stage an order. State plainly that it's on the restricted list and why.
- If you cannot cleanly resolve the ticker, or cannot confirm restricted status: treat it
  as restricted and stop. Fail closed.
- A restricted name may still be *read* as an existing holding for portfolio context
  (correlation, concentration) — never as something to buy or sell.

This gate exists because the restricted name is an employer/insider exposure, and a
single careless order is a real compliance problem. It is cheaper to over-block than to
slip one through.

## The data-grounding rule (applies at every stage)

Pull every number from the live Robinhood feed or a real cited source. If a figure isn't
available, write "unavailable" — never estimate it into existence. Be especially wary of
asks that LLMs fabricate convincingly: insider filings, short interest, options flow,
analyst targets, "safety scores." Persona framing changes tone only, never grants data.

---

## Stage 1 — Screen (build the candidate universe)

Goal: a shortlist, not a buy.

1. Confirm the operator's quantitative gates (or use the ones saved in the project):
   valuation band, revenue-growth floor, leverage ceiling, sector preferences, etc.
2. Run a Robinhood scanner and/or pull fundamentals to assemble candidates that meet
   the gates. Exclude every restricted name at this step so it never surfaces.
3. Return a ranked shortlist with the real metrics that earned each name its place.

Analytical lens (optional, for framing only): a Goldman-style screening report. The
*format* is fine; the *numbers* must be real.

### Stage 1b — Congressional disclosures as a candidate source (FMP)

Congressional trades are an *additional way to surface candidates* — never a buy trigger.
A disclosed name enters the shortlist and then clears the SAME funnel as any other name.

Pull via the FMP `senate` tool: `house-latest` and `senate-latest` for new disclosures,
or `house-trading` / `senate-trading` (by symbol) and `*-trading-by-name` to investigate
a specific ticker or member. Fields returned: `symbol`, `transactionDate`,
`disclosureDate`, member name/office/district, `owner` (self/spouse), `type`
(Purchase/Sale), and `amount` (a range bucket, not an exact figure).

Filtering rules:
- **Purchases only.** Buys are the signal; sales are noisy (taxes, rebalancing, etc.).
- **Stock only** (`assetType` = Stock).
- **Compute the lag** = disclosureDate − transactionDate and surface it on every
  candidate. The edge was exercised at the transaction, not the disclosure, so a stale
  trade carries little signal. Treat anything older than ~45 days as low-value context,
  not a fresh idea.
- **Run Gate 0.** SEZL (and any restricted name) never passes, even if disclosed.
- **Dedupe** against disclosures already seen (key on symbol + transactionDate + filing
  link) so the same trade doesn't re-surface every run.

Important framing: the `amount` field is a range, so you cannot derive exact sizing from
it — and it's irrelevant to your sizing anyway, because your own $25/$50 caps govern what
gets bought, independent of the member's trade size. The more durable signal in the
research is committee-aligned trading (a member buying in a sector their committee
oversees); FMP doesn't return committee data, so treat that as optional manual enrichment
rather than something the run infers.


## Stage 2 — Validate (the actual research)

For shortlisted names only, go deep. Useful lenses, stripped of fabrication traps:

- **Valuation (Morgan Stanley DCF lens):** project from real historicals, compute a
  range, compare to current price. The math is legitimate because the inputs are real.
- **Competitive position (Bain lens):** moat, market share trend, key threats — from
  real filings/data where available, marked unavailable otherwise.
- **Earnings setup (JPMorgan lens):** real beat/miss history and upcoming date from the
  feed; flag anything you can't source.

**Required output — the thesis and its falsifier:**

> "I own this because **[X]**. I am wrong if **[Y]** happens."

If you cannot write a concrete falsifier, the name does not pass. The falsifier becomes
the thesis-break sell condition in Stage 4.

## Stage 3 — Size (fit it to the portfolio)

1. Pull current positions and portfolio value from the connector.
2. Assess correlation/overlap with existing holdings and resulting sector concentration.
3. Propose a position size within the project's risk guardrails (max position %, max
   deployment per cycle).
4. State the maximum dollar loss accepted on this position at the planned stop.

If the proposed size breaches a guardrail, stop and flag it.

## Stage 4 — Define the exit (before any buy)

Specify all four, in writing, now:

- **Target** (from the Stage 2 valuation range).
- **Stop level** (price or thesis-based).
- **Time horizon.**
- **Thesis-break condition** (the Stage 2 falsifier).

Exits must run broker-side because you only run when messaged and cannot watch the
position intraday. Plan to place protective orders at entry so they execute without you.
Confirm which order types the connector actually supports before relying on one.

## Stage 5 — Execute (lane-gated)

Determine the lane first: **autonomous** (a scheduled/hourly run, no human present) or
**interactive** (operator is in the conversation).

### Compute today's auto-spend (autonomous runs)

Pull the account's filled buy orders for the current day via the connector and sum their
notional. This is the source of truth for the daily cap — never a tally carried in the
prompt. If you cannot retrieve it, fail closed: do not auto-execute; escalate instead.

### Auto lane — may place without asking

A buy executes automatically ONLY if BOTH:
- order notional **≤ $25**, AND
- today's summed buys **< $50** before this order.

Sequence: re-run Gate 0 → review/simulate the order → place it → immediately stage the
Stage 4 protective exit orders (stop + target) → log it (ticker, size, thesis, exits,
order IDs) for the operator to review later.

### Escalation lane — must NOT place autonomously

If the order breaches either cap, do not place it. Then:

1. **Write the proposal file.** Save a complete proposal to `proposals/YYYY-MM-DD-TICKER.md`
   covering: ticker, size, thesis, falsifier, full entry/exit plan, and which cap or
   guardrail it exceeded. Use real data only; no fabricated numbers.

2. **Commit the proposal.** Stage and commit the file to the current branch with a message
   like `Log TICKER trade proposal for manual review (YYYY-MM-DD run)`.

3. **Open a GitHub pull request.** Push the branch and create a PR using the `gh` CLI
   (pre-authenticated in the cloud environment):

   ```
   gh pr create \
     --title "Proposal: TICKER — one-line thesis (<date>)" \
     --body "## Summary
   - **Ticker:** TICKER
   - **Proposed size:** $X
   - **Why escalated:** <cap or guardrail breached>

   ## Thesis
   <one-liner>

   ## Falsifier
   <falsifier>

   ## Entry / Exit plan
   - Entry: ...
   - Stop: ...
   - Target: ...
   - Horizon: ...

   Full details in \`proposals/YYYY-MM-DD-TICKER.md\`." \
     --base main
   ```

   If `gh pr create` fails (e.g. PR already exists for this branch), log the error and
   continue — do not abort the run. The proposal file is the source of truth; the PR is
   the notification channel.

4. The PR waits for interactive approval. A routine never places an above-cap order;
   the operator approves it in an interactive session where simulation + confirmation apply.

### Interactive lane

Simulate, show cost/fees/resulting position, obtain explicit confirmation, place, then
stage exits. One confirmation = one order. Above-cap trades the routine queued earlier
are approved here.

### Always, every lane

- Gate 0 runs on the exact ticker immediately before placing. SEZL never trades.
- Every entry gets broker-side protective exit orders so they run without a session.
- Confirm the connector's supported order types before relying on a stop/target type.

---

## Exit management — what triggers a sell

There are three exit triggers, and they are NOT handled the same way.

**1. Stop hit → automatic (broker-side).** At entry, place a resting stop order. The
broker fills it when price reaches the stop. No routine or session required.

**2. Target hit → automatic (broker-side).** At entry, place a resting target/limit
order. The broker fills it when price reaches the target.

Stop and target should be linked as a bracket / OCO (one-cancels-other) so filling one
cancels the other. Confirm whether the connector supports OCO. If it does not, the hourly
run must reconcile manually (see below).

**3. Thesis-break or time-horizon → ALERT, do not auto-sell.** These are judgment calls,
and force-selling on a misread thesis is its own risk. Each hourly run reviews open
positions and, if a position's falsifier (from Stage 2) appears met or its horizon has
passed, it flags the position to the operator with the evidence — it does not liquidate
autonomously. The operator decides in an interactive session.

**Spend caps do not apply to exits.** The $25/$50 caps govern capital deployment (buys).
A protective or risk-reducing sell executes at whatever size the position requires — never
hold a loss-cutting sell because of a buy budget.

**Orphaned-order reconciliation (every hourly run).** Check open protective orders against
current positions. If a position was closed (stop or target filled) but its sibling order
is still resting, cancel the orphan. This prevents a stale order from firing against shares
you no longer hold.

---

## Output template

Use this structure when presenting a researched candidate:

```
TICKER — [company]                      [PASS / FAIL at stage N]
Restricted check: clear

Thesis:    I own this because [X].
Falsifier: I am wrong if [Y].

Screen metrics:   [real figures, sourced]
Valuation:        [DCF range] vs [current price] → [under/fair/over]
Risk/sizing:      [size], [correlation note], max loss at stop: [$]

Entry plan:       buy [qty] near [price]
Exit plan:        target [price] · stop [price] · horizon [t] · break: [Y]

Next action:      simulate order for confirmation? (y/n)
```

## Things to refuse or halt on

- Any trade in a restricted name (SEZL).
- Auto-executing a **buy** above $25, or once the day's buys reach $50 — escalate instead.
  (Spend caps govern BUYS only. Risk-reducing exits are never blocked by them — see below.)
- Auto-executing when today's spend can't be read or a price can't be resolved (fail closed).
- Placing any order without a prior review/simulation.
- Acting on any number you couldn't source from real data.
- A buy with no defined exit.
- Manufacturing a trade just because a scheduled run fired. "No action" is valid output.
