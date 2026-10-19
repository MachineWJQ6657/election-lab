import pytest

from election_forecast.names import candidate_key, candidate_name_match


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


def test_same_family_names_do_not_establish_same_candidate():
    assert (
        candidate_name_match("Darline Graham", "Lindsey Graham") == "different_given_names_review"
    )
    assert (
        candidate_name_match("Darline Graham", "GRAHAM, DARLINE", right_fec_format=True)
        == "given_name_compatible"
    )
    assert candidate_name_match("Graham", "Darline Graham") == "surname_only"
    assert (
        candidate_name_match("Ben Ray Luján", "LUJAN, BEN RAY", right_fec_format=True)
        == "given_name_compatible"
    )


def test_verified_aliases_preserve_continuity_without_guessing_unrelated_nicknames():
    assert candidate_name_match("Bob Menendez", "Robert Menendez") == "verified_alias_compatible"
    assert candidate_name_match("Tim Kaine", "Timothy Michael Kaine") == "verified_alias_compatible"
    assert candidate_name_match("Bob Example", "Robert Example") == "different_given_names_review"
