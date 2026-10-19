"""Canonical records shared by live and historical data sources."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class Office(StrEnum):
    PRESIDENT = "president"
    SENATE = "senate"
    HOUSE = "house"
    GOVERNOR = "governor"
    GENERIC_BALLOT = "generic_ballot"


class Population(StrEnum):
    LIKELY_VOTERS = "lv"
    REGISTERED_VOTERS = "rv"
    VOTERS = "v"
    ADULTS = "a"
    UNKNOWN = "unknown"


class PollRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_id: str
    race_id: str
    cycle: int
    office: Office
    location: str
    pollster: str
    end_date: date
    election_date: date
    sample_size: int | None = Field(default=None, ge=1)
    population: Population = Population.UNKNOWN
    methodology: str | None = None
    partisan: str | None = None
    transparency_score: float | None = None
    pollster_grade: str | None = None
    dem_candidate: str
    rep_candidate: str
    dem_pct: float = Field(ge=0, le=100)
    rep_pct: float = Field(ge=0, le=100)
    actual_margin: float | None = None
    source_url: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: str) -> str:
        normalized = value.strip().upper().replace(" ", "-")
        district = re.fullmatch(r"([A-Z]{2})-(\d{1,2})", normalized)
        if district:
            return f"{district.group(1)}-{int(district.group(2)):02d}"
        return normalized

    @computed_field
    @property
    def margin(self) -> float:
        """Democratic percentage minus Republican percentage."""
        return self.dem_pct - self.rep_pct

    @computed_field
    @property
    def days_to_election(self) -> int:
        return (self.election_date - self.end_date).days
