"use client";

import { useMemo, useState } from "react";
import { EarlyVotingPanel, type EarlyVotingData } from "./EarlyVotingPanel";

type Office = "senate" | "house" | "governor";
type Race = { id: string; source_race_id: string; office: string; location: string; dem: string; rep: string; poll_count: number; pollster_count: number; normalized_pollster_count: number | null; raw_poll_margin: number | null; poll_house_effect: number | null; poll_margin: number | null; model_margin: number; model_probability: number; market_probability: number | null; dem_probability: number; market_weight: number; probability_source: string; validation_scope: string; rating: string | null; rating_source: string | null; model: string; competitiveness: number; dem_side_party: string; multi_candidate_warning: string; probability_event: string; district_boundary_changed: boolean; };
type Evidence = { race_id: string; pollster: string; end_date: string; sample_size: number | null; population: string; partisan: string | null; dem_pct: number; rep_pct: number; margin: number; normalized_race_weight: number; source: string; publisher_domain: string | null; source_url: string; corroborated_sources: string; source_reachable: boolean | null; };
type Distribution = { office: string; dem_seats: number; simulations: number; probability: number; };
type ModelSelection = { office: string; model: string; validated_horizon: number; independent_races: number; brier: number; selection_reason: string; };
type NestedResult = { office: string; races: number; accuracy: number; mae: number; brier: number; };
type DiagnosticScore = { races: number; cycles: number; winner_accuracy: number; brier: number; margin_mae: number; mean_confidence: number; ece_10_bins: number };

export type ForecastData = {
  snapshot_id: string;
  updated_at: string;
  days_to_election: number;
  heldout_forecasts: number;
  validation_horizon: number;
  latest_poll_date: string;
  active_poll_count: number;
  source_link_check: { sample_size: number; reachable: number; generated_at: string } | null;
  collection: { checked_at: string; request_status_counts: Record<string, number>; oldest_observed_at: string | null; latest_observed_at: string | null; scope: string } | null;
  recency_experiment: { challengers: { half_life_days: number; races: number; brier: number; accuracy: number }[]; baseline_30: { brier: number }; outer_policy: { brier: number } } | null;
  publication_lag_experiment: { baseline_common_races: { races: number; brier: number }; delayed_common_races: { races: number; brier: number }; scope: string } | null;
  house_control_validation: { results: { method: string; independent_cycles: number; brier: number; seat_mae: number }[]; scope: string } | null;
  research_audit: { scope: string; subsets: Record<string, DiagnosticScore>; paired_weighted_poll_comparison: { common_races: number; independent_cycle_clusters: number; selected_minus_baseline_brier: number; exploratory_95pct_cycle_interval: number[] }; questions: { perspective: string; question: string; decision: string }[] } | null;
  correlation_experiment: { results: { office: string; method: string; independent_cycles: number; mean_count_rps: number; interval_coverage: number }[]; scope: string } | null;
  pollster_identity_experiment: { baseline: DiagnosticScore; challenger: DiagnosticScore; outer_policy: DiagnosticScore; outer_paired_comparison: { exploratory_95pct_cycle_interval: number[] }; ablation: Record<string, DiagnosticScore>; adopted: boolean; scope: string } | null;
  early_voting: EarlyVotingData | null;
  control: {
    simulations: number;
    independent_caucus_sensitivity: { unresolved_states: string[]; dem_control_lower_endpoint: number; dem_control_upper_endpoint: number; interpretation: string } | null;
    house: { expected_dem_seats: number; median_dem_seats: number; p05_dem_seats: number; p95_dem_seats: number; dem_control_probability: number; };
    senate: { expected_dem_seats: number; median_dem_seats: number; p05_dem_seats: number; p95_dem_seats: number; dem_control_probability: number; };
    governor_elections: { expected_dem_seats: number };
    prediction_market_context: { comparisons: Record<string, { market_consensus_dem_probability: number; bounded_market_context_probability: number; }>; };
  };
  races: Race[];
  evidence: Evidence[];
  distributions: Distribution[];
  model_selection: ModelSelection[];
  nested_backtest: NestedResult[];
  authenticity: { verdict: string; issue_count: number; latest_polls: number; latest_pollsters: number; poll_sources: Record<string, number>; hashes_verified: number; fec_matches: number; fec_checked: number; fec_name_review_flags: number; fec_match_note: string; top_source_domains: [string, number][]; };
};

