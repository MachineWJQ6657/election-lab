import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { mapBands, probabilityBand, raceBand, raceRatingLabel, stateRatingLabel, stateBand, stateRaces, raceCounts, bandColor, seatComparison, seatRatingSummary } from "../lib/election-map.ts";

const data = JSON.parse(await readFile(new URL("../lib/forecast-data.json", import.meta.url), "utf8"));
const atlas = JSON.parse(await readFile(new URL("../lib/us-state-paths.json", import.meta.url), "utf8"));
const example = { id: "senate:TX", office: "senate", location: "TX", dem_side_party: "D", probability_event: "candidate_win", dem_probability: .7 };

test("probability boundaries, uncertainty and invalid values", () => {
  const samples = [[1,"solid-d"],[.95,"solid-d"],[.949,"likely-d"],[.8,"likely-d"],[.799,"lean-d"],[.6,"lean-d"],[.599,"tilt-d"],[.50001,"tilt-d"],[.5,"tossup"],[.49999,"tilt-r"],[.401,"tilt-r"],[.4,"lean-r"],[.201,"lean-r"],[.2,"likely-r"],[.051,"likely-r"],[.05,"solid-r"],[0,"solid-r"]];
  for (const [p, expected] of samples) assert.equal(probabilityBand(p), expected);
  for (const p of [NaN, Infinity, -1, 1.1]) assert.throws(() => probabilityBand(p));
});
test("all nine model categories are named, symmetric and have unique colors", () => {
  assert.deepEqual(mapBands.map((b) => b.label), ["Solid D","Likely D","Lean D","Tilt D","Toss-up","Tilt R","Lean R","Likely R","Solid R"]);
  assert.equal(new Set(mapBands.map((b) => b.color)).size,9);
  for (let i = 0; i <= 1000; i++) {
    const p = i / 1000;
    const mirror = probabilityBand(p).replace(/-[dr]$/, (side) => side === "-d" ? "-r" : "-d");
    assert.equal(probabilityBand(1-p),mirror,`asymmetric category at ${p}`);
  }
});
test("no election, independent and three-way contests remain distinct", () => {
  assert.equal(stateBand([], "senate"), "no-election");
  assert.equal(raceBand({ ...example, dem_side_party: "I" }), "independent");
  assert.equal(raceBand({ ...example, dem_side_party: "I", dem_probability: .5 }), "tossup");
  assert.equal(raceBand({ ...example, dem_side_party: "I", dem_probability: .51 }), "independent");
  assert.equal(raceRatingLabel({ ...example, dem_side_party: "I", dem_probability: .51 }), "Tilt I");
  assert.equal(raceRatingLabel({ ...example, dem_side_party: "I", dem_probability: .49 }), "Tilt R");
  assert.equal(raceRatingLabel({ ...example, dem_side_party: "I", dem_probability: .95 }), "Solid I");
  assert.equal(raceBand({ ...example, dem_side_party: "I", dem_probability: .1 }), "likely-r");
  assert.equal(raceBand({ ...example, probability_event: "pairwise_comparison_only" }), "unmodeled");
  assert.equal(stateBand([example, example], "senate"), "unmodeled");
  assert.equal(raceBand(data.races.find((r) => r.id === "senate:MT")), "unmodeled");
  assert.equal(raceRatingLabel(data.races.find((r) => r.id === "senate:MT")), "Not modeled");
});
test("House state colors use expected seat share, never delegation win odds", () => {
  assert.equal(stateBand([{ ...example, dem_probability: .9 }, { ...example, dem_probability: .1 }], "house"), "tossup");
  assert.equal(stateBand([{ ...example, dem_side_party: "I" }], "house"), "unmodeled");
  assert.equal(stateRatingLabel([example], "house"), "D 70%");
  assert.equal(stateRatingLabel([example], "senate"), "Lean D");
  assert.equal(stateRatingLabel([], "senate"), "No race");
  assert.equal(stateRatingLabel([{ ...example, probability_event: "pairwise_comparison_only" }], "senate"), "Unmodeled");
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

test("final seat comparison includes the whole chamber and complementary intervals", () => {
  for (const [office, total] of [["house",435],["senate",100],["governor",36]]) {
    const s = seatComparison(data.control,office);
    assert.equal(s.total,total);
    assert.equal(s.dem+s.rep,total);
    assert.ok(Math.abs(s.expectedDem+s.expectedRep-total)<1e-9);
    assert.equal(s.demLow+s.repHigh,total);
    assert.equal(s.demHigh+s.repLow,total);
  }
  assert.equal(seatComparison(data.control,"house").dem,data.control.house.median_dem_seats);
  assert.equal(seatComparison(data.control,"senate").dem,data.control.senate.median_dem_seats);
});
test("Senate non-election seats are included without counting them twice", () => {
  const s=seatComparison(data.control,"senate");
  assert.equal(s.nonUpTotal,100-data.control.coverage.senate_races);
  assert.equal(s.nonUpDem,34);
  assert.equal(s.nonUpRep,31);
  assert.equal(s.threshold,51);
  assert.equal(s.expectedDem,data.control.senate.expected_dem_seats);
  assert.ok(Math.abs(s.expectedDem-s.nonUpDem-data.control.senate.dem_wins_among_seats_up)<1e-9);
});
test("simulation median is not confused with a favored-race category count", () => {
  const senateRaces=data.races.filter((r)=>r.office==="senate");
  assert.notEqual(seatComparison(data.control,"senate").dem,raceCounts(senateRaces).dem);
  assert.equal(seatComparison(data.control,"governor").threshold,null);
  assert.equal(seatComparison(data.control,"governor").controlProbability,null);
});
test("invalid seat summaries fail closed", () => {
  const invalid=structuredClone(data.control);
  invalid.senate.non_up_dem_aligned_seats=66;
  assert.throws(()=>seatComparison(invalid,"senate"),/holdover/);
  invalid.house.expected_dem_seats=NaN;
  assert.throws(()=>seatComparison(invalid,"house"),/seat estimate/);
  invalid.governor_elections.median_dem_seats=51;
  assert.throws(()=>seatComparison(invalid,"governor"),/seat estimate/);
});

test("segmented rating bar counts actual map seats and holdovers, not simulation medians", () => {
  for (const [office,total] of [["house",435],["senate",100],["governor",36]]) {
    const r = seatRatingSummary(data.races,data.control,office);
    assert.equal(r.segments.reduce((sum,s)=>sum+s.count,0),total);
    assert.equal(r.dem+r.rep+r.tossup+r.independent+r.unmodeled,total);
    assert.equal(r.bands.length,9);
    assert.ok(r.segments.every((s)=>s.count>0));
  }
  const senate=seatRatingSummary(data.races,data.control,"senate");
  assert.equal(senate.segments.find((s)=>s.key==="holdover-d").count,34);
  assert.equal(senate.segments.find((s)=>s.key==="holdover-r").count,31);
  assert.equal(senate.segments.find((s)=>s.key==="unmodeled").count,1);
  assert.notEqual(senate.rep,seatComparison(data.control,"senate").rep);
  assert.throws(()=>seatRatingSummary(data.races.filter((r)=>r.id!=="senate:TX"),data.control,"senate"),/Incomplete/);
  const duplicate = data.races.map((r)=>r.id==="senate:TX" ? {...r,id:"senate:ME"} : r);
  assert.throws(()=>seatRatingSummary(duplicate,data.control,"senate"),/duplicate/);
});
