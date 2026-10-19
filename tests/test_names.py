import pytest

from election_forecast.names import candidate_key


@pytest.mark.parametrize(
    "left,right",
    [
        ("Ben Ray Luján", "Lujan"),
        ("Marie Gluesenkamp Pérez", "Perez"),
        ("John Smith Jr.", "Smith"),
        ("José García", "Garcia"),
    ],
)
def test_candidate_keys_handle_latin_accents_and_suffixes(left, right):
    assert candidate_key(left) == candidate_key(right)


@pytest.mark.parametrize("value", [None, float("nan"), "Democratic nominee TBD", "Unknown"])
def test_unknown_candidates_do_not_match_as_named_nominees(value):
    assert candidate_key(value) == ""
