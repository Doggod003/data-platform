# Notebooks

Exploratory work lives here. Rules of the woodwork:

1. Name: `YYYY-MM-DD_short-description.ipynb` (e.g. `2026-07-20_revenue-eda.ipynb`)
2. Notebooks are for exploring. Once logic stabilizes, promote it into
   `src/data_platform/` as a real function and import it back into the notebook.
3. Outputs are stripped automatically on commit (nbstripout) — notebooks stay
   diffable and the repo stays small.
