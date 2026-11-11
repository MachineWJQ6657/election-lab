# Reproducing the 2026 results comparison

For the post-election summary and outlook (in Chinese), see [2026_retrospective.md](2026_retrospective.md). Chamber-level media tallies used by the review live in `config/results_2026_media_tallies.json`; `uv run python -m scripts.export_site_results` turns them and the delivered scores into `site/lib/results-data.json`.

The frozen baseline is `artifacts/final_2026_20261103T064943Z`. The scorer reads it without refitting or updating it, verifies all sealed input/output hashes, and records hashes of all 23 archive files before and after scoring. Results are written to a separate directory. Existing output directories are never overwritten.

Run from the repository root with the project environment:

```powershell
uv run python -m scripts.score_results_2026 --output artifacts/results_2026_replay
```

The retained November 11 snapshot is under `data/results/2026_20261111`; the delivered comparison is `artifacts/results_2026_20261111_final/report.md`. Replay is offline. The retrieved third-party page bytes (`raw/` directories) are kept locally and are not committed; the tracked manifests record each URL, retrieval time and SHA-256, so a replay on another machine first needs the same bytes (re-fetching produces a new snapshot, not the archived one). Its race scores, aggregate scores, observations, excluded matchups, authoritative source directory and manifest are derived from the same retained source bytes. Source timestamps are retrieval timestamps, not election dates or publication dates. Source update labels are retained separately when available. One AP chronology was retrieved through the public web tool: its manifest explicitly labels the retained text extraction, and the failed direct HTTP request remains recorded.

To collect a new snapshot from the configured public URLs:

```powershell
uv run python scripts/fetch_results_2026.py --output data/results/2026_new_snapshot
```

Then pass each desired manifest using repeated `--source-manifest PATH` arguments, an appropriate timezone-aware `--as-of`, and a fresh `--output`. A new snapshot does not automatically include the separately reviewed web extraction. Failed requests and pages serving a CAPTCHA are gaps, never results. Adapters reject the wrong election and unexpected contest counts. The current snapshot imports Texas and North Carolina returns and Minnesota Senate returns, AP Senate calls and selected AP/CBS/WRAL governor and House calls. It is partial national coverage.

`config/results_2026_reviewed_calls.json` records manually reviewed article assertions. These require the configured article bytes and evidence terms, and remain media calls. Review these assertions against any new article version before reuse. Missing calls do not mean the real-world race is necessarily undecided; they mean no usable outcome was imported. Winner-only calls identify only the frozen named-candidate event and are labeled accordingly. Candidate-name mismatches remain excluded for review rather than guessed aliases.

`race_scores.csv` retains the result status, outcome source URL/retrieval timestamp, and separate vote source URL/retrieval timestamp/status. Preliminary vote totals may accompany a called outcome; they never become certified. Unresolved or preliminary-only contests have no probability or margin score. Margins use all candidate votes, including third parties/write-ins. Rating priors, different matchups and RCV/runoff margins are excluded from margin scoring. The generic-ballot forecast needs complete compatible national House vote totals and currently stays unscored. The scorer uses the existing production central-matchup rule before attaching outcomes and logs both discarded alternative matchups.

For additional or certified observations, add an archived JSON payload containing a list of `ResultObservation` records and register it in a source manifest with `adapter: normalized`, its SHA-256, provider, source URL, retrieval timestamp, and `kind: official` or `media`. The record schema is in `election_forecast/results.py`. Certified records require an explicit winner, official source, certification document URL, timezone-aware certification timestamp no later than retrieval, and status evidence. Do not promote election-night returns, reporting percentages or projected winners to certification. Aggregate fusion-party candidate vote lines before import. Regular/special contests must match explicitly; Florida and Ohio Senate forecasts are special elections. A later unresolved record by the same provider retracts its earlier call; conflicting equal-status winners are unscored.

The 50-state authority directory is parsed from the [FEC state election office directory](https://www.fec.gov/introduction-campaign-finance/how-to-research-public-records/state-election-offices/). Each Senate, House and governor forecast links to the relevant state authority. Obtain the actual contest-specific canvass/certification document from that authority; the directory itself certifies nothing. The [EAC explanation of reporting and certification](https://www.eac.gov/election-officials/election-results-canvass-and-certification) distinguishes returns and calls from certified outcomes. The FEC compiles federal election results; gubernatorial results remain with state authorities. No chamber-control score is inferred from this partial import.

The résumé text in `docs/resume_election_pipeline.tex` uses the frozen poll table (1,567 deduplicated rows) and frozen model card (16 cycles, 1,343 races, 3,105 distinct held-out race/horizon snapshots). The best retrospective model has accuracy 0.8399356, MAE 4.7640181, and Brier 0.1053474. It was selected after comparing historical benchmarks; these are not 2026 results or an unbiased estimate of the complete production selection policy. The stricter nested model-selection overall row covers 577 races, with 83.71% accuracy, 4.8014-point MAE and Brier 0.11114. The frozen control artifact records 50,000 simulations. The old 659/188 and 1,342/3,097 counts refer to earlier snapshots.
