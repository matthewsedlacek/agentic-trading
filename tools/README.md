# Research tools

Plain Python 3 (standard library only, no installs). They read daily bars that a run
pulled from the Robinhood connector and saved to a file; they never fetch data, never
estimate a missing number, and never place, stage or change an order.

| Tool | Used in | What it answers |
|---|---|---|
| `edge_gate.py` | SKILL Stage 4b, POLICY §4b | Is the market calm enough, and did this exact exit plan make money on this name and beat SPY? |
| `factor_research.py` | SKILL "Factor research" | Which price signals actually predicted the next month's returns? |
| `satellite_scout.py` | SKILL Stage 2b | Are a company's lots busier than a year ago, per logged images? |
| `restricted.py` | SKILL Gate 0, POLICY §0 | Is this ticker on the restricted list? Reads POLICY.md, fails closed. |
| `screen.py` | SKILL Stage 1, POLICY §4a | Which of these names clear the price, cap, volume, P/E and P/B gates? |

Run from the repo root with `python3 -m tools.<name> --help`. Tests:
`python3 -m unittest discover tests`.

## One command line: `python3 -m tools`

Every research step behind one entry point, so Claude Code can run them directly
with no MCP server in between:

```
python3 -m tools restricted TICKER ...                    # Gate 0
python3 -m tools screen --fundamentals F --quotes Q       # Stage 1 (§4a)
python3 -m tools regime --spy SPY.json                    # regime only, cheap first check
python3 -m tools gate --ticker T --bars B --spy S         # Gate 0, then Stage 4b
python3 -m tools factors --bars UNIVERSE.json --out research/factors/YYYY-MM-DD
python3 -m tools satellite --obs research/satellite/observations.csv --ticker T
python3 -m tools research --ticker T --bars B             # all of it for one name
```

`research` prints the Gate 0, regime, factor evidence, Satellite Scout and edge gate
lines of the SKILL.md output template. The `--bars` file can hold both the ticker and
SPY (one `get_equity_historicals` call), or pass SPY separately with `--spy`.

Exit codes: `0` clear / PASS / risk_on, `1` restricted / FAIL / not risk_on, `2` bad input.

## Claude Code commands (`.claude/commands/`)

Open the repo in Claude Code with the Robinhood connector attached, then:

| Command | Does |
|---|---|
| `/regime` | Pulls SPY bars and reports today's regime. |
| `/backtest TICKER [stop] [target] [horizon]` | Gate 0, then the Stage 4b edge gate. |
| `/screen TICKER ...` | Gate 0, then the §4a screen on fundamentals and quotes. |
| `/research TICKER` | Gate 0, screen metrics, regime, edge gate, factor evidence, Satellite Scout. |
| `/factor-research TICKER ...` | Monthly factor test on 30 to 75 names; leaves the report uncommitted. |

They are **read-only**. Each command's `allowed-tools` lists only `python3 -m tools`
and the connector's `get_` tools for historicals, fundamentals and quotes, and each
tells Claude never to call an order, alert, watchlist or scan tool. None of them reaches
SKILL.md Stage 5; buying still goes through the full funnel and its confirmations.
`tests/test_cli.py` fails if a command file ever allows another tool or if `tools/`
gains network or order code.

The `allowed-tools` names use the `mcp__Robinhood__` prefix that Claude Code gives a
connector named Robinhood. If yours is named differently, Claude Code asks before each
connector call instead of running it straight through.

Saved connector responses for `/screen` and `/research` go in `research/screen/`,
which git ignores.
