# Research tools

Plain Python 3 (standard library only, no installs). They read daily bars that a run
pulled from the Robinhood connector and saved to a file; they never fetch data, never
estimate a missing number, and never place, stage or change an order.

| Tool | Used in | What it answers |
|---|---|---|
| `edge_gate.py` | SKILL Stage 4b, POLICY §4b | Is the market calm enough, and did this exact exit plan make money on this name and beat SPY? |
| `factor_research.py` | SKILL "Factor research" | Which price signals actually predicted the next month's returns? |
| `satellite_scout.py` | SKILL Stage 2b | Are a company's lots busier than a year ago, per logged images? |

Run from the repo root with `python3 -m tools.<name> --help`. Tests:
`python3 -m unittest discover tests`.
