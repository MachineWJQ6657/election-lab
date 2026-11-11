"""Offline parsers for archived 2026 returns; no automatic winner calls."""

from __future__ import annotations

import json
import re
from io import BytesIO
from zipfile import ZipFile

import pandas as pd
from bs4 import BeautifulSoup

from ..results import CandidateResult, ResultObservation, contest_type

STATE_NAMES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|"
    "Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|"
    "Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|"
    "New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|"
    "Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
    "West Virginia|Wisconsin|Wyoming"
).split("|")
STATE_CODES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
).split()
STATE_MAP = dict(zip(STATE_NAMES, STATE_CODES, strict=True))


def text_content(payload: bytes) -> str:
    return BeautifulSoup(payload, "lxml").get_text(" ", strip=True)


def clean_name(name: str) -> str:
    return re.sub(r"\s*\(I\)\s*", "", name, flags=re.I).strip()


def preliminary(source: dict, office: str, location: str, candidates: list, **kwargs):
    return ResultObservation(
        office=office,
        location=location,
        contest_type=contest_type(office, location),
        source_id=source["id"],
        status="preliminary",
        candidates=candidates,
        all_candidates_included=True,
        status_evidence="Official reporting feed; no certificate of canvass or winner assertion.",
        **kwargs,
    )


def parse_texas(payload: bytes, source: dict) -> list[ResultObservation]:
    soup = BeautifulSoup(payload, "lxml")
    text = soup.get_text(" ", strip=True)
    if "2026 NOVEMBER GENERAL ELECTION" not in text:
        raise ValueError("Texas feed is not the expected 2026 general election")
    updated = re.search(r"Updated ([^)]+)", text)
    output = []
    for table in soup.select("table.election"):
        title = table.find_previous("div", class_="election").get_text(" ", strip=True)
        if title == "U. S. SENATOR":
            office, location = "senate", "TX"
        elif title == "GOVERNOR":
            office, location = "governor", "TX"
        elif match := re.fullmatch(r"U\. S\. REPRESENTATIVE DISTRICT (\d+)", title):
            office, location = "house", f"TX-{int(match[1]):02d}"
        else:
            continue
        candidates = []
        for row in table.select("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.select("td")]
            if len(cells) == 3:
                candidates.append(
                    CandidateResult(
                        name=clean_name(cells[1]),
                        party=cells[0],
                        votes=int(cells[2].replace(",", "")),
                    )
                )
        output.append(
            preliminary(
                source,
                office,
                location,
                candidates,
                source_updated_at=updated[1] if updated else None,
            )
        )
    if len(output) != 40:
        raise ValueError(f"Expected 40 Texas congressional/governor contests, got {len(output)}")
    return output


def parse_north_carolina(payload: bytes, source: dict) -> list[ResultObservation]:
    with ZipFile(BytesIO(payload)) as archive:
        frame = pd.read_csv(
            BytesIO(archive.read("results_pct_20261103.txt")),
            sep="\t",
            encoding="utf-8-sig",
        )
    if set(frame["Election Date"]) != {"11/03/2026"}:
        raise ValueError("North Carolina file contains another election date")
    frame = frame[frame["Contest Name"].str.match(r"US SENATE$|US HOUSE OF REPRESENTATIVES")]
    if frame.duplicated(["County", "Precinct", "Contest Name", "Choice", "Choice Party"]).any():
        raise ValueError("Duplicate precinct candidate rows in North Carolina feed")
    output = []
    for title, contest in frame.groupby("Contest Name"):
        if title == "US SENATE":
            office, location = "senate", "NC"
        elif match := re.fullmatch(r"US HOUSE OF REPRESENTATIVES DISTRICT (\d+)", title):
            office, location = "house", f"NC-{int(match[1]):02d}"
        else:
            continue
        totals = contest.groupby(["Choice", "Choice Party"], dropna=False)["Total Votes"].sum()
        candidates = [
            CandidateResult(name=name, party=str(party), votes=int(votes))
            for (name, party), votes in totals.items()
        ]
        output.append(preliminary(source, office, location, candidates))
    if len(output) != 15:
        raise ValueError(f"Expected 15 North Carolina federal contests, got {len(output)}")
    return output


def parse_minnesota(payload: bytes, source: dict) -> list[ResultObservation]:
    soup = BeautifulSoup(payload, "lxml")
    text = soup.get_text(" ", strip=True)
    if "Unofficial Results" not in text or "November 3, 2026" not in text:
        raise ValueError("Minnesota response is not 2026 unofficial returns (may be CAPTCHA)")
    updated = re.search(r"Last Updated:\s*(.+?)Voters Registered", text)
    output = []
    for table in soup.find_all("table"):
        caption = table.find("caption")
        if caption is None:
            continue
        title = caption.get_text(" ", strip=True)
        if "U.S. Senator" in title:
            office, location = "senate", "MN"
        elif "Governor & Lt Governor" in title:
            office, location = "governor", "MN"
        elif match := re.search(r"U.S. Representative District (\d+)", title):
            office, location = "house", f"MN-{int(match[1]):02d}"
        else:
            continue
        candidates = []
        for row in table.select("tbody tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) >= 5:
                name = cells[2].split(" and ")[0] if office == "governor" else cells[2]
                candidates.append(
                    CandidateResult(
                        name=name,
                        party=cells[1],
                        votes=int(cells[3].replace(",", "")),
                    )
                )
        output.append(
            preliminary(
                source,
                office,
                location,
                candidates,
                source_updated_at=updated[1].strip() if updated else None,
            )
        )
    expected = 8 if source["office"] == "house" else 1
    if len(output) != expected:
        raise ValueError(f"Expected {expected} Minnesota contests, got {len(output)}")
    return output


def parse_ap_senate(payload: bytes, source: dict) -> list[ResultObservation]:
    text = payload.decode("utf-8") if source.get("transport") else text_content(payload)
    pattern = (
        r"(?:Democrat|Republican) (.+?) wins (?:reelection|election) to U\.S\. Senate from "
        r"([A-Za-z ]+)\."
    )
    output = []
    for name, state in re.findall(pattern, text):
        output.append(
            ResultObservation(
                office="senate",
                location=STATE_MAP[state],
                contest_type=contest_type("senate", STATE_MAP[state]),
                source_id=source["id"],
                status="called",
                winner_candidate=name,
                source_updated_at="2026-11-05",
                status_evidence="Explicit AP race-call entry in the November 5 Senate chronology.",
            )
        )
    if len(output) != 33 or len({o.location for o in output}) != 33:
        raise ValueError(f"Expected 33 AP Senate calls in retained chronology: {len(output)}")
    return output


def parse_reviewed_calls(payload: bytes, source: dict, reviews: list[dict]) -> list:
    text = text_content(payload)
    output = []
    for review in reviews:
        if review["source_id"] != source["id"]:
            continue
        if any(term.casefold() not in text.casefold() for term in review["required_terms"]):
            raise ValueError(f"Reviewed call evidence no longer matches: {review}")
        output.append(
            ResultObservation(
                **{key: value for key, value in review.items() if key != "required_terms"}
            )
        )
    return output


def parse_state_directory(payload: bytes, source: dict) -> list[dict]:
    soup = BeautifulSoup(payload, "lxml")
    output = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        name = cells[0].get_text(" ", strip=True)
        if "Candidates on Ballot" in name:
            continue
        name = name.replace(" (Election Results)", "")
        if name not in STATE_MAP:
            continue
        output.append(
            {
                "state": STATE_MAP[name],
                "state_name": name,
                "authority": cells[1].get_text(" ", strip=True),
                "authority_url": cells[2].find("a")["href"],
                "offices": ["senate", "house", "governor"],
                "directory_source_url": source["url"],
                "retrieved_at": source["retrieved_at"],
                "certification_policy": "Obtain the state canvass/certification document for the "
                "specific contest. This directory is not evidence of certification.",
            }
        )
    if len(output) != 50:
        raise ValueError(f"Expected 50 state authorities in FEC directory, got {len(output)}")
    return output


def parse_source(payload: bytes, source: dict, reviews: list[dict]) -> list[ResultObservation]:
    parsers = {
        "texas": parse_texas,
        "north_carolina": parse_north_carolina,
        "minnesota": parse_minnesota,
        "ap_senate": parse_ap_senate,
    }
    if source["adapter"] in {"reference", "state_directory"}:
        return []
    if source["adapter"] == "reviewed_calls":
        return parse_reviewed_calls(payload, source, reviews)
    if source["adapter"] == "normalized":
        return [ResultObservation.model_validate(row) for row in json.loads(payload)]
    return parsers[source["adapter"]](payload, source)
