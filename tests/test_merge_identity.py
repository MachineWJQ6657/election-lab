import pandas as pd

from election_forecast.sources.merge import merge_current_polls


def poll(pollster, source, day, population="lv"):
    return dict(
        office="senate",
        location="TX",
        cycle=2026,
        dem_candidate="James Talarico",
        rep_candidate="Ken Paxton",
        dem_pct=48,
        rep_pct=46,
        sample_size=1000,
        population=population,
        pollster=pollster,
        source=source,
        end_date=day,
        source_url=f"https://{source}.example/",
    )


def test_identical_results_from_different_institutes_stay_independent():
    rows = [poll("Emerson College", "a", "2026-09-20"), poll("Siena College", "b", "2026-09-20")]
    assert len(merge_current_polls(pd.DataFrame(rows))) == 2


def test_fox_publisher_matches_joint_beacon_shaw_credit():
    rows = [
        poll("Fox News", "a", "2026-10-01"),
        poll("Beacon Research (D)/ Shaw & Co. Research (R)", "b", "2026-09-28"),
    ]
    assert len(merge_current_polls(pd.DataFrame(rows))) == 1


def test_beacon_alone_is_not_automatically_a_fox_poll():
    rows = [poll("Fox News", "a", "2026-10-01"), poll("Beacon", "b", "2026-09-28")]
    assert len(merge_current_polls(pd.DataFrame(rows))) == 2


def test_latin_accent_aliases_share_one_matchup_and_survey():
    first = poll("Emerson", "a", "2026-10-09")
    second = poll("Emerson College", "b", "2026-10-09")
    first.update(location="NM", dem_candidate="Ben Ray Luján", rep_candidate="Larry Marker")
    second.update(location="NM", dem_candidate="Lujan", rep_candidate="Marker")
    result = merge_current_polls(pd.DataFrame([first, second]))
    assert len(result) == 1
    assert result.iloc[0]["race_id"].endswith(":lujan:marker")


def test_population_versions_are_not_the_same_observation():
    rows = [
        poll("Emerson", "a", "2026-09-20", "lv"),
        poll("Emerson College", "b", "2026-09-20", "rv"),
    ]
    assert len(merge_current_polls(pd.DataFrame(rows))) == 2


def test_cross_source_alias_cannot_bridge_two_tracking_waves():
    rows = [
        poll("Emerson", "a", "2026-09-10"),
        poll("Emerson College", "b", "2026-09-13"),
        poll("Emerson", "a", "2026-09-17"),
    ]
    assert len(merge_current_polls(pd.DataFrame(rows))) == 2
