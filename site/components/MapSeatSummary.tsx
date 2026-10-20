import { seatComparison, type MapOffice, type MapSeatControl } from "../lib/election-map";

export function MapSeatSummary({ office, control, unresolvedStates }: { office: MapOffice; control: MapSeatControl; unresolvedStates: string[] }) {
  const s = seatComparison(control, office);
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
    <div className="map-final-bar" role="img" aria-label={`${demLabel} ${s.dem}, ${repLabel} ${s.rep}${s.threshold != null ? `; ${s.threshold} seats for Democratic control` : ""}`}>
      <span className="map-final-bar-dem" style={{ width: `${100 * s.dem / s.total}%` }} />
      {s.threshold != null && <i style={{ left: `${100 * s.threshold / s.total}%` }} />}
    </div>
    <div className="map-final-caption"><span>{s.threshold == null ? "2026 races only · not all 50 governorships" : `${s.threshold} seats for ${office === "senate" ? "D-aligned" : "Democratic"} control`}</span><span>Projected, not decided</span></div>
    <div className="map-final-stats">
      <div><span>Expected seats{office === "governor" ? " won" : ""}</span><b><em className="dem-text">D {s.expectedDem.toFixed(1)}</em><i> / </i><em className="rep-text">R {s.expectedRep.toFixed(1)}</em></b></div>
      <div><span>90% seat range</span><b>D {s.demLow}–{s.demHigh}<i> / </i>R {s.repLow}–{s.repHigh}</b></div>
      {s.controlProbability != null && <div><span>Model control odds</span><b><em className="dem-text">D {(100 * s.controlProbability).toFixed(1)}%</em><i> / </i><em className="rep-text">R {(100 * (1 - s.controlProbability)).toFixed(1)}%</em></b></div>}
    </div>
    <p className="map-final-note">{office === "senate" ? <>Includes all {s.nonUpTotal} seats not up: {s.nonUpDem} D-aligned + {s.nonUpRep} R-aligned. {unresolvedStates.length > 0 && <>Uses the simulation’s caucus proxies for {unresolvedStates.join(" / ")}; independent wins are not automatically Democratic seats. </>}A 50–50 split is treated as R control in this simulation.</> : office === "house" ? "All 435 House seats. Counts come from the chamber simulation, not the sum of favored categories below." : "Only the governorships holding elections in this snapshot are included; non-election states are excluded."} The two ranges describe the same complementary seat distribution, not independent outcomes.</p>
  </div>;
}
