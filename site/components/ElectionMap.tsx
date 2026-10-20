"use client";

import { useEffect, useMemo, useState } from "react";
import atlas from "../lib/us-state-paths.json";
import { bandColor, mapBands, raceBand, raceCounts, stateBand, stateRaces, type MapOffice, type MapRace } from "../lib/election-map";

const officeNames = { senate: "Senate", house: "House", governor: "Governor" };
const pct = (p: number) => `${(p * 100).toFixed(1)}%`;
const margin = (m: number | null) => m == null ? "—" : `${m >= 0 ? "D" : "R"} +${Math.abs(m).toFixed(1)}`;
// Legible, clickable callouts for the small northeastern states and DC.
const callouts: Record<string, [number, number]> = Object.fromEntries(
  ["VT", "NH", "MA", "RI", "CT", "NJ", "DE", "MD", "DC"].map((s, i) => [s, [1010, 140 + i * 35]]),
);
const lightText = new Set(["safe-d", "likely-d", "safe-r", "likely-r"]);
const seatShareLabels = ["≥95% D", "80–95% D", "60–80% D", "40–60% D", "20–40% D", "5–20% D", "≤5% D"];
const states = [...atlas.states].sort((a, b) => a.name.localeCompare(b.name));

export function ElectionMap({ races, office, selectedState, selectedRaceId, filteredState, onStateSelect, onRaceSelect, onOpenRace, onClearState }: {
  races: MapRace[]; office: MapOffice; selectedState: string; selectedRaceId: string;
  filteredState: string | null; onStateSelect: (state: string) => void;
  onRaceSelect: (id: string) => void; onOpenRace: (id: string) => void; onClearState: () => void;
}) {
  const [view, setView] = useState<"map" | "tiles">("map");
  const [hovered, setHovered] = useState<string | null>(null);
  useEffect(() => { if (window.matchMedia("(max-width: 680px)").matches) setView("tiles"); }, []);
  const officeRaces = useMemo(() => races.filter((r) => r.office === office), [races, office]);
  const grouped = useMemo(() => Object.fromEntries(atlas.states.map((s) => [s.code, stateRaces(races, office, s.code)])), [races, office]);
  const counts = raceCounts(officeRaces);
  const activeState = hovered ?? selectedState;
  const state = atlas.states.find((s) => s.code === activeState);
  const current = grouped[activeState] ?? [];
  const race = current.find((r) => r.id === selectedRaceId) ?? current[0];
  const selectedDistricts = grouped[selectedState] ?? [];
  const stateName = atlas.states.find((s) => s.code === selectedState)?.name;
  const share = current.length ? current.reduce((sum, r) => sum + r.dem_probability, 0) / current.length : 0;
  const describe = (code: string, name: string) => {
    const rows = grouped[code];
    if (!rows.length) return `${name}: no ${officeNames[office].toLowerCase()} election in this snapshot`;
    if (office === "house") return `${name}: ${rows.length} districts, expected Democratic seat share ${pct(rows.reduce((s, r) => s + r.dem_probability, 0) / rows.length)}`;
    if (rows.length !== 1 || raceBand(rows[0]) === "unmodeled") return `${name}: multi-candidate contest, full winner probabilities not modeled`;
    return `${name}: ${rows[0].dem}, ${rows[0].dem_side_party} win ${pct(rows[0].dem_probability)}; ${rows[0].rep}, R win ${pct(1 - rows[0].dem_probability)}`;
  };
  const chooseState = (code: string) => { setHovered(null); onStateSelect(code); };

  return <section className="election-map" id="election-map" aria-labelledby="election-map-title">
    <div className="map-heading">
      <div><p>2026 · {officeNames[office].toUpperCase()} FORECAST MAP</p><h3 id="election-map-title">The battleground, at a glance.</h3></div>
      <div className="map-view-switch" aria-label="Map display">
        <button type="button" aria-pressed={view === "map"} onClick={() => setView("map")}>Map</button>
        <button type="button" aria-pressed={view === "tiles"} onClick={() => setView("tiles")}>State tiles</button>
      </div>
    </div>
    <div className="map-seat-totals" aria-label="Contests by forecast category">
      <span><i style={{ background: bandColor("likely-d") }} /><b>{counts.dem}</b> D favored</span>
      <span><i style={{ background: bandColor("tossup") }} /><b>{counts.tossup}</b> Toss-up</span>
      <span><i style={{ background: bandColor("likely-r") }} /><b>{counts.rep}</b> R favored</span>
      {counts.independent > 0 && <span><i style={{ background: bandColor("independent") }} /><b>{counts.independent}</b> I favored</span>}
      {counts.unmodeled > 0 && <span><i style={{ background: bandColor("unmodeled") }} /><b>{counts.unmodeled}</b> Not modeled</span>}
      <small>{officeRaces.length} contests · not chamber seat totals</small>
    </div>
    <div className="map-layout">
      <div className="map-canvas">
        <div className="map-selection-tools">
          <label>Jump to state<select value={selectedState} onChange={(e) => chooseState(e.target.value)} aria-label="Map state">
            {states.map((s) => <option key={s.code} value={s.code}>{s.name}{grouped[s.code].length ? "" : " · no election"}</option>)}
          </select></label>
          {filteredState && <button type="button" className="map-clear" onClick={onClearState}>Clear state filter ×</button>}
        </div>
        {view === "map" ? <div className="map-svg-scroll" onMouseLeave={() => setHovered(null)}>
          <svg viewBox={atlas.viewBox} className="us-election-map" role="group" aria-label={`2026 ${officeNames[office]} forecast map`}>
            <title>{`2026 ${officeNames[office]} forecast map`}</title>
            <desc>Click a state or use the state selector. Alaska and Hawaii are insets. Gray means no election, not a Republican seat. State outlines are not congressional district boundaries.</desc>
            <defs><pattern id="map-unmodeled-hatch" width="7" height="7" patternUnits="userSpaceOnUse"><rect width="7" height="7" fill="#e3ded3" /><path d="M-2,2L2,-2M0,7L7,0M5,9L9,5" stroke="#9d9484" strokeWidth="2" /></pattern></defs>
            {atlas.states.map((s) => {
              const band = stateBand(grouped[s.code], office);
              const callout = callouts[s.code];
              const [x, y] = callout ?? s.label;
              return <g key={s.code} className={`map-state${selectedState === s.code ? " selected" : ""}`} data-state={s.code} data-map-band={band}
                role="button" tabIndex={0} aria-label={describe(s.code, s.name)} aria-pressed={selectedState === s.code}
                onClick={() => chooseState(s.code)} onMouseEnter={() => setHovered(s.code)} onFocus={() => setHovered(s.code)} onBlur={() => setHovered(null)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); chooseState(s.code); } }}>
                <title>{describe(s.code, s.name)}</title>
                <path className="map-state-shape" d={s.path} fill={band === "unmodeled" ? "url(#map-unmodeled-hatch)" : bandColor(band)} fillRule="evenodd" />
                {callout && <><path className="map-callout-line" d={`M${s.label[0]},${s.label[1]}L${x - 28},${y}`} /><rect className="map-callout-box" x={x - 22} y={y - 14} width="44" height="28" rx="2" fill={bandColor(band)} /></>}
                <text x={x} y={y} dy=".35em" className={lightText.has(band) ? "map-label light" : "map-label"}>{s.code}</text>
              </g>;
            })}
            <text x="400" y="590" className="map-inset-note">AK / HI shown as insets</text>
          </svg>
        </div> : <div className="map-state-tiles" aria-label="Alphabetical state tiles, not geographic boundaries" onMouseLeave={() => setHovered(null)}>
          {states.map((s) => {
            const band = stateBand(grouped[s.code], office);
            return <button key={s.code} type="button" className={`${selectedState === s.code ? "selected " : ""}${lightText.has(band) ? "light" : ""}`}
              style={{ background: bandColor(band) }} aria-label={describe(s.code, s.name)} aria-pressed={selectedState === s.code}
              onMouseEnter={() => setHovered(s.code)} onFocus={() => setHovered(s.code)} onBlur={() => setHovered(null)} onClick={() => chooseState(s.code)}>
              <b>{s.code}</b><small>{grouped[s.code].length ? office === "house" ? `${grouped[s.code].length} seats` : band === "unmodeled" ? "3-way" : "2026" : "No race"}</small>
            </button>;
          })}
        </div>}
        <div className="map-legend" aria-label={office === "house" ? "Expected Democratic seat share legend" : "Win probability legend"}>
          {mapBands.map((b, index) => <span key={b.key}><i style={{ background: b.color }} />{office === "house" ? seatShareLabels[index] : b.label}</span>)}
          <span><i style={{ background: bandColor("no-election") }} />No election</span>
          {office !== "house" && <><span><i className="map-hatch-key" />Not modeled</span><span><i style={{ background: bandColor("independent") }} />Independent favored</span></>}
        </div>
      </div>
      <aside className="map-detail" aria-label="Map state detail">
        <div className="map-detail-title">
        <p className="map-detail-kicker">{hovered ? "PREVIEW" : "SELECTED"} · {activeState}</p>
        <h4>{state?.name ?? "Choose a state"}</h4>
        {office === "house" && current.length > 0 && <div className="map-delegation"><strong>{current.length} districts</strong><p>{(share * current.length).toFixed(1)} expected D seats · {(current.length * (1 - share)).toFixed(1)} expected R seats</p></div>}
        </div>
        <div className="map-detail-content">
        {!current.length ? <p className="map-detail-note">No {officeNames[office].toLowerCase()} election is included here for 2026. Gray does not indicate party control.</p> : <>
          {race && <>
            <p className="map-race-name">{officeNames[office]} · {race.location}</p>
            {race.probability_event === "pairwise_comparison_only" ? <p className="map-detail-note">Multi-candidate contest. Full winner probabilities are not modeled; no two-party win probability is shown.</p> : <>
              <div className="map-candidate"><span><small>{race.dem_side_party}</small>{race.dem}</span><strong>{pct(race.dem_probability)}</strong></div>
              <div className="map-candidate"><span><small>R</small>{race.rep}</span><strong>{pct(1 - race.dem_probability)}</strong></div>
              <div className="map-detail-track"><span style={{ width: pct(race.dem_probability), background: race.dem_side_party === "D" ? bandColor("likely-d") : bandColor("independent") }} /></div>
              {race.dem_side_party !== "D" && <p className="map-detail-note">Independent candidate probability, not a Democratic seat or caucus assignment.</p>}
            </>}
            <dl className="map-detail-metrics"><div><dt>Adjusted polls</dt><dd>{margin(race.poll_margin)}</dd></div><div><dt>Model margin</dt><dd>{margin(race.model_margin)}</dd></div></dl>
            <p className="map-detail-note">{race.poll_count ? `${race.poll_count} qualifying poll${race.poll_count === 1 ? "" : "s"} · bounded market context where available.` : "Provisional rating prior · no qualifying direct poll snapshot. Not validated by the poll-model backtest."}</p>
            {race.district_boundary_changed && <p className="map-boundary-note">Redrawn district · old district baseline excluded.</p>}
            <button type="button" className="map-evidence-button" onClick={() => { chooseState(activeState); onOpenRace(race.id); }}>Inspect {race.location} evidence →</button>
          </>}
        </>}
        </div>
      </aside>
    </div>
    {office === "house" && selectedDistricts.length > 0 && <div className="map-districts">
      <div><strong>{stateName} · {selectedDistricts.length} districts</strong><span>Each tile is one district; tile colors show candidate win probabilities, not geographic boundaries.</span></div>
      <div className="map-legend district-legend" aria-label="District win probability legend">{mapBands.map((b) => <span key={b.key}><i style={{ background: b.color }} />{b.label}</span>)}</div>
      <div className="map-district-grid" aria-label={`${stateName} congressional districts`}>
        {[...selectedDistricts].sort((a, b) => a.location.localeCompare(b.location)).map((r) => {
          const band = raceBand(r);
          return <button type="button" key={r.id} className={`${selectedRaceId === r.id ? "selected " : ""}${lightText.has(band) ? "light" : ""}`} style={{ background: bandColor(band) }}
            aria-pressed={selectedRaceId === r.id} aria-label={`${r.location}: ${r.dem_side_party} win ${pct(r.dem_probability)}${r.poll_count ? "" : ", rating prior"}`} onClick={() => onRaceSelect(r.id)}>
            {r.location}<small>{r.dem_side_party} {pct(r.dem_probability)}</small>
          </button>;
        })}
      </div>
    </div>}
    <p className="map-footnote">{office === "house" ? "State colors show expected Democratic seat share, not delegation-control odds. District tiles use the win-probability legend. " : "Colors show candidate win probabilities, not vote share or results. Favored categories start at 60% win probability. "}Gray means no election in this snapshot. <a href="https://github.com/topojson/us-atlas" target="_blank" rel="noreferrer">US Atlas / Census state outlines</a> · <a href="/us-atlas-LICENSE.txt" target="_blank" rel="noreferrer">ISC license</a>. State geography only; no 2026 district-boundary claim.</p>
  </section>;
}
