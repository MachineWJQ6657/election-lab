from datetime import UTC, date, datetime

import pandas as pd

from election_forecast.cli import _exclude_non_model_polls
from election_forecast.schemas import Office
from election_forecast.sources.decision_labs import _public_source_url
from election_forecast.sources.fte_archive import _location
from election_forecast.sources.merge import merge_current_polls
from election_forecast.sources.polling_source import (
    _candidate_cell,
    _extract_javascript_json,
    _find_poll_table,
    _party_candidate,
    _sample_cell,
    fetch_polling_source,
)
from election_forecast.sources.reference_results import (
    _house_2024_major_party_margin,
    _normalize_house_party_divisions,
    _result_location,
)
from election_forecast.sources.silver_generic import fetch_silver_generic_ballot
from election_forecast.sources.two_seventy import _clean_source_url, _map_pages, _parse_page


def test_polling_source_table_parser():
    html = b"""
    <html><head><title>fixture</title></head><body>
      <table>
        <thead><tr><th>State</th><th>Pollster</th><th>Date</th><th>Sample</th><th>Dem</th><th>Rep</th></tr></thead>
        <tbody><tr><td>PA</td><td>Example</td><td>2026-08-01</td><td>800 LV</td>
        <td>Jane Doe 49.0%</td><td>John Roe 47.0%</td></tr></tbody>
      </table>
    </body></html>
    """
    table = _find_poll_table(html)
    assert table.iloc[0]["location"] == "PA"
    assert _candidate_cell(table.iloc[0]["dem"]) == ("Jane Doe", 49.0)
    assert _sample_cell(table.iloc[0]["sample"])[0] == 800


def test_adapter_keeps_independent_firms_with_identical_scores_and_third_candidate():
    html = b"""<table><tr><th>State</th><th>Pollster</th><th>Date</th>
    <th>Sample</th><th>Dem</th><th>Ind</th><th>Rep</th></tr>
    <tr><td>MT</td><td>Emerson</td><td>
    <a href="https://pollster.example/release">2026-10-18</a></td><td>800 LV</td>
    <td>Jane 20%</td><td>Alex 35%</td><td>John 40%</td></tr>
    <tr><td>MT</td><td>Siena</td><td>2026-10-18</td><td>800 LV</td>
    <td>Jane 20%</td><td>Alex 35%</td><td>John 40%</td></tr></table>"""

    class Client:
        def get(self, url, **kwargs):
            return html

    result = fetch_polling_source(Office.SENATE, client=Client())
    assert len(result) == 2
    assert set(result["pollster"]) == {"Emerson", "Siena"}
    assert result["ind_pct"].tolist() == [35, 35]
    assert result.loc[result.pollster.eq("Emerson"), "source_url"].iloc[0] == (
        "https://pollster.example/release"
    )
    assert (
        result.loc[result.pollster.eq("Siena"), "source_url"]
        .iloc[0]
        .startswith("https://pollingsource.com")
    )


def test_decision_labs_source_url_normalizes_malformed_provider_links():
    assert _public_source_url("file:///C:/Users/example/topline.pdf").startswith(
        "https://decisionlabs.ai/"
    )
    assert (
        _public_source_url("https://www.270towin.com\\t\\thttps://unf.example/topline.pdf")
        == "https://unf.example/topline.pdf"
    )


def test_schema_enums_are_stable():
    assert Office.SENATE.value == "senate"
    assert date(2026, 11, 3).isoformat() == "2026-11-03"


def test_archive_location_normalization():
    assert _location("Pennsylvania", "senate", None) == "PA"
    assert _location("Pennsylvania", "house", 7) == "PA-07"
    assert _location(float("nan"), "president", None) == "US"
    assert _result_location(pd.Series({"state_abbrev": "M1"}), "president") == "ME-01"


def test_javascript_catalog_parser_and_candidate_selection():
    payload = (
        b'<script>const districtInfo = {"PA-07":{"party":"d","name":"Jane Doe",'
        b'"rating":"Lean D","nom":[{"p":"D","n":"Jane Doe","i":true},'
        b'{"p":"R","n":"John Roe","i":false}]}};</script>'
    )
    data = _extract_javascript_json(payload, "districtInfo")
    assert list(data) == ["PA-07"]
    assert _party_candidate(data["PA-07"], "D") == "Jane Doe"
    assert _party_candidate(data["PA-07"], "R") == "John Roe"


