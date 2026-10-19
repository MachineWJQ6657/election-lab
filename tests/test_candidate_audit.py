import pandas as pd

from election_forecast.audit import audit_fec_candidates


def test_fec_match_does_not_return_same_surname_predecessor_as_current_candidate():
    catalog = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "SC",
                "dem_candidate": "Democratic nominee TBD",
                "rep_candidate": "Darline Graham",
            }
        ]
    )
    fec = pd.DataFrame(
        [
            {
                "office_name": "senate",
                "location": "SC",
                "party": "REP",
                "candidate_id": candidate_id,
                "candidate_name": name,
            }
            for candidate_id, name in [
                ("CURRENT", "GRAHAM, DARLINE"),
                ("PREDECESSOR", "GRAHAM, LINDSEY O."),
            ]
        ]
    )
    result = audit_fec_candidates(catalog, fec).iloc[0]
    assert result.fec_match
    assert result.fec_candidate_ids == "CURRENT"
    assert set(result.surname_candidate_ids_for_review.split(",")) == {"CURRENT", "PREDECESSOR"}