const officeLabels: Record<Office, string> = { senate: "Senate", house: "House", governor: "Governors" };
const stateNames: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey",
  NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming", DC: "District of Columbia",
};
const pct = (value: number | null, digits = 1) => value == null ? "—" : `${(100 * value).toFixed(digits)}%`;
const observationTime = (value: string | null) => value == null ? "unavailable" : `${new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "America/New_York" }).format(new Date(value))} ET`;
const margin = (value: number | null) => value == null ? "—" : `${value >= 0 ? "D" : "R"} +${Math.abs(value).toFixed(1)}`;
const controlRead = (office: "House" | "Senate", value: number) => value >= 0.6 ? `${office} leans Democratic.` : value <= 0.4 ? `${office} leans Republican.` : `${office} remains a toss-up.`;
const modelLabel = (value: string) => value.replace("candidate_evidence_ml_blend", "Evidence-adaptive Ridge blend").replace("robust_poll_ml_blend", "Ridge + poll/fundamentals").replace("conditional_candidate_blend", "Candidate-aware fundamentals").replace("environment_adjusted_blend", "National environment blend").replace("house_effect_poll", "House-effect poll average").replaceAll("_", " ");
const compactModelLabel = (value: string) => value.replace("candidate_evidence_ml_blend", "Evidence-adaptive blend").replace("robust_poll_ml_blend", "Ridge blend").replace("conditional_candidate_blend", "Candidate blend").replace("environment_adjusted_blend", "Environment blend").replace("house_effect_poll", "Poll average").replaceAll("_", " ");

function ProbabilityLine({ value }: { value: number }) {
  return <div className="race-probability" aria-label={`Democratic probability ${pct(value)}`}><span style={{ width: `${100 * value}%` }} /><b>{pct(value, 0)}</b></div>;
}

function DistributionChart({ data, office }: { data: Distribution[]; office: "house" | "senate" }) {
  const values = data.filter((row) => row.office === office);
  const peak = Math.max(0.001, ...values.map((row) => row.probability));
  const threshold = office === "house" ? 218 : 51;

  return <div className="distribution-chart" aria-label={`${officeLabels[office]} Democratic seat distribution`}>
    {values.map((row) => <div className={`distribution-bar ${row.dem_seats >= threshold ? "wins" : "loses"}`} key={row.dem_seats} style={{ height: `${Math.max(3, (100 * row.probability) / peak)}%` }} title={`${row.dem_seats} seats: ${pct(row.probability, 2)}`} />)}
    <span className="threshold-note">CONTROL THRESHOLD →</span>
    {values.length > 0 && <div className="chart-axis"><span>{values[0].dem_seats} D seats</span><span>{values.at(-1)?.dem_seats} D seats</span></div>}
  </div>;
}

