from election_forecast.pollsters import pollster_key


def test_fieldwork_alias_keys_are_idempotent_without_merging_unrelated_campuses():
    for name in ("CBS News/YouGov", "Emerson College (R)", "Fox News", "Morning Consult"):
        key = pollster_key(name)
        assert pollster_key(key) == key
    assert pollster_key("CBS News/YouGov") == pollster_key("YouGov")
    assert pollster_key("University of Texas at Tyler") != pollster_key("University of Texas")
