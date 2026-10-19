# Data boundaries

The production pipeline downloads public sources into ignored `raw/`, `cache/`
and `processed/` directories. Run the data commands in the project README to
reconstruct these files. Third-party sources retain their original terms.

The small checked-in CSVs are legacy teaching inputs, **not the production
forecast or the source of its reported validation scores**:

- `demo_polls.csv` and `demo_fundamentals.csv` describe a fictional scenario.
- `historical_training.csv` is a small, manually assembled presidential teaching
  extract with rounded values and limited provenance. Use the auditable public
  archive adapters instead for research, training, or performance claims.

The checked-in website snapshot in `site/lib/forecast-data.json` contains model
outputs, compact public polling evidence and original-source links. It is not
a replacement for the complete source snapshots and integrity manifests retained
locally by the pipeline.
