export type MapOffice = "senate" | "house" | "governor";
export type SeatEstimate = { expected_dem_seats: number; median_dem_seats: number; p05_dem_seats: number; p95_dem_seats: number };
export type MapSeatControl = {
  house: SeatEstimate & { control_threshold: number; dem_control_probability: number };
  senate: SeatEstimate & { control_threshold: number; dem_control_probability: number; non_up_dem_aligned_seats: number };
  governor_elections: SeatEstimate;
  coverage: { house_races: number; senate_races: number; governor_races: number };
};

export function seatComparison(control: MapSeatControl, office: MapOffice) {
  const estimate = office === "governor" ? control.governor_elections : control[office];
  const total = office === "house" ? 435 : office === "senate" ? 100 : control.coverage.governor_races;
  const threshold = office === "governor" ? null : control[office].control_threshold;
  const controlProbability = office === "governor" ? null : control[office].dem_control_probability;
  if (!Number.isInteger(total) || total <= 0) throw new Error("Invalid seat total");
  for (const v of [estimate.expected_dem_seats, estimate.median_dem_seats, estimate.p05_dem_seats, estimate.p95_dem_seats]) {
    if (!Number.isFinite(v) || v < 0 || v > total) throw new Error("Invalid simulated seat estimate");
  }
  if (estimate.p05_dem_seats > estimate.median_dem_seats || estimate.median_dem_seats > estimate.p95_dem_seats) throw new Error("Invalid seat interval");
  if (threshold != null && (!Number.isInteger(threshold) || threshold <= 0 || threshold > total)) throw new Error("Invalid control threshold");
  if (controlProbability != null && (!Number.isFinite(controlProbability) || controlProbability < 0 || controlProbability > 1)) throw new Error("Invalid control probability");
  const nonUpTotal = office === "senate" ? total - control.coverage.senate_races : 0;
  const nonUpDem = office === "senate" ? control.senate.non_up_dem_aligned_seats : 0;
  if (!Number.isInteger(nonUpTotal) || !Number.isInteger(nonUpDem) || nonUpTotal < 0 || nonUpDem < 0 || nonUpDem > nonUpTotal) throw new Error("Invalid Senate holdover seats");
  return {
    total, threshold, controlProbability,
    dem: estimate.median_dem_seats, rep: total - estimate.median_dem_seats,
    expectedDem: estimate.expected_dem_seats, expectedRep: total - estimate.expected_dem_seats,
    demLow: estimate.p05_dem_seats, demHigh: estimate.p95_dem_seats,
    repLow: total - estimate.p95_dem_seats, repHigh: total - estimate.p05_dem_seats,
    nonUpTotal, nonUpDem, nonUpRep: nonUpTotal - nonUpDem,
  };
}
export type MapRace = {
  id: string; office: string; location: string; dem: string; rep: string;
  dem_probability: number; model_probability: number; poll_count: number;
  dem_side_party: string; probability_event: string; poll_margin: number | null;
  model_margin: number; district_boundary_changed: boolean;
};
export const mapBands = [
  { key: "solid-d", label: "Solid D", probability: "≥95%", seatShare: "≥95% D", color: "#254d9b" },
  { key: "likely-d", label: "Likely D", probability: "80–<95%", seatShare: "80–<95% D", color: "#3e6eae" },
  { key: "lean-d", label: "Lean D", probability: "60–<80%", seatShare: "60–<80% D", color: "#91b5e3" },
  { key: "tilt-d", label: "Tilt D", probability: ">50–<60%", seatShare: ">50–<60% D", color: "#c9daed" },
  { key: "tossup", label: "Toss-up", probability: "50 / 50", seatShare: "50% D", color: "#e5ce88" },
  { key: "tilt-r", label: "Tilt R", probability: ">50–<60%", seatShare: ">40–<50% D", color: "#efd2cc" },
  { key: "lean-r", label: "Lean R", probability: "60–<80%", seatShare: ">20–40% D", color: "#e4a69b" },
  { key: "likely-r", label: "Likely R", probability: "80–<95%", seatShare: ">5–20% D", color: "#ad534b" },
  { key: "solid-r", label: "Solid R", probability: "≥95%", seatShare: "≤5% D", color: "#a33739" },
] as const;
export type MapBand = (typeof mapBands)[number]["key"] | "independent" | "unmodeled" | "no-election";
export const specialColors = { independent: "#9671b5", unmodeled: "#9d9484", "no-election": "#dddcd4" };
export function probabilityBand(p: number): (typeof mapBands)[number]["key"] {
  if (!Number.isFinite(p) || p < 0 || p > 1) throw new Error("Invalid map probability");
  if (p === .5) return "tossup";
  // Normalize machine-precision noise at complementary cutoffs, not model odds.
  const confidence = Number(Math.max(p, 1 - p).toFixed(12));
  const rating = confidence >= .95 ? "solid" : confidence >= .8 ? "likely" : confidence >= .6 ? "lean" : "tilt";
  return `${rating}-${p > .5 ? "d" : "r"}`;
}
export function raceBand(race: MapRace): MapBand {
  if (race.probability_event === "pairwise_comparison_only") return "unmodeled";
  const band = probabilityBand(race.dem_probability);
  if (race.dem_side_party !== "D" && race.dem_probability > .5) return "independent";
  return band;
}
export function raceRatingLabel(race: MapRace): string {
  if (race.probability_event === "pairwise_comparison_only") return "Not modeled";
  const label = mapBands.find((b) => b.key === probabilityBand(race.dem_probability))!.label;
  return race.dem_side_party === "D" ? label : label.replace(/D$/, race.dem_side_party);
}
export function stateRatingLabel(races: MapRace[], office: MapOffice): string {
  const band = stateBand(races, office);
  if (band === "no-election") return "No race";
  if (band === "unmodeled") return "Unmodeled";
  // A House state's label is a seat-share estimate, NOT a race rating.
  if (office === "house") return `D ${Math.round(100 * races.reduce((sum, r) => sum + r.dem_probability, 0) / races.length)}%`;
  return raceRatingLabel(races[0]);
}
export function bandColor(band: MapBand): string {
  return mapBands.find((item) => item.key === band)?.color ?? specialColors[band as keyof typeof specialColors];
}
export function stateRaces(races: MapRace[], office: MapOffice, state: string): MapRace[] {
  return races.filter((r) => r.office === office && r.location.slice(0, 2) === state)
    .sort((a, b) => Math.abs(a.dem_probability - .5) - Math.abs(b.dem_probability - .5) || a.location.localeCompare(b.location));
}
export function stateBand(races: MapRace[], office: MapOffice): MapBand {
  if (!races.length) return "no-election";
  if (office !== "house") return races.length === 1 ? raceBand(races[0]) : "unmodeled";
  // This is an expected seat SHARE, never the probability of delegation control.
  if (races.some((r) => r.probability_event === "pairwise_comparison_only" || r.dem_side_party !== "D")) return "unmodeled";
  return probabilityBand(races.reduce((sum, r) => sum + r.dem_probability, 0) / races.length);
}
export function raceCounts(races: MapRace[]) {
  const counts = { dem: 0, tossup: 0, rep: 0, independent: 0, unmodeled: 0 };
  for (const race of races) {
    const band = raceBand(race);
    if (band === "unmodeled") counts.unmodeled++;
    else if (band === "independent") counts.independent++;
    else if (band === "tossup") counts.tossup++;
    else if (band.endsWith("-d")) counts.dem++;
    else counts.rep++;
  }
  return counts;
}

