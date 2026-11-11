export type ResultsRace = {
  race: string;
  office: string;
  dem: string;
  rep: string;
  dem_side_party: string;
  forecast_dem_probability: number | null;
  winner: string | null;
  forecast_source: string;
  status?: string;
  leader?: string;
};

type Score = { races: number; winner_accuracy: number | null; brier: number | null };

export type ResultsData = {
  compiled_at: string;
  frozen_release: string;
  frozen_at: string;
  scores_as_of: string;
  status_counts: Record<string, number>;
  chambers: {
    office: string;
    seats: number;
    majority: number | null;
    forecast: { median: number; mean: number; p05: number; p95: number; dem_control_probability: number | null };
    result: { control: string | null; dem_low: number; dem_high: number; summary: string; within_90: "inside" | "above" | "partly_outside" };
  }[];
  national_vote: { forecast_dem_margin: number; observed_dem_margin: number; observed_range: [number, number]; basis: string };
  flips: { senate_to_dem: string[]; governor_to_dem: string[] };
  race_scores: { overall: Score; poll_model: Score; rating_prior: Score; by_office: Record<"senate" | "governor" | "house", Score> };
  misses: ResultsRace[];
  pending: ResultsRace[];
  pending_notes: string[];
  turnout_note: string;
  sources: { name: string; url: string }[];
  scope: string;
};

const RETROSPECTIVE_URL = "https://github.com/MachineWJQ6657/election-lab/blob/main/docs/2026_retrospective.md";
const pct = (value: number | null, digits = 1) => value == null ? "—" : `${(100 * value).toFixed(digits)}%`;
const verdict = { inside: "Inside the 90% range", above: "Above the 90% range", partly_outside: "Partly outside the 90% range" };

function IntervalBar({ chamber }: { chamber: ResultsData["chambers"][number] }) {
  const { forecast, result, majority } = chamber;
  const lo = Math.min(forecast.p05, result.dem_low) - 4;
  const hi = Math.max(forecast.p95, result.dem_high) + 4;
  const x = (value: number) => `${(100 * (value - lo)) / (hi - lo)}%`;
  const resultLabel = result.dem_low === result.dem_high ? `${result.dem_low}` : `${result.dem_low}–${result.dem_high}`;
  return <div className="result-scale" role="img" aria-label={`${chamber.office}: forecast median ${forecast.median} Democratic seats, 90% range ${forecast.p05} to ${forecast.p95}; result ${resultLabel}. ${verdict[result.within_90]}.`}>
    <span className="result-band" style={{ left: x(forecast.p05), width: `calc(${x(forecast.p95)} - ${x(forecast.p05)})` }} />
    <i className="result-median" style={{ left: x(forecast.median) }} />
    {majority != null && <i className="result-majority" style={{ left: x(majority) }} title={`Majority: ${majority}`} />}
    <b className={`result-actual ${result.within_90}`} style={{ left: x(result.dem_low), width: `max(6px, calc(${x(result.dem_high)} - ${x(result.dem_low)}))` }} />
    <small style={{ left: x(forecast.p05) }}>{forecast.p05}</small>
    <small style={{ left: x(forecast.p95) }}>{forecast.p95}</small>
  </div>;
}

function RaceList({ races, kind }: { races: ResultsRace[]; kind: "miss" | "pending" }) {
  return <ul className="result-races">
    {races.map((race) => <li key={race.race}>
      <div><strong>{race.race}</strong><span>{race.forecast_source}</span></div>
      <p>{kind === "miss" ? <>Won by <b className="dem-text">{race.winner}</b> ({race.dem_side_party}); forecast gave {pct(race.forecast_dem_probability)}</> : <><b>{race.leader}</b> leads; forecast gave the D side {pct(race.forecast_dem_probability)}. <span>{race.status}</span></>}</p>
    </li>)}
  </ul>;
}

