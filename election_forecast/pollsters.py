"""Conservative fieldwork-organization aliases for historical quality estimates."""

import re


def pollster_key(value: object) -> str:
    text = re.sub(r"\([dr]\)|[★☆]|[±].*$", "", str(value).casefold()).strip()
    aliases = (
        (r"\byougov\b", "yougov"),
        (r"\bipsos\b", "ipsos"),
        (r"\bsiena\b", "siena"),
        (r"\bemerson\b", "emerson"),
        (r"\bquinnipiac\b", "quinnipiac"),
        (r"\bmarist\b", "marist"),
        (r"\bmonmouth\b", "monmouth"),
        (r"\bmorning consult\b", "morning-consult"),
        (r"\bsurveyusa\b", "surveyusa"),
        (r"\bfox news\b|beacon.*shaw", "fox-beacon-shaw"),
    )
    for pattern, key in aliases:
        if re.search(pattern, text):
            return key
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")
