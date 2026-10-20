export type MapOffice = "senate" | "house" | "governor";
export type MapRace = {
  id: string; office: string; location: string; dem: string; rep: string;
  dem_probability: number; model_probability: number; poll_count: number;
  dem_side_party: string; probability_event: string; poll_margin: number | null;
  model_margin: number; district_boundary_changed: boolean;
};
export const mapBands = [
  { key: "safe-d", label: "D ≥95%", color: "#254d9b" },
  { key: "likely-d", label: "D 80–95%", color: "#4779c5" },
  { key: "lean-d", label: "D 60–80%", color: "#91b5e3" },
  { key: "tossup", label: "Toss-up", color: "#e5ce88" },
  { key: "lean-r", label: "R 60–80%", color: "#e4a69b" },
  { key: "likely-r", label: "R 80–95%", color: "#ca6c62" },
  { key: "safe-r", label: "R ≥95%", color: "#a33739" },
] as const;
export type MapBand = (typeof mapBands)[number]["key"] | "independent" | "unmodeled" | "no-election";
export const specialColors = { independent: "#9671b5", unmodeled: "#9d9484", "no-election": "#dddcd4" };
export function probabilityBand(p: number): (typeof mapBands)[number]["key"] {
  if (!Number.isFinite(p) || p < 0 || p > 1) throw new Error("Invalid map probability");
  if (p >= .95) return "safe-d";
  if (p >= .8) return "likely-d";
  if (p >= .6) return "lean-d";
  if (p > .4) return "tossup";
  if (p > .2) return "lean-r";
  if (p > .05) return "likely-r";
  return "safe-r";
}
export function raceBand(race: MapRace): MapBand {
  if (race.probability_event === "pairwise_comparison_only") return "unmodeled";
  if (race.dem_side_party !== "D" && race.dem_probability >= .6) return "independent";
  return probabilityBand(race.dem_probability);
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
