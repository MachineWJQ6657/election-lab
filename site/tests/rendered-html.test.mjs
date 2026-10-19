import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

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
  assert.match(html, /Election Forecast Lab/);
  assert.match(html, /House leans Democratic/);
  assert.match(html, /Balance of power/);
  assert.match(html, /RACE EXPLORER/);
  assert.match(html, /Uncertainty/);
  assert.match(html, /OBSERVED PARTICIPATION/);
  assert.match(html, /not votes for a candidate/);
  const data = JSON.parse(await readFile(new URL("../lib/forecast-data.json", import.meta.url), "utf8"));
  assert.match(html, new RegExp(`${data.days_to_election}(?:<!-- -->)? DAYS OUT`));
  assert.match(html, new RegExp(`${data.validation_horizon}(?:<!-- -->)?-day Brier`));
  const races = data.races.filter((race) => ["senate", "house", "governor"].includes(race.office));
  assert.match(html, new RegExp(`${races.length}(?:<!-- -->)? races covered`));
  assert.equal(new Set(races.map((race) => race.id)).size, races.length);
  if (data.research_audit) {
    const expected = (100 * data.research_audit.subsets.current_offices.winner_accuracy).toFixed(1);
    assert.match(html.replace(/<!--.*?-->/g, ""), new RegExp(`Winner accuracy</span><strong>${expected}%`));
    assert.match(html, /competitive races and shared election errors/);
  }
  assert.match(html, /election-forecast-lab-og-v2-1200x630\.png/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
});
