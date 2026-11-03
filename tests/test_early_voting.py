import json
from datetime import date

import httpx
import pandas as pd
import pytest

from election_forecast.sources.early_voting import (
    discover_sc_turnout,
    election_day,
    observation_day,
    parse_civic,
    parse_florida,
    parse_nc_counts,
    parse_sc_turnout,
    read_capabilities,
    reconcile_demographics,
)


def test_observation_day_does_not_treat_utc_midnight_as_tomorrow_in_new_york():
    assert observation_day("2026-10-20T00:30:00+00:00") == date(2026, 10, 19)
    with pytest.raises(ValueError, match="timezone"):
        observation_day("2026-10-19T12:00:00")


def test_capability_fallback_uses_only_verified_discovery_not_old_ballot_totals():
    class Client:
        def get(self, url, **kwargs):
            response = httpx.Response(503, request=httpx.Request("GET", url))
            response.raise_for_status()

        def get_cached(self, url):
            return b'{"categories":{"returned":{"race":true}}}'

    data, fallback = read_capabilities(Client(), "https://example.test/capabilities", refresh=True)
    assert fallback and data["categories"]["returned"]["race"]
    assert "total" not in data


def test_north_carolina_grid_is_not_counted_again_for_each_demographic():
    payload = (
        b"abs_request_type,party_cd,gender,race,ethnicity,0\n"
        b"CIVILIAN,DEM,FEMALE,BLACK,UNDESIGNATED,10\n"
        b"CIVILIAN,REP,MALE,WHITE,HISPANIC,5\n"
        b"EARLY VOTING,UNA,FEMALE,WHITE,UNDESIGNATED,20\n"
        b"MILITARY,DEM,MALE,WHITE,UNDESIGNATED,2\n"
    )
    counts, demographics = parse_nc_counts(payload, as_of=date(2026, 10, 19))
    frame = pd.DataFrame(counts)
    assert frame.groupby("category")["count"].sum().to_dict() == {"returned": 17, "inperson": 20}
    demo = pd.DataFrame(demographics)
    assert demo.groupby("dimension")["count"].sum().to_dict() == {
        "race": 37,
        "ethnicity": 37,
        "gender": 37,
    }


@pytest.mark.parametrize(
    "count,snapshot", [(-1, "2026-10-19"), (1.5, "2026-10-19"), (10, "2026-10-20")]
)
def test_reject_invalid_or_future_early_vote_observations(count, snapshot):
    payload = json.dumps(
        {
            "category": "returned",
            "snapshot_date": snapshot,
            "regions": {"NC": {"Unspecified": {"votes": count}}},
        }
    ).encode()
    with pytest.raises(ValueError):
        parse_civic(
            payload, category="returned", as_of=date(2026, 10, 19), url="https://example.org"
        )


def test_unspecified_party_is_not_reclassified_as_unaffiliated():
    payload = json.dumps(
        {
            "category": "returned",
            "snapshot_date": "2026-10-19",
            "regions": {"GA": {"Unspecified": {"votes": 100}}},
        }
    ).encode()
    rows = parse_civic(
        payload, category="returned", as_of=date(2026, 10, 19), url="https://example.org"
    )
    assert rows[0]["party"] == "Unspecified"


def test_historical_days_out_alignment_uses_correct_election_day():
    assert election_day(2026) == date(2026, 11, 3)
    assert election_day(2022) == date(2022, 11, 8)
    assert election_day(2024) == date(2024, 11, 5)


def test_florida_issued_includes_outstanding_but_cast_total_does_not():
    table = """2026 General Election Date - 11/03/2026
    <table><tr><th>Stats Type</th><th>Republican</th><th>Democrat</th><th>Other</th>
    <th>No Party Affiliation</th><th>Total</th><th>Compiled</th></tr>
    <tr><td>Vote-by-Mail Provided (Not Yet Returned)</td><td>10</td><td>20</td><td>1</td>
    <td>4</td><td>35</td><td>10/19/2026 11:01AM</td></tr>
    <tr><td>Voted Vote-by-Mail</td><td>20</td><td>30</td><td>2</td><td>8</td>
    <td>60</td><td>10/19/2026 11:01AM</td></tr>
    <tr><td>Voted Early</td><td>0</td><td>0</td><td>0</td><td>0</td>
    <td>0</td><td>10/19/2026 11:01AM</td></tr></table>"""
    frame = pd.DataFrame(parse_florida(table.encode(), as_of=date(2026, 10, 19)))
    assert frame.groupby("category")["count"].sum().to_dict() == {
        "returned": 60,
        "inperson": 0,
        "outstanding": 35,
        "requested": 95,
    }


def test_demographic_gaps_stay_unknown_instead_of_renormalizing_known_groups():
    values, gap = reconcile_demographics({"Group A": 60, "Group B": 30}, 90, 100)
    assert sum(values.values()) == 100 and gap == 10
    assert values["Not reported / reporting gap"] == 10
    with pytest.raises(ValueError):
        reconcile_demographics({"Group A": 101}, 101, 100)


def _sc_report():
    return "\n".join(
        [
            "Election Date,Report Date,,,",
            "11/03/2026,10/23/2026,,,",
            "Jurisdiction,Election Name,Poll Place,10/26/2026,Total",
            "South Carolina,,,46,46",
            *[f"County {i},Statewide General Election,,1,1" for i in range(46)],
            ",,Precinct subtotal must not be added,999,999",
            ",,,,",
            ",,,294226,",
        ]
    ).encode()


def test_sc_uses_reconciled_county_level_and_actual_daily_column_date():
    rows = parse_sc_turnout(
        _sc_report(), as_of=date(2026, 10, 27), url="https://scvotes.gov/test.csv"
    )
    assert len(rows) == 1 and rows[0]["count"] == 46
    assert rows[0]["snapshot_date"] == "2026-10-26"
    assert rows[0]["party"] == "Unspecified"
    assert "2026-10-23" in rows[0]["date_basis"]


def test_sc_accepts_only_empty_trailing_spreadsheet_columns():
    padded = b"\n".join(line + b",, " for line in _sc_report().splitlines())
    rows = parse_sc_turnout(padded, as_of=date(2026, 10, 27), url="https://scvotes.gov/test.csv")
    assert rows[0]["count"] == 46


@pytest.mark.parametrize(
    "before,after",
    [
        (b"11/03/2026", b"06/09/2026"),
        (b"10/26/2026", b"10/28/2026"),
        (b"South Carolina,,,46,46", b"South Carolina,,,47,47"),
        (b"County 45,", b"County 44,"),
    ],
)
def test_sc_rejects_wrong_election_future_dates_and_nonreconciling_counties(before, after):
    with pytest.raises(ValueError):
        parse_sc_turnout(
            _sc_report().replace(before, after),
            as_of=date(2026, 10, 27),
            url="https://scvotes.gov/test.csv",
        )


def test_sc_discovers_only_the_unambiguous_official_csv_link():
    page = b'<a href="/uploads/ev.csv">Early Voting Turnout Report</a>'
    assert discover_sc_turnout(page) == "https://scvotes.gov/uploads/ev.csv"
    for changed in [
        page.replace(b"/uploads/ev.csv", b"https://other.test/ev.csv"),
        page + page.replace(b"ev.csv", b"other.csv"),
        b"",
    ]:
        with pytest.raises(ValueError):
            discover_sc_turnout(changed)
