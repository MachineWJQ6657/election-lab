from datetime import date

import pytest

from election_forecast.sources.hobby import DISTRICT_URL, STATEWIDE_URL, parse_hobby_release


def test_statewide_primary_keeps_fieldwork_release_and_original_sample():
    payload = b"""<main>online statewide survey of likely voters in Texas,
    between Oct. 10 and Oct. 14, 2026.
    overall sample population of 2,000 likely voters.
    Democrat James Talarico (48%) leads Republican challenger Ken Paxton (46%).
    Republican incumbent Greg Abbott (49%) leads Democrat Gina Hinojosa (46%).
    Media Release October 19, 2026</main>"""
    result = parse_hobby_release(payload, url=STATEWIDE_URL, as_of=date(2026, 10, 19))
    assert len(result) == 2
    assert set(result.end_date) == {"2026-10-14"}
    assert set(result.publication_date) == {"2026-10-19"}
    assert result.margin.tolist() == [2, -3]
    assert result.sample_size.tolist() == [2000, 2000]
    with pytest.raises(ValueError, match="not available"):
        parse_hobby_release(payload, url=STATEWIDE_URL, as_of=date(2026, 10, 18))


def test_district_poll_does_not_turn_statewide_cross_tabs_into_statewide_surveys():
    payload = b"""<main>fielded between October 3 and October 7, 2026,
    overall sample population of 677 likely voters in TX-9.
    Republican Alex Mealer is leading Democratic challenger Leticia Gutierrez
    with support from 48% of likely voters, compared with 42% for Gutierrez.
    Senate Paxton leads by 1 point. Governor Abbott leads by 4 points.
    Media Release October 14, 2026</main>"""
    result = parse_hobby_release(payload, url=DISTRICT_URL, as_of=date(2026, 10, 19))
    assert len(result) == 1
    assert result.iloc[0].location == "TX-09"
    assert result.iloc[0].office == "house"
    assert result.iloc[0].margin == -6
    assert result.iloc[0].district_boundary_changed
