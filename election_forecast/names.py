"""Shared candidate matching keys; preserve original spelling for display."""

import re
import unicodedata

# Person-specific, source-verified aliases, not an unrestricted nickname guess.
# Robert/Bob Menendez: Senate Foreign Relations Committee, 2015-03-02.
# https://www.foreign.senate.gov/press/dem/release/senator-menendezs-remarks-at-aipac-national-convention
# Timothy Michael/Tim Kaine: official Virginia Senate timeline, 2016-07-27.
# https://www.senate.gov/states/VA/timeline.shtml
VERIFIED_GIVEN_ALIASES = {("menendez", "bob"): "robert", ("kaine", "tim"): "timothy"}
COMPATIBLE_NAME_MATCHES = frozenset(
    {
        "given_name_compatible",
        "initial_compatible",
        "surname_only",
        "verified_alias_compatible",
    }
)


def given_name_key(value: object, *, fec_format: bool = False) -> str:
    """Return a known first name/initial; never infer a nickname or identity."""
    if not candidate_key(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold()
    if fec_format and "," in text:
        text = text.split(",", 1)[1]
        tokens = re.findall(r"[a-z]+", text)
    else:
        tokens = re.findall(r"[a-z]+", text)
        while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv"}:
            tokens.pop()
        tokens = tokens[:-1]
    while tokens and tokens[0] in {"dr", "mr", "mrs", "ms", "hon", "sen", "rep", "senator"}:
        tokens.pop(0)
    return tokens[0] if tokens else ""


def candidate_name_match(left: object, right: object, *, right_fec_format: bool = False) -> str:
    """Grade a name match so same-family candidates are not silently equated.

    A compatible name is not a verified person ID. Unresolved nicknames need
    provenance, not a guessed expansion.
    """
    right_surname = str(right).split(",", 1)[0] if right_fec_format else right
    last_left, last_right = candidate_key(left), candidate_key(right_surname)
    if not last_left or not last_right:
        return "unknown"
    if last_left != last_right:
        return "different_surnames"
    first_left = given_name_key(left)
    first_right = given_name_key(right, fec_format=right_fec_format)
    if not first_left or not first_right:
        return "surname_only"
    if first_left == first_right:
        return "given_name_compatible"
    if VERIFIED_GIVEN_ALIASES.get(
        (last_left, first_left), first_left
    ) == VERIFIED_GIVEN_ALIASES.get((last_right, first_right), first_right):
        return "verified_alias_compatible"
    if min(len(first_left), len(first_right)) == 1 and first_left[0] == first_right[0]:
        return "initial_compatible"
    return "different_given_names_review"


def candidate_key(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold()
    tokens = re.findall(r"[a-z]+", text)
    if (
        text in {"nan", "none", "null"}
        or not tokens
        or any(token in {"tbd", "unknown", "nominee"} for token in tokens)
    ):
        return ""
    while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv"}:
        tokens.pop()
    return tokens[-1] if tokens else ""
