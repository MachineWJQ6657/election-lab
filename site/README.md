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
or a count of races favored above 60%. Senate caucus proxies for unresolved
independent/multi-candidate contests remain explicit. Governor totals cover
only the 36 elections, not all 50 governorships. State/search filtering changes
the map's evidence selection, never these nationwide simulation totals.

Senate/governor colors represent candidate win probabilities. House state
colors represent expected Democratic seat share, not delegation-control odds;
individual district tiles use win probabilities. No-election states, independent
candidates, multi-candidate limitations and unpolled rating priors remain
explicit. These are mapped contests, not full chamber seat totals.

`lib/us-state-paths.json` contains locally bundled Albers USA SVG paths converted
from US Atlas 3.0.1 / Census 2017 state outlines. It is **not** a source of 2026
congressional district boundaries. Source URL and SHA-256 are retained, with the
ISC license in `public/us-atlas-LICENSE.txt`. Regenerate only when intentionally
updating geography with `node scripts/generate-state-map.mjs` (requires network).
The published page never requests third-party map tiles or a paid map API.

Run `npm test` for the build, server-rendered dashboard checks, probability-bin
boundaries, all 506 race-to-state joins, and geography integrity checks.

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
maps, duplicate state keys, cross-origin redirects and broken build assets.
It cannot repair account permissions or replace an interactive browser check.
