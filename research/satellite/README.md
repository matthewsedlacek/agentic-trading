# Satellite Scout

Year-over-year activity from dated satellite images of a company's own sites: store
parking lots, vehicle delivery lots, distribution centres. Idea from Angus Sewell's
"Satellite Spy Playbook" (Nov 2026); his guide and paid agent were not used here.

**Context only.** A Satellite Scout read never triggers a buy, never passes Stage 2 by
itself, and a name with no imagery is not penalised. See POLICY.md §4c.

## How to log an observation

Add one row per image to `observations.csv` (copy the header from
`observations.example.csv`):

| Column | What goes in it |
|---|---|
| `ticker` | The company the site belongs to |
| `site_id` | A stable id you choose per site, e.g. `wmt-golden-valley` |
| `site_name` | Plain description (optional) |
| `capture_date` | The date the image was **captured**, from the provider, `YYYY-MM-DD` |
| `provider` | Where the image came from; compare like with like |
| `image_id` | The provider's id for the image, so anyone can find it again |
| `metric` | What you counted: `cars`, `occupancy_pct`, `vehicles_staged` |
| `value` | The count or percentage you read off the image |
| `notes` | Weekday, local time, weather, anything odd (snow, construction) |

Rules: count only what you can see; skip cloudy or partial images; never estimate a
missing count. Log the same sites every time, and log a year-ago image for each site, or
the tool reports "no comparison". Three or more compared sites are needed for a read.

Then run, from the repo root:

```
python3 -m tools.satellite_scout --obs research/satellite/observations.csv --ticker TICKER
```

## Imagery sources (not checked live; verify before relying on one)

Car counting needs roughly 1 m resolution or better, and a useful signal needs images on
similar weekdays a year apart.

- **Google Earth Pro historical imagery**: free desktop app, high resolution, but dates
  are irregular and often a year or more apart. Good for a first look.
- **Copernicus Sentinel-2 (ESA)**: free, frequent, but 10 m pixels are too coarse to count
  cars; at best a full-versus-empty read on very large lots. Needs a free Copernicus
  account.
- **Commercial high-resolution imagery** (Planet, Maxar, Airbus, or marketplaces that
  resell them): the right resolution and dates, but paid, with an account.

No account was opened and nothing was bought for this feature. Picking a source, and any
sign-up or spend, is the operator's decision.
