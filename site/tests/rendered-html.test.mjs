import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

function contains(text, pattern) {
  assert.ok(pattern.test(text), `Rendered HTML is missing ${pattern}`);
}

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("https://forecast.example/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the forecast dashboard and social metadata", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  contains(html, /Election Forecast Lab/);
  contains(html, /House leans Democratic/);
  contains(html, /Balance of power/);
  contains(html, /RACE EXPLORER/);
  contains(html, /id="election-map"/);
  contains(html, /Senate(?:<!-- -->)? election map/);
  contains(html, /not simulation totals/);
  contains(html, /no 2026 district-boundary claim/);
  contains(html, /Jump to state/);
  assert.equal((html.match(/data-state="[A-Z]{2}"/g) ?? []).length, 51);
  assert.match(html, /data-state="MT" data-map-band="unmodeled"/);
  assert.match(html, /data-state="CA" data-map-band="no-election"/);
  contains(html, /data-map-rating-scale="solid-likely-lean-tilt"/);
  contains(html, /data-state="TX" data-map-band="lean-d"/);
  contains(html, /data-state="ME" data-map-band="tilt-d"/);
  assert.ok(!html.includes('class="map-rating-label'));
  assert.equal((html.match(/class="map-label(?: light)?"/g) ?? []).length,51);
  for (const rating of ["Solid D","Likely D","Lean D","Tilt D","Toss-up","Tilt R","Lean R","Likely R","Solid R"]) contains(html,new RegExp(`title="${rating}:`));
  contains(html, /data-race-rating="Lean D"/);
  contains(html, /Solid is not a guarantee/);
  contains(html, /<details class="map-forecast-details">/);
  contains(html, /<details class="map-footnote">/);
  const seatSegments=[...html.matchAll(/data-seat-band="([a-z-]+)" data-seat-count="(\d+)"/g)];
  assert.equal(seatSegments.reduce((sum,m)=>sum+Number(m[2]),0),100);
  assert.equal(seatSegments.find((m)=>m[1]==="holdover-d")?.[2],"34");
  assert.equal(seatSegments.find((m)=>m[1]==="holdover-r")?.[2],"31");
  // A single text child avoids SSR separator comments inside SVG title text.
  const svgTitle = html.match(/<svg[^>]*class="us-election-map"[\s\S]*?<title>([\s\S]*?)<\/title>/);
  assert.equal(svgTitle?.[1], "2026 Senate forecast map");
  contains(html, /Uncertainty/);
  contains(html, /OBSERVED PARTICIPATION/);
  contains(html, /not votes for a candidate/);
  const data = JSON.parse(await readFile(new URL("../lib/forecast-data.json", import.meta.url), "utf8"));
  contains(html, /Projected final Senate seats/);
  contains(html, new RegExp(`data-seat-summary="senate" data-total-seats="100" data-dem-seats="${data.control.senate.median_dem_seats}" data-rep-seats="${100-data.control.senate.median_dem_seats}"`));
  contains(html, /PROJECTED FINAL SENATE SEATS/);
  contains(html, /Expected seats/);
  contains(html, /Model control odds/);
  contains(html, /seats not up/);
  contains(html, new RegExp(`data-snapshot-id="${data.snapshot_id}"`));
  contains(html, new RegExp(`${data.days_to_election}(?:<!-- -->)? DAYS OUT`));
  contains(html, new RegExp(`${data.validation_horizon}(?:<!-- -->)?-day Brier`));
  const races = data.races.filter((race) => ["senate", "house", "governor"].includes(race.office));
  contains(html, new RegExp(`${races.length}(?:<!-- -->)? races covered`));
  assert.equal(new Set(races.map((race) => race.id)).size, races.length);
  if (data.pollster_identity_experiment) {
    for (const race of data.races.filter((row) => row.poll_count > 0)) {
      assert.ok(race.normalized_pollster_count > 0);
      assert.ok(race.normalized_pollster_count <= race.pollster_count);
      assert.ok(Number.isFinite(race.raw_poll_margin));
      assert.ok(Math.abs(race.raw_poll_margin - race.poll_house_effect - race.poll_margin) < 1e-8);
      if (race.poll_count === 1) {
        const solePoll = data.evidence.find((poll) => poll.race_id === race.source_race_id);
        assert.ok(solePoll);
        assert.ok(Math.abs(race.raw_poll_margin - solePoll.margin) < 1e-8);
      }
    }
    assert.equal(data.races.find((race) => race.id === "house:TX-09").district_boundary_changed, true);
  }
  if (data.research_audit) {
    const expected = (100 * data.research_audit.subsets.current_offices.winner_accuracy).toFixed(1);
    contains(html.replace(/<!--.*?-->/g, ""), new RegExp(`Winner accuracy</span><strong>${expected}%`));
    contains(html, /competitive races and shared election errors/);
  }
  if (data.collection) {
    contains(html, /cache is not a live update/);
    contains(html, /not an automatically streaming feed/);
  }
  if (data.pollster_identity_experiment) {
    contains(html, /eight-way ablation, no production switch/);
    assert.equal(Object.keys(data.pollster_identity_experiment.ablation).length, 8);
    assert.equal(data.pollster_identity_experiment.adopted, false);
  }
  contains(html, /election-forecast-lab-og-v2-1200x630\.png/);
  assert.ok(!/codex-preview|react-loading-skeleton/i.test(html));
});