export function ResultsReview({ data }: { data: ResultsData }) {
  const scores = data.race_scores;
  const scoreRows: [string, Score][] = [
    ["All called races", scores.overall],
    ["Poll model", scores.poll_model],
    ["Rating prior (unpolled)", scores.rating_prior],
    ["Senate", scores.by_office.senate],
    ["Governor", scores.by_office.governor],
    ["House (NC/TX only)", scores.by_office.house],
  ];
  const gap = data.national_vote.observed_dem_margin - data.national_vote.forecast_dem_margin;
  return <section className="section-shell results-section" id="results" data-results-compiled={data.compiled_at}>
    <div className="section-title"><div><p>00 · RESULTS VS. FROZEN FORECAST</p><h2>Right direction.<br /><em>The wave was bigger than forecast.</em></h2></div><span>Media calls compiled {data.compiled_at}</span></div>

    <div className="result-chambers">
      {data.chambers.map((chamber) => <article key={chamber.office} data-result-office={chamber.office.toLowerCase()} data-within-90={chamber.result.within_90}>
        <header><span>{chamber.office.toUpperCase()}{chamber.office === "Governors" ? " · 36 RACES" : ""}</span>{chamber.result.control && <b className="result-control">D control ✓</b>}</header>
        <div className="result-numbers">
          <div><small>Forecast median</small><strong>{chamber.forecast.median}</strong></div>
          <div><small>Result (D)</small><strong className="dem-text">{chamber.result.dem_low === chamber.result.dem_high ? chamber.result.dem_low : `${chamber.result.dem_low}–${chamber.result.dem_high}`}</strong></div>
        </div>
        <IntervalBar chamber={chamber} />
        <p className={`result-verdict ${chamber.result.within_90}`}>{verdict[chamber.result.within_90]}</p>
        <p className="result-summary">{chamber.result.summary}.{chamber.forecast.dem_control_probability != null && ` Forecast gave Democrats ${pct(chamber.forecast.dem_control_probability)} to win control.`}</p>
      </article>)}
      <article data-result-office="national-vote">
        <header><span>NATIONAL HOUSE VOTE</span></header>
        <div className="result-numbers">
          <div><small>Forecast</small><strong>D+{data.national_vote.forecast_dem_margin.toFixed(1)}</strong></div>
          <div><small>Observed</small><strong className="dem-text">D+{data.national_vote.observed_dem_margin.toFixed(1)}</strong></div>
        </div>
        <p className="result-verdict above">Environment missed by ~{gap.toFixed(0)} points</p>
        <p className="result-summary">{data.national_vote.basis}</p>
      </article>
    </div>
    <p className="result-legend"><span className="key band" /> Forecast 90% range <span className="key median" /> Forecast median <span className="key majority" /> Majority line <span className="key actual" /> Result (called + leading / projected)</p>

    <div className="result-grid">
      <div>
        <h3>Race-level scores on called contests</h3>
        <table className="early-table result-table">
          <thead><tr><th>Scope</th><th>Races</th><th>Winner accuracy</th><th>Brier ↓</th></tr></thead>
          <tbody>{scoreRows.map(([label, score]) => <tr key={label}><td>{label}</td><td>{score.races}</td><td>{pct(score.winner_accuracy)}</td><td>{score.brier?.toFixed(3) ?? "—"}</td></tr>)}</tbody>
        </table>
        <p className="early-caption">Frozen {data.frozen_release} probabilities scored against {data.status_counts.called} called contests retrieved through {data.scores_as_of.slice(0, 10)}. Historical backtest Brier was 0.105–0.116. Calls are media projections, not certified results; {data.status_counts.unresolved} contests were not yet imported.</p>
      </div>
      <div>
        <h3>Every miss went the same way</h3>
        <RaceList races={data.misses} kind="miss" />
        <p className="early-caption">{data.misses.filter((race) => (race.forecast_dem_probability ?? 0.5) < 0.5).length} of {data.misses.length} wrong calls were Republican favorites that lost. That pattern points to a shared national error, not independent bad luck.</p>
      </div>
    </div>

    <div className="result-grid">
      <div>
        <h3>Still counting</h3>
        <RaceList races={data.pending} kind="pending" />
        <ul className="result-notes">{data.pending_notes.map((note) => <li key={note}>{note}</li>)}</ul>
      </div>
      <div>
        <h3>What we learned</h3>
        <ol className="result-lessons">
          <li><b>The national environment was underestimated.</b> The generic-ballot projection (D+{data.national_vote.forecast_dem_margin.toFixed(1)}) was shrunk toward a prior; the realized vote was about D+{data.national_vote.observed_dem_margin.toFixed(0)}. That one error explains the House seat miss.</li>
          <li><b>Correlation was too weak.</b> Every miss leaned the same way. A 0.18 national correlation understated how much races move together in a wave.</li>
          <li><b>Unpolled rating priors were overconfident.</b> Districts priced at 2% Democratic flipped. Priors need fatter tails tied to the national environment.</li>
          <li><b>Markets were closer on the House.</b> Their 94% consensus beat the model’s 79%. The capped market layer was a reasonable guardrail, not an error.</li>
        </ol>
        <p className="early-caption"><a href={RETROSPECTIVE_URL} target="_blank" rel="noreferrer">Full retrospective and 2028 outlook (Chinese) →</a></p>
      </div>
    </div>

    <details className="early-method"><summary>Sources and limits of this comparison</summary>
      <p>{data.scope}</p>
      <p>{data.turnout_note}</p>
      <p>{data.sources.map((source) => <a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.name}</a>)}</p>
    </details>
  </section>;
}