export function seatRatingSummary(races: MapRace[], control: MapSeatControl, office: MapOffice) {
  const seats = seatComparison(control, office);
  const rows = races.filter((r) => r.office === office);
  const expected = office === "house" ? 435 : office === "senate" ? control.coverage.senate_races : control.coverage.governor_races;
  if (rows.length !== expected || new Set(rows.map((r) => r.id)).size !== expected) throw new Error("Incomplete or duplicate map races");
  const bands = mapBands.map((b) => ({ ...b, count: rows.filter((r) => raceBand(r) === b.key).length }));
  const counts = raceCounts(rows);
  const segments = [
    { key: "holdover-d", label: "D-aligned · not up", color: "#254d9b", count: seats.nonUpDem, holdover: true },
    ...bands.slice(0,4),
    bands[4],
    { key: "independent", label: "Independent favored", color: specialColors.independent, count: counts.independent },
    { key: "unmodeled", label: "Not modeled", color: specialColors.unmodeled, count: counts.unmodeled },
    ...bands.slice(5),
    { key: "holdover-r", label: "R-aligned · not up", color: "#a33739", count: seats.nonUpRep, holdover: true },
  ].filter((s) => s.count > 0);
  if (segments.reduce((sum, s) => sum + s.count, 0) !== seats.total) throw new Error("Map rating seats do not sum to total");
  return { bands, segments, ...counts, dem: counts.dem + seats.nonUpDem, rep: counts.rep + seats.nonUpRep, total: seats.total, nonUpDem: seats.nonUpDem, nonUpRep: seats.nonUpRep };
}
