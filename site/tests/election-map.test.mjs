import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { probabilityBand, raceBand, stateBand, stateRaces, raceCounts, bandColor } from "../lib/election-map.ts";

const data = JSON.parse(await readFile(new URL("../lib/forecast-data.json", import.meta.url), "utf8"));
const atlas = JSON.parse(await readFile(new URL("../lib/us-state-paths.json", import.meta.url), "utf8"));
const example = { id: "senate:TX", office: "senate", location: "TX", dem_side_party: "D", probability_event: "candidate_win", dem_probability: .7 };

test("probability boundaries, uncertainty and invalid values", () => {
  const samples = [[1,"safe-d"],[.95,"safe-d"],[.949,"likely-d"],[.8,"likely-d"],[.6,"lean-d"],[.599,"tossup"],[.401,"tossup"],[.4,"lean-r"],[.2,"likely-r"],[.05,"safe-r"],[0,"safe-r"]];
  for (const [p, expected] of samples) assert.equal(probabilityBand(p), expected);
  for (const p of [NaN, Infinity, -1, 1.1]) assert.throws(() => probabilityBand(p));
});
test("no election, independent and three-way contests remain distinct", () => {
  assert.equal(stateBand([], "senate"), "no-election");
  assert.equal(raceBand({ ...example, dem_side_party: "I" }), "independent");
  assert.equal(raceBand({ ...example, dem_side_party: "I", dem_probability: .5 }), "tossup");
  assert.equal(raceBand({ ...example, dem_side_party: "I", dem_probability: .1 }), "likely-r");
  assert.equal(raceBand({ ...example, probability_event: "pairwise_comparison_only" }), "unmodeled");
  assert.equal(stateBand([example, example], "senate"), "unmodeled");
  assert.equal(raceBand(data.races.find((r) => r.id === "senate:MT")), "unmodeled");
});
test("House state colors use expected seat share, never delegation win odds", () => {
  assert.equal(stateBand([{ ...example, dem_probability: .9 }, { ...example, dem_probability: .1 }], "house"), "tossup");
  assert.equal(stateBand([{ ...example, dem_side_party: "I" }], "house"), "unmodeled");
});
test("all modeled contests map exactly once and counts are exhaustive", () => {
  for (const [office, expected] of [["house",435],["senate",35],["governor",36]]) {
    const rows = atlas.states.flatMap((s) => stateRaces(data.races, office, s.code));
    assert.equal(rows.length, expected);
    assert.equal(new Set(rows.map((r) => r.id)).size, expected);
    assert.equal(Object.values(raceCounts(rows)).reduce((a,b) => a+b, 0), expected);
    for (const s of atlas.states) assert.match(bandColor(stateBand(stateRaces(data.races, office, s.code), office)), /^#[a-f0-9]{6}$/i);
  }
  assert.equal(stateRaces(data.races, "house", "TX").length, 38);
  assert.equal(stateRaces(data.races, "house", "CA").length, 52);
  assert.equal(stateRaces(data.races, "house", "AK").length, 1);
});
test("SVG source includes 50 states and DC with finite projected geometry", () => {
  assert.equal(atlas.states.length, 51);
  assert.equal(new Set(atlas.states.map((s) => s.code)).size, 51);
  assert.match(atlas.source_sha256, /^[a-f0-9]{64}$/);
  assert.match(atlas.source, /us-atlas@3\.0\.1/);
  assert.match(atlas.boundary_vintage, /not congressional districts/);
  for (const s of atlas.states) {
    assert.match(s.path, /^M[\d.-]+,[\d.-]+L/);
    assert.ok(!/NaN|Infinity|undefined/.test(s.path));
    assert.ok(s.label.every(Number.isFinite));
    assert.ok(s.label[0] >= 0 && s.label[0] <= 975);
    assert.ok(s.label[1] >= 0 && s.label[1] <= 610);
  }
});
