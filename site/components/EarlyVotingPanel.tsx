"use client";

import { useState } from "react";

type EarlyState = {
  state: string; requested: number | null; returned: number | null; inperson: number | null;
  observed_ballots: number | null; democratic: number; republican: number; other: number;
  unspecified: number; snapshot_date: string; sources: string[]; source_urls: string[];
  review_flags: { check: string; category?: string; aggregator?: number; official?: number }[];
  request_basis: string;
};
export type EarlyVotingData = {
  as_of: string; states: EarlyState[]; reporting_states: number; issue_count: number;
  historical_snapshots_available: number;
  model_gate: { accepted: boolean; probability_weight: number; reason: string };
  references: { name: string; url: string }[];
  demographics: { state: string; dimension: string; group: string; count: number }[];
};
const number = (n: number | null) => n == null ? "—" : n.toLocaleString("en-US");

export function EarlyVotingPanel({ data }: { data: EarlyVotingData }) {
  const [state, setState] = useState("NC");
  const [dimension, setDimension] = useState("race");
  const selected = data.states.find((row) => row.state === state) ?? data.states[0];
  const castStates = data.states.filter((row) => row.observed_ballots != null);
  const ballots = castStates.reduce((sum, row) => sum + (row.observed_ballots ?? 0), 0);
  const rows = [...data.states].sort((a, b) => (b.observed_ballots ?? -1) - (a.observed_ballots ?? -1));
  const dimensions = [...new Set(data.demographics.filter((row) => row.state === selected?.state).map((row) => row.dimension))];
  const selectedDimension = dimensions.includes(dimension) ? dimension : dimensions[0] ?? "race";
  const demo = data.demographics.filter((row) => row.state === selected?.state && row.dimension === selectedDimension);
  const demoTotal = demo.reduce((sum, row) => sum + row.count, 0);
  const partyTotal = selected?.observed_ballots ?? 0;
  const summaryFlags = selected?.review_flags.filter((flag, index, flags) => flag.check === "provider_official_difference" || flags.findIndex((item) => item.check === flag.check) === index) ?? [];

  return <section className="section-shell early-section" id="early-vote">
    <div className="section-title compact"><div><p>EARLY VOTE · OBSERVED PARTICIPATION</p><h2>Ballots arriving. Outcomes still uncertain.</h2></div><span>Snapshot {data.as_of}</span></div>
    <p className="early-intro">{number(ballots)} reported mail returns and in-person early ballots across {castStates.length} states. Coverage and reporting times vary; requests and outstanding ballots are excluded from this total.</p>
    <div className="early-layout">
      <div className="early-table-wrap"><table className="early-table">
        <caption>Reporting states · select a row for sources and voter registration</caption>
        <thead><tr><th>State</th><th>Mail returned</th><th>In person</th><th>Observed total</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.state} className={selected?.state === row.state ? "selected" : ""}>
          <th><button type="button" aria-pressed={selected?.state === row.state} onClick={() => setState(row.state)}>{row.state}{row.review_flags.length > 0 && <span aria-label="Source or coverage limitation"> *</span>}</button></th>
          <td>{number(row.returned)}</td><td>{number(row.inperson)}</td><td>{number(row.observed_ballots)}</td>
        </tr>)}</tbody>
      </table></div>
      {selected && <aside className="early-detail" aria-live="polite">
        <div className="early-detail-heading"><h3>{selected.state} participation</h3><span>{selected.snapshot_date}</span></div>
        <dl><div><dt>Mail requests / issued</dt><dd>{number(selected.requested)}</dd></div><div><dt>Reported ballots</dt><dd>{number(selected.observed_ballots)}</dd></div></dl>
        <p className="early-caption">{selected.request_basis}. A dash means unavailable, not zero.</p>
        <h4>Registered party of reported voters</h4>
        {partyTotal > 0 && selected.unspecified < partyTotal ? <>
          <div className="early-party-bar" aria-label="Registered party composition">
            {(["democratic", "republican", "other", "unspecified"] as const).map((key) => <span key={key} className={key} style={{ width: `${100 * selected[key] / partyTotal}%` }} title={`${key}: ${number(selected[key])}`} />)}
          </div>
          <div className="early-party-legend"><span>D {number(selected.democratic)}</span><span>R {number(selected.republican)}</span><span>Other / unaffiliated {number(selected.other)}</span><span>Not reported {number(selected.unspecified)}</span></div>
        </> : <p className="early-caption">Party registration is not reported for this state or snapshot. No party split is inferred.</p>}
        <p className="early-caution">These are registration records, not votes for a candidate. Early voting can replace Election Day voting without increasing final turnout.</p>
        {demo.length > 0 && <div className="early-demographics">
          <label>Reported demographic breakdown <select value={selectedDimension} onChange={(event) => setDimension(event.target.value)}>{dimensions.map((key) => <option key={key} value={key}>{key === "age" ? "Age" : key === "race" ? "Race" : key === "ethnicity" ? "Ethnicity" : "Gender"}</option>)}</select></label>
          {[...demo].sort((a, b) => b.count - a.count).map((row) => <div className="early-demo-row" key={row.group}><span>{row.group}</span><b>{number(row.count)}</b><small>{demoTotal ? (100 * row.count / demoTotal).toFixed(1) : "0.0"}%</small></div>)}
          <p className="early-caption">{selected.state === "NC" ? "North Carolina official aggregate grid" : "civicAPI aggregate reporting"}; race and ethnicity are separate dimensions. Unreported buckets include missing records or voting modes; shares use all observed ballots. No candidate preference is inferred.</p>
        </div>}
        {summaryFlags.map((flag, index) => <p className="early-flag" key={index}>{flag.check === "provider_official_difference" ? `Source difference (${flag.category}): aggregator ${number(flag.aggregator ?? null)}, official ${number(flag.official ?? null)}. Official statewide total is used.` : flag.check === "demographic_partial_coverage" ? "Some demographic records are unreported; they remain in the unknown bucket." : flag.check === "demographic_total_mismatch" ? "A demographic denominator did not reconcile; that breakdown is withheld." : flag.check === "capabilities_cache_fallback" ? "Provider discovery was unavailable; a verified older capability map was used to find separately fetched reports. The capability map supplies no ballot counts." : "Demographic detail is unavailable for part of this snapshot; reported ballot totals are retained."}</p>)}
        <div className="early-links">{selected.source_urls.map((url) => <a key={url} href={url} target="_blank" rel="noreferrer">{selected.sources.includes("ncsbe") || selected.sources.includes("florida_dos") ? "Official source" : "civicAPI data"} ↗</a>)}</div>
      </aside>}
    </div>
    <details className="early-method"><summary>How early voting affects this forecast · weight {data.model_gate.probability_weight * 100}%</summary>
      <p>{data.model_gate.reason}</p>
      <p>{data.historical_snapshots_available} historical state snapshots were retrieved at matching days before Election Day. Mode definitions and publication history are insufficient for a validated turnout correction. The forecast continues to update from new polling and its historical calibration.</p>
      <p>{data.references.map((reference) => <a href={reference.url} key={reference.url} target="_blank" rel="noreferrer">{reference.name} ↗ </a>)}</p>
    </details>
  </section>;
}