export function ForecastDashboard({ data }: { data: ForecastData }) {
  const [office, setOffice] = useState<Office>("senate");
  const [query, setQuery] = useState("");
  const [distributionOffice, setDistributionOffice] = useState<"house" | "senate">("house");
  const defaultRace = data.races.find((race) => race.id === "senate:TX") ?? data.races.find((race) => race.office === "senate");
  const [selectedRaceId, setSelectedRaceId] = useState(defaultRace?.id ?? "");

  const races = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return data.races
      .filter((race) => race.office === office)
      .filter((race) => !needle || [race.location, stateNames[race.location.slice(0, 2)], race.dem, race.rep, race.rating].filter(Boolean).join(" ").toLowerCase().includes(needle))
      .sort((a, b) => a.competitiveness - b.competitiveness);
  }, [data.races, office, query]);

  const selectedRace = races.find((race) => race.id === selectedRaceId) ?? races[0] ?? null;
  const selectedEvidence = selectedRace ? data.evidence.filter((poll) => poll.race_id === selectedRace.source_race_id).slice(0, 8) : [];
  const overallBacktest = data.nested_backtest.find((row) => row.office === "__overall__");
  const currentValidation = data.research_audit?.subsets.current_offices;
  const closeValidation = data.research_audit?.subsets.forecast_probability_20_80;
  const cycleComparison = data.research_audit?.paired_weighted_poll_comparison;
  const houseMarket = data.control.prediction_market_context.comparisons.house;
  const senateMarket = data.control.prediction_market_context.comparisons.senate;
  const updateLabel = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(data.updated_at));
  const totalRaces = data.races.filter((race) => race.office in officeLabels).length;
  const controlCards = [
    { label: "HOUSE CONTROL", value: houseMarket.bounded_market_context_probability, title: "Democratic", opponent: "Republican", note: `${data.control.house.expected_dem_seats.toFixed(1)} expected D seats`, secondary: `Model ${pct(data.control.house.dem_control_probability)} · market ${pct(houseMarket.market_consensus_dem_probability)}` },
    { label: "SENATE CONTROL", value: senateMarket.bounded_market_context_probability, title: "Democratic", opponent: "Republican", note: `${data.control.senate.expected_dem_seats.toFixed(1)} expected D-aligned seats`, secondary: `Model ${pct(data.control.senate.dem_control_probability)} · market ${pct(senateMarket.market_consensus_dem_probability)}` },
    { label: "TEXAS SENATE", value: defaultRace?.dem_probability ?? 0.5, title: defaultRace?.dem ?? "Talarico", opponent: defaultRace?.rep ?? "Paxton", note: `Polls ${margin(defaultRace?.poll_margin ?? null)} · model ${margin(defaultRace?.model_margin ?? null)}`, secondary: `Model-only ${pct(defaultRace?.model_probability ?? null)} · market ${pct(defaultRace?.market_probability ?? null)}` },
  ];

  const selectOffice = (nextOffice: Office) => {
    const firstRace = data.races.filter((race) => race.office === nextOffice).sort((a, b) => a.competitiveness - b.competitiveness)[0];
    setOffice(nextOffice);
    setQuery("");
    setSelectedRaceId(firstRace?.id ?? "");
  };

  const selectRace = (raceId: string) => {
    setSelectedRaceId(raceId);
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 1100px)").matches) {
      window.requestAnimationFrame(() => document.querySelector(".race-inspector")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  };

  return <main className="forecast-shell" data-snapshot-id={data.snapshot_id}>
    <header className="desk-header" id="top">
      <a className="desk-wordmark" href="#top" aria-label="Election Forecast Lab home"><b>EF</b><span>Election Forecast Lab</span></a>
      <nav aria-label="Primary navigation"><a href="#forecast">Forecast</a><a href="#races">Races</a><a href="#early-vote">Early vote</a><a href="#methodology">Methods</a></nav>
      <div className="desk-status"><i /> Updated {updateLabel}</div>
    </header>

    <section className="desk-intro">
      <div className="desk-intro-copy">
        <div className="desk-edition"><span>2026 MIDTERMS</span><span>{data.days_to_election} DAYS OUT</span><span>MODEL № 01</span></div>
        <p className="desk-eyebrow">CURRENT CONTROL OUTLOOK</p>
        <h1>{controlRead("House", houseMarket.bounded_market_context_probability)}<br /><span>{controlRead("Senate", senateMarket.bounded_market_context_probability)}</span></h1>
        <p className="desk-deck">A race-by-race forecast combining sourced polling, historical fundamentals, candidate evidence and bounded prediction-market signals. Latest poll: {data.latest_poll_date}.</p>
      </div>
      <aside className="snapshot-panel" aria-label="Forecast data snapshot">
        <p>MODEL SNAPSHOT</p>
        <dl>
          <div><dt>2026-cycle poll records</dt><dd>{data.authenticity.latest_polls}</dd></div>
          <div><dt>Pollster / sponsor labels</dt><dd>{data.authenticity.latest_pollsters}</dd></div>
          <div><dt>Races covered</dt><dd>{totalRaces}</dd></div>
          <div><dt>Correlated simulations</dt><dd>{(data.control.simulations / 1000).toFixed(0)}k</dd></div>
        </dl>
      </aside>
    </section>

    <section className="control-board" id="forecast" aria-label="Forecast overview">
      <div className="board-heading"><div><span>01</span><h2>Balance of power</h2></div><p>Model + bounded market context</p></div>
      <div className="control-list">
        {controlCards.map((card) => <article className="control-row" key={card.label}>
          <div className="control-name"><span>{card.label}</span><small>{card.note}</small></div>
          <div className="control-sides"><span><b>{card.title}</b> {pct(card.value)}</span><span>{pct(1 - card.value)} <b>{card.opponent}</b></span></div>
          <div className="control-track" aria-label={`${card.title} probability ${pct(card.value)}`}><span style={{ width: `${100 * card.value}%` }} /><i style={{ left: `${100 * card.value}%` }} /></div>
          <small>{card.secondary}</small>
        </article>)}
      </div>
      <div className="board-note"><b>How to read it</b><p>Seat distributions use the model simulation; chamber headlines also include bounded market context.{data.control.independent_caucus_sensitivity && ` Senate control is conditional on caucus proxies in ${data.control.independent_caucus_sensitivity.unresolved_states.join(" and ")}; see the independent-seat stress test below.`}</p><a href="#methodology">Methodology →</a></div>
    </section>

    <section className="section-shell race-section" id="races">
      <div className="section-title"><div><p>02 · RACE EXPLORER</p><h2>Every race. One evidence trail.</h2></div><span>{totalRaces} races covered</span></div>
      <div className="race-controls">
        <div className="office-tabs" role="tablist" aria-label="Election office">
          {(Object.keys(officeLabels) as Office[]).map((item) => <button type="button" className={office === item ? "active" : ""} key={item} onClick={() => selectOffice(item)} role="tab" aria-selected={office === item}>{officeLabels[item]} <span>{data.races.filter((race) => race.office === item).length}</span></button>)}
        </div>
        <label className="race-search"><span>Search races</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="State, district or candidate" /></label>
      </div>

      <div className="race-workspace">
        <div className="race-table-wrap" key={`${office}:${query}`}>
          <table className="race-table">
            <thead><tr><th>Race</th><th>Matchup</th><th>Polls</th><th>Model</th><th>Market</th><th>D win</th></tr></thead>
            <tbody>{races.map((race) => <tr key={race.id} className={selectedRace?.id === race.id ? "selected" : ""}>
              <td><button type="button" onClick={() => selectRace(race.id)} aria-label={`Open ${race.location} forecast`}>{race.location}<small>{race.rating ?? "Polled race"}</small></button></td>
              <td><span className="candidate dem">{race.dem_side_party}</span>{race.dem}<br /><span className="candidate rep">R</span>{race.rep}</td>
              <td>{margin(race.poll_margin)}<small>{race.poll_count} polls</small></td>
              <td>{margin(race.model_margin)}<small>{compactModelLabel(race.model)}</small></td>
              <td>{pct(race.market_probability, 0)}<small>{race.market_probability == null ? "No market" : `Weight ${pct(race.market_weight, 0)}`}</small></td>
              <td>{race.probability_event === "pairwise_comparison_only" ? <small>3-way: not modeled</small> : <><ProbabilityLine value={race.dem_probability} />{race.dem_side_party !== "D" && <small>{race.dem_side_party} candidate win</small>}</>}</td>
            </tr>)}</tbody>
          </table>
          {!races.length && <p className="empty-races">No races match that search.</p>}
        </div>

        <aside className="race-inspector" aria-live="polite">
          {selectedRace ? <>
            <div className="inspector-head"><div><p>SELECTED · {selectedRace.office.toUpperCase()}</p><h3>{selectedRace.location}</h3></div><div><strong>{selectedRace.probability_event === "pairwise_comparison_only" ? "—" : pct(selectedRace.dem_probability)}</strong><span>{selectedRace.dem_side_party} win</span></div></div>
            <p className="inspector-matchup"><b>{selectedRace.dem}</b><span>vs.</span><b>{selectedRace.rep}</b></p>
            <dl className="inspector-metrics">
              <div><dt>Raw poll average</dt><dd>{margin(selectedRace.raw_poll_margin)}</dd></div>
              <div><dt>House-effect adjusted</dt><dd>{margin(selectedRace.poll_margin)}</dd></div>
              <div><dt>Model margin</dt><dd>{margin(selectedRace.model_margin)}</dd></div>
              <div><dt>Market</dt><dd>{pct(selectedRace.market_probability)}</dd></div>
            </dl>
            <p className="inspector-note">{selectedRace.poll_count ? `${selectedRace.poll_count} polls with ${selectedRace.pollster_count} reported labels${selectedRace.normalized_pollster_count != null ? ` and ${selectedRace.normalized_pollster_count} conservative organization keys` : ""} feed this matchup. Neither labels nor keys establish independent surveys or panels.` : `No qualifying direct poll snapshot. This race currently uses a provisional ${selectedRace.rating} rating prior.`}</p>
            {selectedRace.poll_house_effect != null && <p className="inspector-note">The adjusted average subtracts an estimated prior-cycle pollster house effect of {selectedRace.poll_house_effect >= 0 ? "+" : ""}{selectedRace.poll_house_effect.toFixed(2)} points from the raw average. This is a model correction, not additional poll evidence.</p>}
            {selectedRace.multi_candidate_warning && <p className="early-flag">{selectedRace.multi_candidate_warning}</p>}
            {selectedRace.district_boundary_changed && <p className="early-flag">Verified boundary change: the old district result is excluded from this forecast. A comparable reconstructed district baseline is not yet available.</p>}
            <div className="poll-ledger"><div className="ledger-head"><span>RECENT POLLS</span><span>Margin · weight</span></div>{selectedEvidence.length ? selectedEvidence.map((poll, index) => <a className="poll-row" href={poll.source_url} target="_blank" rel="noreferrer" key={`${poll.pollster}-${poll.end_date}-${poll.margin}-${index}`}><div><strong>{poll.pollster}</strong><span>{poll.end_date} · {poll.sample_size?.toLocaleString() ?? "?"} {poll.population.toUpperCase()}</span></div><b className={poll.margin >= 0 ? "dem-text" : "rep-text"}>{margin(poll.margin)}</b><em>{pct(poll.normalized_race_weight)}</em></a>) : <p className="no-evidence">No direct poll ledger for this rating-prior race.</p>}</div>
          </> : <p className="no-evidence">Select a race or clear the search to inspect its forecast.</p>}
        </aside>
      </div>
    </section>

    <section className="section-shell distribution-section">
      <div className="section-title compact"><div><p>03 · SIMULATION</p><h2>Where the chamber could land.</h2></div><div className="distribution-tabs">{(["house", "senate"] as const).map((item) => <button type="button" key={item} className={distributionOffice === item ? "active" : ""} onClick={() => setDistributionOffice(item)}>{officeLabels[item]}</button>)}</div></div>
      <div className="distribution-layout">
        <DistributionChart data={data.distributions} office={distributionOffice} />
        <div className="distribution-stats">{distributionOffice === "house" ? <><div><span>Median D seats</span><strong>{data.control.house.median_dem_seats}</strong></div><div><span>90% range</span><strong>{data.control.house.p05_dem_seats}–{data.control.house.p95_dem_seats}</strong></div><div><span>D control</span><strong>{pct(data.control.house.dem_control_probability)}</strong></div></> : <><div><span>Median D-aligned</span><strong>{data.control.senate.median_dem_seats}</strong></div><div><span>90% range</span><strong>{data.control.senate.p05_dem_seats}–{data.control.senate.p95_dem_seats}</strong></div><div><span>D control</span><strong>{pct(data.control.senate.dem_control_probability)}</strong></div></>}</div>
      </div>
    </section>

    {data.early_voting && <EarlyVotingPanel data={data.early_voting} />}
    {data.control.independent_caucus_sensitivity && <aside className="section-shell"><p className="early-flag">Senate control depends on unresolved independent contests in {data.control.independent_caucus_sensitivity.unresolved_states.join(", ")}. The central forecast uses two-side caucus proxies. Assigning all unresolved seats zero or one Democratic-aligned seat gives stress endpoints of {pct(data.control.independent_caucus_sensitivity.dem_control_lower_endpoint)}–{pct(data.control.independent_caucus_sensitivity.dem_control_upper_endpoint)}. These endpoints are not a confidence interval.</p></aside>}

    <section className="method-section" id="methodology">
      <div className="method-intro"><p>04 · METHODOLOGY</p><h2>Uncertainty,<br /><em>made inspectable.</em></h2><span>The model exposes data gaps, rejected adjustments and correlated error instead of hiding them behind one headline number.</span></div>
      <div className="method-grid"><article><span>01</span><h3>Aggregate evidence</h3><p>Polls decay over time and are weighted for sample, likely-voter status, sponsorship, frequency and house effects.</p></article><article><span>02</span><h3>Blend models</h3><p>Polling, Ridge and candidate-aware fundamentals are combined using leakage-resistant historical selection; deep new-matchup polling can retire old ML priors.</p></article><article><span>03</span><h3>Gate adjustments</h3><p>Calibration is accepted only after out-of-period improvement. Market signals remain capped secondary evidence.</p></article><article><span>04</span><h3>Correlate shocks</h3><p>{data.control.simulations.toLocaleString()} draws let national and office-level errors move related races together.</p></article></div>
    </section>

    <section className="section-shell validation-section">
      <div className="section-title compact"><div><p>05 · VALIDATION · {data.validation_horizon} DAYS OUT</p><h2>Earlier cycles choose. Later cycles judge.</h2></div></div>
      <div className="validation-layout">
        <div className="validation-hero"><div><span>Winner accuracy</span><strong>{pct(currentValidation?.winner_accuracy ?? overallBacktest?.accuracy ?? 0)}</strong></div><div><span>Brier score</span><strong>{(currentValidation?.brier ?? overallBacktest?.brier)?.toFixed(3)}</strong></div><div><span>Held-out races</span><strong>{(currentValidation?.races ?? overallBacktest?.races)?.toFixed(0)}</strong></div><div><span>All-office snapshots</span><strong>{data.heldout_forecasts.toLocaleString()}</strong></div></div>
        <div className="model-table">{data.model_selection.filter((row) => row.office !== "generic_ballot").map((row) => <article key={row.office}><span>{row.office.toUpperCase()}</span><div><h3>{modelLabel(row.model)}</h3><p>{row.independent_races} races · {row.validated_horizon}-day Brier {row.brier.toFixed(3)}</p></div></article>)}</div>
      </div>
      <p className="early-caption">Headline validation covers historical House, Senate and governor races at {data.validation_horizon} days using nested earlier-cycle model selection. The {data.heldout_forecasts.toLocaleString()} comparison snapshots span all five horizons and also include presidential and generic-ballot forecasts; they are not {data.heldout_forecasts.toLocaleString()} independent races.</p>
      <p className="early-caption">These scores validate historical polled races—not the full 435-seat House, external rating priors for unpolled districts, or the bounded live-market layer. Single-race accuracy is not chamber-control accuracy.</p>
      {closeValidation && cycleComparison && <details className="early-method"><summary>Stress test · competitive races and shared election errors</summary><p>Among {closeValidation.races} races forecast at 20–80% probability, winner accuracy was {pct(closeValidation.winner_accuracy)}, Brier {closeValidation.brier.toFixed(3)} and mean winner confidence {pct(closeValidation.mean_confidence)}. Safe races make overall accuracy substantially higher.</p><p>On {cycleComparison.common_races} matched races, the selected policy minus a plain weighted-poll baseline had Brier difference {cycleComparison.selected_minus_baseline_brier.toFixed(4)} (negative is better). A whole-election-cycle bootstrap over {cycleComparison.independent_cycle_clusters} clusters gave an exploratory 95% interval of {cycleComparison.exploratory_95pct_cycle_interval.map((value) => value.toFixed(4)).join(" to ")}. This does not establish that the more complex policy is superior.</p></details>}
      {data.research_audit && <details className="early-method"><summary>Research questions · political, statistical and data-science checks</summary>{data.research_audit.questions.map((item) => <p key={item.question}><b>{item.question}</b><br />{item.decision}</p>)}</details>}
      {data.pollster_identity_experiment && <details className="early-method"><summary>Pollster identity · eight-way ablation, no production switch</summary><p>On the same {data.pollster_identity_experiment.baseline.races} historical races, pooling aliases improved some retrospective comparisons. A policy choosing configurations using earlier cycles only had Brier {data.pollster_identity_experiment.outer_policy.brier.toFixed(5)}, versus {data.pollster_identity_experiment.baseline.brier.toFixed(5)} for reported labels. Its exploratory cycle-bootstrap improvement interval crosses zero: {data.pollster_identity_experiment.outer_paired_comparison.exploratory_95pct_cycle_interval.map((value) => value.toFixed(6)).join(" to ")}. Production defaults remain unchanged.</p><div className="early-table-wrap"><table className="early-table"><thead><tr><th>Alias pooling</th><th>Brier ↓</th><th>Winner accuracy</th></tr></thead><tbody>{Object.entries(data.pollster_identity_experiment.ablation).map(([policy, score]) => <tr key={policy}><td>{policy.replaceAll("_", " ").replaceAll("+", " + ")}</td><td>{score.brier.toFixed(5)}</td><td>{pct(score.winner_accuracy)}</td></tr>)}</tbody></table></div><p>Publisher, sponsor, fieldwork organization and sample panel are different roles. Shared organization keys do not establish statistical independence.</p></details>}
      {data.correlation_experiment && <details className="early-method"><summary>Shared election errors · correlated count validation</summary>{data.correlation_experiment.results.filter((row) => row.method === "fixed_rho_0.3").map((row) => <p key={row.office}>{row.office === "senate" ? "Senate" : "Governor"} poll-covered subsets · {row.independent_cycles} held-out cycles · ranked count loss {row.mean_count_rps.toFixed(3)} · observed 90% interval coverage {pct(row.interval_coverage)}. The fixed within-office correlation remains 0.30; this small sample does not establish full-chamber calibration.</p>)}<p>{data.correlation_experiment.scope}</p></details>}
      {data.house_control_validation && <details className="early-method"><summary>House-control validation has few independent elections</summary>{data.house_control_validation.results.filter((row) => row.method === "production_modern_2012").map((row) => <p key={row.method}>The production-style national seats–votes curve has {row.independent_cycles} fully held-out cycles · Brier {row.brier.toFixed(3)} · seat MAE {row.seat_mae.toFixed(1)}. This sample is too small to establish robust control-probability calibration.</p>)}<p>{data.house_control_validation.scope}</p></details>}
      {data.recency_experiment && <details className="early-method"><summary>Recency sensitivity · 30-day half-life retained</summary><p>Decay settings were compared on the same historical races. An outer selection rule could change settings using earlier cycles only, and required at least 0.002 Brier improvement before switching. It retained 30 days.</p>{data.recency_experiment.challengers.map((row) => <p key={row.half_life_days}>{row.half_life_days}-day half-life · {row.races} races · Brier {row.brier.toFixed(4)} · winner accuracy {pct(row.accuracy)}</p>)}<p>These are research comparisons, not measured 2026 accuracy.</p></details>}
      {data.publication_lag_experiment && <details className="early-method"><summary>Historical release-time sensitivity</summary><p>Fieldwork end dates are not necessarily publication dates. On the same {data.publication_lag_experiment.baseline_common_races.races} races, adding a conservative three-day availability delay changed Brier from {data.publication_lag_experiment.baseline_common_races.brier.toFixed(4)} to {data.publication_lag_experiment.delayed_common_races.brier.toFixed(4)}. Missing or revised release timestamps remain a validation limit.</p><p>{data.publication_lag_experiment.scope}</p></details>}
    </section>

    <section className="source-section">
      <div className="source-copy"><p>06 · DATA PROVENANCE</p><h2>{data.authenticity.latest_polls} cycle poll records.<br /><em>{data.authenticity.hashes_verified} hash-checked snapshots.</em></h2><p>{data.active_poll_count} eligible polls support the central matchups within the 120-day window. Original links and audit flags are retained. Hash checks verify file integrity.</p>{data.source_link_check && <p>{data.source_link_check.reachable}/{data.source_link_check.sample_size} sampled original-source links were reachable. Availability alone does not authenticate a poll.</p>}</div>
      <div className="source-audit"><div><span>Authenticity audit</span><strong>{data.authenticity.verdict.replaceAll("_", " ")}</strong></div><div><span>Pollster / sponsor labels</span><strong>{data.authenticity.latest_pollsters}</strong></div><div><span>FEC candidate matches</span><strong>{data.authenticity.fec_matches}/{data.authenticity.fec_checked}</strong></div><div><span>Review flags</span><strong>{data.authenticity.issue_count}</strong></div></div>
      {data.collection && <details className="early-method"><summary>Acquisition freshness · cache is not a live update</summary><p>{data.collection.request_status_counts.network ?? 0} network responses · {data.collection.request_status_counts.cache ?? 0} cache reads · {data.collection.request_status_counts.failed ?? 0} failed requests. Failed map discovery may use verified cached page links; failures do not automatically mean missing polls.</p><p>Acquisition checked: {observationTime(data.collection.checked_at)}. Source observations: {observationTime(data.collection.oldest_observed_at)} to {observationTime(data.collection.latest_observed_at)}. The site is a published snapshot, not an automatically streaming feed.</p><p>{data.collection.scope}</p></details>}
      <p className="early-caption">{data.authenticity.fec_name_review_flags} candidate names need filing-identity review, including unresolved nicknames or middle names. Same-surname predecessors are not accepted as the same person. {data.authenticity.fec_match_note}</p>
      <div className="domain-list">{data.authenticity.top_source_domains.map(([domain, count]) => <span key={domain}>{domain} <b>{count}</b></span>)}</div>
    </section>

    <footer><a className="forecast-brand" href="#top"><span>EF</span><strong>Election Forecast Lab</strong></a><p>Research forecast · Not a polling firm or betting recommendation</p><a href="#top">Back to top ↑</a></footer>
  </main>;
}
