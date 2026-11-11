# Election Forecast Lab

Interactive publication layer for the U.S. election forecasting model in the
parent project. The 2026 midterms are over, so the page now opens with a
post-election review (frozen forecast vs. called results) and keeps the sealed
pre-election forecast below it, unchanged: race-level probabilities, poll
evidence, correlated chamber simulations, prediction-market context, validation
metrics and provenance checks.

## Local development

```bash
npm ci
npm run dev
```

Refresh the data files from the parent project root with:

```bash
uv run python scripts/export_site_data.py        # lib/forecast-data.json (sealed forecast)
uv run python -m scripts.export_site_results     # lib/results-data.json (post-election review)
```

The site does not use a database. Every deployed version is an immutable model
snapshot and links poll rows back to their original published sources.

## Post-election review

`components/ResultsReview.tsx` renders `lib/results-data.json`: chamber seat
results against the forecast median and 90% range, the national House vote,
race-level scores on called contests, every wrong call, races still counting,
and the main lessons. Chamber tallies are media projections compiled on
2026-11-11, not certified results; race-level scores come from the parent
project's results scorer. The review never edits `lib/forecast-data.json`, and
the tests check that its forecast numbers match the sealed snapshot.

The sealed pre-result snapshot is locked at **2026-11-03 01:49:43 EST**. No
election-night results were inputs. Any input/output change invalidates the
exported final-release badge until explicitly resealed.

Publication status (2026-11-11): the public domain still serves v11
(2026-10-20, Oct 19 model data). Sites returned `project_not_found` on Nov 3, so
the sealed forecast was never deployed. The post-election build passes all tests
and is committed to the local Sites repository, ready to deploy.

The parent GitHub repository includes this directory as ordinary source files,
not as an inaccessible nested submodule. The local directory also retains its
separate Sites publication repository; the two Git remotes serve different
purposes. Pushing GitHub source alone does not deploy the public website.

## Interactive election map

The race explorer includes a state SVG map for Senate and governor forecasts,
and a House delegation map that drills down into each state's district tiles.
Map selection, search, the race table and evidence inspector share selection
state. Small screens default to alphabetical state tiles; the geographic view
remains available. The map reads the existing forecast snapshot and never
changes its probabilities.

Above the map, a final-seat comparison uses the existing simulation median:
Democratic versus Republican seats across all 435 House or 100 Senate seats.
The Senate includes its 65 non-election seats (34 D-aligned, 31 R-aligned in
this snapshot); it does not mistake 35 contests for the whole chamber. The
comparison also shows simulation means, complementary 90% ranges and model
control probabilities, with a threshold marker. It is not an election result
or a count of races favored above 50%. Senate caucus proxies for unresolved
independent/multi-candidate contests remain explicit. Governor totals cover
only the 36 elections, not all 50 governorships. State/search filtering changes
the map's evidence selection, never these nationwide simulation totals.

Senate/governor colors represent candidate win probabilities. House state
colors represent expected Democratic seat share, not delegation-control odds;
individual district tiles use win probabilities. No-election states, independent
candidates, multi-candidate limitations and unpolled rating priors remain
explicit. These are mapped contests, not full chamber seat totals.

The model's own win-probability ratings are **Solid** (also called Safe, ≥95%),
**Likely** (80–<95%), **Lean** (60–<80%), **Tilt** (>50–<60%), and **Toss-up**
(exactly 50/50). Thresholds refer to the favored candidate's unrounded probability,
not a vote margin or an imported expert rating; a displayed 50.0% can still be Tilt.
These presentation categories do not change model probabilities. A tiny numerical
normalization at cutoffs ensures complementary probabilities receive symmetric
ratings. Solid does not mean certain. Geographic states show only abbreviations;
ratings appear in hover/accessibility labels, the compact legend, the segmented
seat bar, district tiles and the selected-race panel. Independent candidates
retain their own party label and purple color. House state colors use expected
D seat share, with a separate share key, never a race-win rating.

The segmented bar counts ratings and includes explicit hatched Senate holdovers.
Its totals are distinct from the large simulation medians: unmodeled contests
are not silently assigned a winner. Legend chips show category counts, while
thresholds and uncertainty notes are in a collapsed details disclosure. The
selected-state strip is below the map, with deeper evidence folded by default.

`lib/us-state-paths.json` contains locally bundled Albers USA SVG paths converted
from US Atlas 3.0.1 / Census 2017 state outlines. It is **not** a source of 2026
congressional district boundaries. Source URL and SHA-256 are retained, with the
ISC license in `public/us-atlas-LICENSE.txt`. Regenerate only when intentionally
updating geography with `node scripts/generate-state-map.mjs` (requires network).
The published page never requests third-party map tiles or a paid map API.

Run `npm test` for the build, server-rendered dashboard checks, probability-bin
boundaries, all 506 race-to-state joins, and geography integrity checks.

## Experimental early-vote scenarios

The observed-participation section has a collapsed scenario lab for compatible
statewide Senate/governor contests. Its inputs are reported ballots, assumed
final two-side turnout, included-ballot exposure, and assumed early/remaining
Democratic vote shares. The early weight is included ballots / assumed turnout;
the total share is a weighted average of the two explicit preference assumptions.
The calculator displays conditional margin, remaining share needed for 50%,
and sensitivity. It does not estimate winner probabilities or change the map,
official race odds, chamber simulations, or the formal early-vote weight of 0%.

The turnout scale is sourced 2024 Democratic + Republican presidential votes.
Its default 75% factor is illustrative, not estimated. Shares start at the
selected race's model-margin baseline, not party registration or demographic
inference. Third-party votes and rejection rates are not estimated. Impossible
turnout assumptions produce an alert, not silent ballot clipping. Switching
states resets assumptions. Unit tests cover weight, endpoints, bounds,
zero exposure, and analytical sensitivity; browser QA checks real controls.

## Publication recovery and verification

The original project identity is retained in `.openai/hosting.json`. Check that
project with Sites before publishing, confirm the returned role/audience and
original domain, then request a fresh repository credential. Pass credentials
through the official workflow helper's hidden stdin; never commit them or place
them in command arguments. Save the exact pushed source/archive pair and deploy
that saved version, preserving the public audience and custom domain.

`project_not_found` at project lookup does not demonstrate a build failure or
prove that the site was deleted. Project lookup has failed intermittently while
other attempts could access the same identity. Recheck after restoring the intended
account/workspace connection. Do not replace the project ID, create a duplicate,
change DNS, or reuse an expired credential as a workaround. The connector does
not expose enough evidence to establish the underlying account/backend cause.

After a successful native deployment, run `npm run verify:publication`. This
read-only command checks the existing public HTTPS domain, exact snapshot ID,
all 51 initial state shapes, and the availability/content types of every
referenced JavaScript and stylesheet asset. It fails on stale snapshots, missing
maps, missing named-rating scale, duplicate state keys, cross-origin redirects and broken build assets.
It cannot repair account permissions or replace an interactive browser check.
