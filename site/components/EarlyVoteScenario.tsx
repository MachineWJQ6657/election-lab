"use client";

import { useState } from "react";
import { earlyVoteScenario } from "../lib/early-vote-scenario";
import type { MapRace } from "../lib/election-map";

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const number = (n: number) => Math.round(n).toLocaleString("en-US");
const clamp = (n: number) => Math.max(0, Math.min(1, n));

export function EarlyVoteScenario({ state, ballots, reference, races }: {
  state: string; ballots: number | null;
  reference?: { two_party_votes: number; source_url: string; scope: string };
  races: MapRace[];
}) {
  const [raceId, setRaceId] = useState("");
  const [turnoutFactor, setTurnoutFactor] = useState(.75);
  const [exposure, setExposure] = useState(1);
  const [earlyShift, setEarlyShift] = useState(0);
  const [remainingShift, setRemainingShift] = useState(0);
  const eligible = races.filter((r) => r.location === state && r.dem_side_party === "D" && r.probability_event !== "pairwise_comparison_only" && ["senate","governor"].includes(r.office));
  const race = eligible.find((r) => r.id === raceId) ?? eligible[0];
  const baselineShare = race ? clamp(.5 + race.model_margin / 200) : .5;
  const finalTurnout = reference ? reference.two_party_votes * turnoutFactor : 0;
  const earlyShare = clamp(baselineShare + earlyShift / 100);
  const remainingShare = clamp(baselineShare + remainingShift / 100);
  const valid = ballots != null && ballots >= 0 && reference && finalTurnout >= ballots && race;
  const scenario = valid ? earlyVoteScenario({ reportedBallots: ballots, finalTurnout, exposure, earlyDemShare: earlyShare, remainingDemShare: remainingShare }) : null;
  return <details className="early-scenario" data-early-vote-scenario="conditional-ballot-accounting">
    <summary>Early-vote scenario lab <span>Adjustable · not the official forecast</span></summary>
    <p>Use reported ballots as an explicit component of a two-side turnout scenario. Preferences and final turnout below are assumptions, not counted votes. Party registration and demographics do not set candidate preferences.</p>
    {!reference || !race || ballots == null ? <p>No compatible statewide two-side race, turnout reference, or reported ballot total is available for {state}. No adjustment is invented.</p> : <>
      <div className="scenario-race"><label>Scenario race<select aria-label="Early-vote scenario race" value={race.id} onChange={(e) => setRaceId(e.target.value)}>{eligible.map((r) => <option key={r.id} value={r.id}>{r.location} {r.office} · {r.dem} / {r.rep}</option>)}</select></label><span>Official {race.dem} win probability: <b>{pct(race.dem_probability)}</b> · unchanged by this lab</span></div>
      <div className="scenario-controls">
        <label>Final-turnout assumption <b>{number(finalTurnout)} · {(100 * turnoutFactor).toFixed(0)}% of reference</b><input aria-label="Final turnout assumption" type="range" min="0.5" max="1.25" step="0.05" value={turnoutFactor} onChange={(e) => setTurnoutFactor(Number(e.target.value))} /></label>
        <label>Reported ballots included <b>{(100 * exposure).toFixed(0)}% · {number(ballots * exposure)} ballots</b><input aria-label="Early-vote influence" type="range" min="0" max="1" step="0.05" value={exposure} onChange={(e) => setExposure(Number(e.target.value))} /></label>
        <label>Assumed early-voter D share <b>{pct(earlyShare)} · shift {earlyShift > 0 ? "+" : ""}{earlyShift.toFixed(1)} pp</b><input aria-label="Assumed early-voter Democratic share shift" type="range" min="-10" max="10" step="0.5" value={earlyShift} onChange={(e) => setEarlyShift(Number(e.target.value))} /></label>
        <label>Assumed remaining-voter D share <b>{pct(remainingShare)} · shift {remainingShift > 0 ? "+" : ""}{remainingShift.toFixed(1)} pp</b><input aria-label="Assumed remaining-voter Democratic share shift" type="range" min="-10" max="10" step="0.5" value={remainingShift} onChange={(e) => setRemainingShift(Number(e.target.value))} /></label>
      </div>
      {scenario ? <div className="scenario-results" aria-live="polite" aria-label="Experimental early-vote scenario results">
        <div><span>Early ballots’ scenario weight</span><strong>{pct(scenario.earlyWeight)}</strong></div>
        <div><span>Conditional vote margin · not win odds</span><strong>{scenario.demMargin >= 0 ? "D" : "R"} +{Math.abs(scenario.demMargin).toFixed(1)} pp</strong></div>
        <div><span>Remaining D share needed for 50% overall</span><strong>{scenario.requiredRemainingDemShare == null ? "No remaining ballots" : scenario.requiredRemainingDemShare < 0 ? "Already met in this scenario" : scenario.requiredRemainingDemShare > 1 ? "Not reachable in this scenario" : pct(scenario.requiredRemainingDemShare)}</strong></div>
      </div> : <p className="early-flag" role="alert">Assumed final turnout is below the reported ballot count. Increase the turnout assumption; the calculator will not discard ballots.</p>}
      {scenario && <p className="early-caption" data-scenario-sensitivity="margin-not-probability">With these assumptions, a +1 pp change in early-voter D share changes the total vote margin by +{(2 * scenario.earlyWeight).toFixed(2)} pp. If early and remaining voters have the same preferences, changing exposure alone has no effect. The official forecast above stays fixed.</p>}
      <p className="early-caption">Reference: <a href={reference.source_url} target="_blank" rel="noreferrer">{number(reference.two_party_votes)} Democratic + Republican presidential votes in 2024 ↗</a>. The default 75% turnout factor is illustrative, not fitted. Both vote-share shifts start at zero relative to this race’s model margin. Increasing reported ballots’ exposure changes their accounting weight, not the official model’s probability weight.</p>
      <p className="early-caution">Two-side arithmetic only: assumes included reported ballots become valid votes for the two modeled sides; third-party votes, rejection rates and unreported modes are not estimated. No calibrated winner probability or chamber simulation is claimed. Comparable historical timing and mode coverage remain insufficient to validate this layer.</p>
      <button type="button" onClick={() => { setTurnoutFactor(.75); setExposure(1); setEarlyShift(0); setRemainingShift(0); }}>Reset assumptions</button>
    </>}
  </details>;
}
