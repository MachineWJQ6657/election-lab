import { seatComparison, seatRatingSummary, type MapOffice, type MapSeatControl, type MapRace } from "../lib/election-map";

export function MapSeatSummary({ races, office, control, unresolvedStates }: { races: MapRace[]; office: MapOffice; control: MapSeatControl; unresolvedStates: string[] }) {
  const s = seatComparison(control, office);
  const ratings = seatRatingSummary(races, control, office);
  const demLabel = office === "senate" ? "Democratic-aligned" : "Democratic";
  const repLabel = office === "senate" ? "Republican-aligned" : "Republican";
  const officeLabel = office === "house" ? "House" : office === "senate" ? "Senate" : "Governor";
  return <div className="map-final-seats" role="region" aria-label={`Projected ${office === "governor" ? "2026 Governor wins" : `final ${officeLabel} seats`}`}
    data-seat-summary={office} data-total-seats={s.total} data-dem-seats={s.dem} data-rep-seats={s.rep}>
    <div className="map-final-heading"><span>{office === "governor" ? "PROJECTED 2026 GOVERNOR WINS" : `PROJECTED FINAL ${officeLabel.toUpperCase()} SEATS`}</span><small>Simulation median · {s.total} {office === "governor" ? "races" : "seats"}</small></div>
    <div className="map-final-comparison">
      <div className="map-final-dem"><span>{demLabel}</span><strong>{s.dem}</strong></div>
      <span className="map-final-versus">vs</span>
      <div className="map-final-rep"><span>{repLabel}</span><strong>{s.rep}</strong></div>
    </div>
    <div className="map-final-bar map-rating-bar" role="group" aria-label="Seats by map rating, not simulation median" data-rated-total={ratings.total} data-rated-dem={ratings.dem} data-rated-rep={ratings.rep}>
      {ratings.segments.map((segment) => <span key={segment.key} className={`map-rating-segment${"holdover" in segment ? " holdover" : ""}`}
        style={{ width: `${100 * segment.count / ratings.total}%`, backgroundColor: segment.color }} data-seat-band={segment.key} data-seat-count={segment.count}
        title={`${segment.label}: ${segment.count} seats`} aria-label={`${segment.label}: ${segment.count} seats`}>{segment.count / ratings.total >= .035 ? segment.count : ""}</span>)}
      {s.threshold != null && <i title={`${s.threshold} seats for D control`} style={{ left: `${100 * s.threshold / s.total}%` }} />}
    </div>
    <div className="map-final-caption"><span>Map ratings: D {ratings.dem} / R {ratings.rep}{ratings.tossup > 0 ? ` / Toss-up ${ratings.tossup}` : ""}{ratings.independent > 0 ? ` / I ${ratings.independent}` : ""}{ratings.unmodeled > 0 ? ` / Not modeled ${ratings.unmodeled}` : ""}</span><span>{s.threshold == null ? "2026 races only" : `${s.threshold} for D control`} · not simulation totals</span></div>
    <div className="map-legend map-ratings-key" aria-label="Win probability legend">
      {ratings.bands.map((b) => <span key={b.key} title={`${b.label}: ${b.count} contests; favored candidate win probability ${b.probability}`}><i style={{ background: b.color }} />{b.label}<b>{b.count}</b></span>)}
      {ratings.nonUpDem + ratings.nonUpRep > 0 && <span className="map-holdover-key">Not up: D {ratings.nonUpDem} · R {ratings.nonUpRep}</span>}
    </div>
    <details className="map-forecast-details"><summary>Forecast details &amp; rating definitions</summary>
    <div className="map-final-stats">
      <div><span>Expected seats{office === "governor" ? " won" : ""}</span><b><em className="dem-text">D {s.expectedDem.toFixed(1)}</em><i> / </i><em className="rep-text">R {s.expectedRep.toFixed(1)}</em></b></div>
      <div><span>90% seat range</span><b>D {s.demLow}–{s.demHigh}<i> / </i>R {s.repLow}–{s.repHigh}</b></div>
      {s.controlProbability != null && <div><span>Model control odds</span><b><em className="dem-text">D {(100 * s.controlProbability).toFixed(1)}%</em><i> / </i><em className="rep-text">R {(100 * (1 - s.controlProbability)).toFixed(1)}%</em></b></div>}
    </div>
    <p className="map-final-note">{office === "senate" ? <>Includes all {s.nonUpTotal} seats not up: {s.nonUpDem} D-aligned + {s.nonUpRep} R-aligned. {unresolvedStates.length > 0 && <>Uses the simulation’s caucus proxies for {unresolvedStates.join(" / ")}; independent wins are not automatically Democratic seats. </>}A 50–50 split is treated as R control in this simulation.</> : office === "house" ? "All 435 House seats. Counts come from the chamber simulation, not the sum of favored categories below." : "Only the governorships holding elections in this snapshot are included; non-election states are excluded."} The two ranges describe the same complementary seat distribution, not independent outcomes.</p>
    <p className="map-final-note">The large numbers are simulation medians. The segmented bar counts map ratings, not expected seats or simulated totals. Hatched party segments are seats not up, not Solid forecasts. Our model scale: Solid (Safe) ≥95%; Likely 80–&lt;95%; Lean 60–&lt;80%; Tilt &gt;50–&lt;60%; Toss-up exactly 50/50. These are favored-candidate probabilities, not vote margins or imported expert ratings. Ratings use unrounded probabilities, so a displayed 50.0% can still be Tilt. Solid is not a guarantee.</p>
    </details>
  </div>;
}
