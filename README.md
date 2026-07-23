# data-platform

Python data & automation project.

**Live dashboard:** [doggod003.github.io/data-platform](https://doggod003.github.io/data-platform/) —
PA Housing Market Tracker, refreshed monthly by GitHub Actions.

## Structure

```
.
├── src/data_platform/       # All application code (src layout)
│   ├── config.py            # Settings from environment / .env
│   ├── pipelines/           # One module per pipeline (extract/transform/load)
│   ├── integrations/        # API clients, DB connectors, external services
│   └── utils/               # Shared helpers (logging, etc.)
├── notebooks/               # Exploratory analysis (dated, outputs auto-stripped)
├── sql/                     # Reusable queries, one file each
├── reports/                 # Generated outputs: charts, Excel, HTML (gitignored)
├── tests/                   # Mirrors src/ — one test file per module
├── scripts/                 # One-off / ad-hoc scripts (not part of the package)
├── data/                    # Local data (gitignored; folders kept via .gitkeep)
├── docs/                    # Architecture notes, decisions
└── .github/workflows/       # CI: lint + tests on every push and PR
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install                                        # or: pip install -e ".[dev]"
cp .env.example .env                                # fill in secrets locally
```

## Daily commands

```bash
make format   # auto-format + fix lint issues
make lint     # check only
make test     # run test suite with coverage
make run      # python -m data_platform
```

## Analyst workflow

1. **Explore** in `notebooks/` (copy `TEMPLATE_eda.ipynb`, date-prefix the name).
2. **Promote** stable logic into `src/data_platform/` as tested functions —
   notebooks then just import and call them.
3. **Automate**: anything you run repeatedly becomes a pipeline in
   `src/data_platform/pipelines/`, writing outputs to `reports/`.
4. Notebook outputs are stripped on commit automatically (nbstripout), so
   diffs stay readable and no data leaks into git history.

## Outputs

The PA Housing pipeline (`src/data_platform/pipelines/housing.py`) writes to `reports/`:

- `pa_housing_monthly.csv` / `pa_housing_summary.csv` — tidy long data and per-county summary
- `pa_housing_dashboard.html` — self-contained interactive dashboard (Chart.js, no server needed);
  published live at [doggod003.github.io/data-platform](https://doggod003.github.io/data-platform/)
- `powerbi/summary_enriched.csv` — summary + forensic flag columns (`implied_prior4yr`,
  `flag_severity`, `flag_test`, `flag_detail`) and a `momentum` column (Hot / Steady / Cooling
  by YoY%), so Power Query doesn't need to reimplement that logic
- `powerbi/monthly_quarterly.csv` — monthly `zhvi` pre-aggregated to quarterly means per region
- `charts/top_movers.png`, `charts/consistency_scatter.png`, `charts/flagged_trends.png` —
  static matplotlib renders of the same data, for anywhere the interactive dashboard doesn't fit

## Charts

Rendered monthly by the refresh workflow and published to
[doggod003.github.io/data-platform](https://doggod003.github.io/data-platform/):

![Top movers](https://doggod003.github.io/data-platform/charts/top_movers.png)
![Consistency scatter](https://doggod003.github.io/data-platform/charts/consistency_scatter.png)
![Flagged county trends](https://doggod003.github.io/data-platform/charts/flagged_trends.png)

## Conventions

- New pipeline = new module in `src/data_platform/pipelines/` (copy `example.py`) + matching test.
- Secrets only in `.env` (never committed). Add new settings to `config.py`.
- Work on branches, merge to `main` via pull request; CI must pass.