def test_candidate_fallback_is_explicit():
    info = {"party": "r", "name": "Incumbent", "rating": "Safe R"}
    assert _party_candidate(info, "R") == "Incumbent"
    assert _party_candidate(info, "D") == "Democratic nominee TBD"


def test_candidate_fallback_never_copies_an_opposing_nominee():
    info = {
        "incumbent_party": "R",
        "incumbent": "Jane Democrat",
        "nominees": [{"p": "D", "n": "Jane Democrat"}],
    }
    assert _party_candidate(info, "D") == "Jane Democrat"
    assert _party_candidate(info, "R") == "Republican nominee TBD"


def test_generic_ballot_candidate_labels_are_not_candidate_names():
    assert _candidate_cell("Democrats 49%") == ("Democrats", 49.0)
    assert _candidate_cell("Kathy Hochul 49%") == ("Kathy Hochul", 49.0)


def test_pollster_aliases_do_not_double_count_one_survey():
    frame = pd.DataFrame(
        [
            {
                "office": "governor",
                "location": "CA",
                "end_date": "2026-04-27",
                "pollster": pollster,
                "dem_candidate": "D",
                "rep_candidate": "R",
                "dem_pct": 45.0,
                "rep_pct": 44.0,
                "source": "decision_labs",
                "source_url": "https://example.test",
            }
            for pollster in ("CBS News", "CBS / YouGov")
        ]
    )
    result = merge_current_polls(frame)
    assert len(result) == 1
    assert "CBS News" in result.iloc[0]["reported_pollster_aliases"]
    assert result.iloc[0]["pollster"] == "CBS / YouGov"


def test_pollster_metadata_suffixes_are_not_identity():
    frame = pd.DataFrame(
        [
            {
                "office": "senate",
                "location": "TX",
                "end_date": "2026-07-30",
                "pollster": "Beacon Research (D)/ Shaw & Co. Research (R) ±2.3",
                "dem_candidate": "Talarico",
                "rep_candidate": "Paxton",
                "dem_pct": 51.0,
                "rep_pct": 48.0,
                "source": "270towin",
                "source_url": "https://example.test",
            }
        ]
    )
    result = merge_current_polls(frame)
    assert result.iloc[0]["pollster"] == "Beacon Research (D)/ Shaw & Co. Research (R)"


def test_cross_source_dedupe_tolerates_date_conventions():
    rows = []
    for source, end_date, sample_size in [
        ("pollingsource", "2026-08-05", 1000),
        ("270towin", "2026-08-13", 1000),
    ]:
        rows.append(
            {
                "office": "senate",
                "location": "TX",
                "cycle": 2026,
                "end_date": end_date,
                "pollster": "Emerson College",
                "dem_candidate": "James Talarico",
                "rep_candidate": "Ken Paxton",
                "dem_pct": 46.0,
                "rep_pct": 47.0,
                "sample_size": sample_size,
                "population": "lv",
                "source": source,
                "source_url": (
                    "https://pollingsource.com/senate/polls"
                    if source == "pollingsource"
                    else "https://emersoncollegepolling.com/texas-2026-poll/"
                ),
            }
        )
    result = merge_current_polls(pd.DataFrame(rows))
    assert len(result) == 1
    assert result.iloc[0]["source_count"] == 2
    assert result.iloc[0]["reported_end_dates"] == "2026-08-05 | 2026-08-13"
    assert result.iloc[0]["source"] == "270towin"


def test_cross_source_dedupe_tolerates_release_dates_two_weeks_apart():
    rows = []
    for source, end_date, pollster in [
        ("pollingsource", "2026-08-13", "University of Texas/Texas Politics Project"),
        ("270towin", "2026-08-25", "University of Texas"),
    ]:
        rows.append(
            {
                "office": "senate",
                "location": "TX",
                "cycle": 2026,
                "end_date": end_date,
                "pollster": pollster,
                "dem_candidate": "James Talarico",
                "rep_candidate": "Ken Paxton",
                "dem_pct": 42.0,
                "rep_pct": 39.0,
                "sample_size": 1200,
                "population": "rv",
                "source": source,
                "source_url": "https://example.test/topline",
            }
        )
    result = merge_current_polls(pd.DataFrame(rows))
    assert len(result) == 1
    assert result.iloc[0]["source_count"] == 2
    assert result.iloc[0]["reported_end_dates"] == "2026-08-13 | 2026-08-25"


