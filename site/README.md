# Election Forecast Lab

Interactive publication layer for the U.S. election forecasting model in the
parent project. The checked-in snapshot covers the 2026 Senate, House, and
gubernatorial contests with race-level probabilities, recent poll evidence,
correlated chamber simulations, prediction-market context, validation metrics,
and provenance checks.

## Local development

```bash
npm install
npm run dev
```

Refresh `lib/forecast-data.json` from the parent project with:

```bash
python ../scripts/export_site_data.py
```

The site does not use a database. Every deployed version is an immutable model
snapshot and links poll rows back to their original published sources.

The parent GitHub repository includes this directory as ordinary source files,
not as an inaccessible nested submodule. The local directory also retains its
separate Sites publication repository; the two Git remotes serve different
purposes. Pushing GitHub source alone does not deploy the public website.
