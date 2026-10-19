"""Expose when a two-side forecast cannot represent a full candidate contest."""

import json

import pandas as pd

from .names import COMPATIBLE_NAME_MATCHES, candidate_key, candidate_name_match


def _surname(value: object) -> str:
    return candidate_key(value)


def annotate_contest_scope(
    forecast: pd.DataFrame, catalog: pd.DataFrame, raw_polls: pd.DataFrame
) -> pd.DataFrame:
    frame = forecast.copy()
    frame["dem_side_party"] = "D"
    frame["multi_candidate_warning"] = ""
    frame["unresolved_independent_seat"] = False
    frame["probability_event"] = "candidate_win"
    frame["catalog_candidate_match"] = False
    for index, row in frame.iterrows():
        entry = catalog[(catalog.office == row.office) & (catalog.location == row.location)]
        if not entry.empty and {"dem_candidate", "rep_candidate"}.issubset(entry):
            named_dem = candidate_key(entry.iloc[0]["dem_candidate"])
            named_rep = candidate_key(entry.iloc[0]["rep_candidate"])
            frame.loc[index, "catalog_candidate_match"] = bool(
                named_dem
                and named_rep
                and candidate_name_match(row.dem_candidate, entry.iloc[0]["dem_candidate"])
                in COMPATIBLE_NAME_MATCHES
                and candidate_name_match(row.rep_candidate, entry.iloc[0]["rep_candidate"])
                in COMPATIBLE_NAME_MATCHES
            )
        if not entry.empty and "nominees_json" in entry:
            for candidate in json.loads(entry.iloc[0]["nominees_json"] or "[]"):
                if (
                    not candidate.get("w")
                    and candidate_name_match(row.dem_candidate, candidate.get("n"))
                    in COMPATIBLE_NAME_MATCHES
                ):
                    frame.loc[index, "dem_side_party"] = candidate.get("p", "D")
        polls = raw_polls[(raw_polls.office == row.office) & (raw_polls.location == row.location)]
        if not polls.empty and "ind_pct" in polls:
            cutoff = pd.Timestamp(row.as_of_date)
            dates = pd.to_datetime(polls.end_date)
            relevant = polls[(dates <= cutoff) & (dates >= cutoff - pd.Timedelta(days=120))]
            relevant = relevant[pd.to_numeric(relevant.ind_pct, errors="coerce").ge(10)]
            if not relevant.empty:
                names = ", ".join(sorted(relevant.ind_candidate.dropna().unique()))
                frame.loc[index, "multi_candidate_warning"] = (
                    f"Competitive independent candidate(s): {names}. The two-side model does "
                    "not estimate the full three-way winner probability."
                )
                frame.loc[index, "probability_event"] = "pairwise_comparison_only"
                frame.loc[index, "unresolved_independent_seat"] = row.office == "senate"
        if frame.loc[index, "dem_side_party"] == "I":
            frame.loc[index, "unresolved_independent_seat"] = row.office == "senate"
            frame.loc[index, "multi_candidate_warning"] = (
                "The opposition candidate is independent. Candidate win probability does "
                "not establish Senate caucus affiliation; central control uses an aligned proxy."
            )
    return frame