def test_270towin_map_and_general_election_parser():
    map_payload = b"""<script>m.seats = {"48":[{"state_abbr":"TX","url_link":
        "https:\\/\\/www.270towin.com\\/2026-senate-polls\\/texas"}]};</script>"""
    assert _map_pages(map_payload) == [("TX", "https://www.270towin.com/2026-senate-polls/texas")]
    page = """
    <div id="GE"><h4>Talarico vs. Paxton</h4><table><thead><tr>
      <th class="poll_src">Source</th><th class="poll_date">Date</th>
      <th class="poll_sample">Sample</th>
      <th class="can_name" style="background-color:#3e5a96">Talarico</th>
      <th class="can_name" style="background-color:#c23237">Paxton</th>
    </tr></thead><tbody><tr class="poll_row">
      <td class="poll_src"><a href="https://example.test/topline">Example Poll ±3.1</a></td>
      <td class="poll_date">8/13/2026</td><td class="poll_sample">1,000 LV +/-3%</td>
      <td class="poll_data">46%</td><td class="poll_data">47%</td>
    </tr></tbody></table></div>
    """.encode()
    records = _parse_page(
        page,
        office=Office.SENATE,
        location="TX",
        page_url="https://www.270towin.com/2026-senate-polls/texas",
        cycle=2026,
        election_date=date(2026, 11, 3),
        fetched_at=datetime(2026, 8, 16, tzinfo=UTC),
    )
    assert len(records) == 1
    assert records[0]["dem_candidate"] == "Talarico"
    assert records[0]["pollster"] == "Example Poll"
    assert records[0]["sample_size"] == 1000
    assert records[0]["source_url"] == "https://example.test/topline"


def test_270towin_source_url_rejects_local_paths_and_repairs_pasted_urls():
    page = "https://www.270towin.com/2026-senate-polls/florida"
    assert _clean_source_url("file:///C:/Users/example/topline.pdf", page) == page
    assert (
        _clean_source_url("https://www.270towin.com\\t\\thttps://unf.example/topline.pdf", page)
        == "https://unf.example/topline.pdf"
    )


def test_silver_generic_prefers_likely_voter_version():
    csv_payload = (
        b"subgroup,pollster,sponsors,enddate,samplesize,population,dem,rep,url,"
        b"partisan,poll_id,question_id\n"
        b"All polls,Example,Sponsor,8/11/2026,1000,RV,48,42,"
        b"https://example.test/rv,,10,101\n"
        b"All polls,Example,Sponsor,8/11/2026,800,LV,49,42,"
        b"https://example.test/lv,DEM,10,102\n"
    )

    class StubClient:
        def get(self, url: str, *, refresh: bool = False) -> bytes:
            return csv_payload

    result = fetch_silver_generic_ballot(client=StubClient())  # type: ignore[arg-type]
    assert len(result) == 1
    assert result.iloc[0]["population"] == "lv"
    assert result.iloc[0]["partisan"] == "D"
    assert result.iloc[0]["dem_pct"] == 49.0


def test_straw_poll_is_retained_only_in_exclusion_audit():
    frame = pd.DataFrame(
        [
            {"pollster": "Scientific Poll"},
            {"pollster": "Iowa State Fair Straw"},
        ]
    )
    included, excluded = _exclude_non_model_polls(frame)
    assert included["pollster"].tolist() == ["Scientific Poll"]
    assert excluded["pollster"].tolist() == ["Iowa State Fair Straw"]
    assert excluded.iloc[0]["exclusion_reason"] == "nonrepresentative straw poll"


def test_house_history_normalizes_official_seats_and_fusion_votes():
    table = pd.DataFrame(
        {
            "Congress (Years)": ["118th (2023-2025)", "119th (2025-2027)"],
            "# of House Seats": ["435", "435"],
            "First party": ["213", "215"],
            "Second party": ["222", "220"],
        }
    )
    normalized = _normalize_house_party_divisions(table)
    assert normalized.set_index("cycle").loc[2024, "dem_seats"] == 215

    results = pd.DataFrame(
        [
            {
                "cycle": 2024,
                "stage": "general",
                "special": False,
                "state_abbrev": "NY",
                "race_id": 1,
                "candidate_id": 10,
                "ballot_party": party,
                "votes": votes,
            }
            for party, votes in [("DEM", 100), ("WFP", 20)]
        ]
        + [
            {
                "cycle": 2024,
                "stage": "general",
                "special": False,
                "state_abbrev": "NY",
                "race_id": 1,
                "candidate_id": 11,
                "ballot_party": "REP",
                "votes": 100,
            }
        ]
    )
    assert _house_2024_major_party_margin(results) == 100 * 20 / 220
