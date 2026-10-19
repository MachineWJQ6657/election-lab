"""Prefer complete archives without counting the ratings extract twice."""

from __future__ import annotations

import pandas as pd


def merge_historical_sources(
    ratings: pd.DataFrame,
    archive: pd.DataFrame | None,
    *,
    min_cycle: int | None = None,
) -> pd.DataFrame:
    """Replace only office/cycle cells actually covered by the full archive.

    A global start-year cutoff loses offices missing from the archive; always
    keeping generic-ballot extracts double-counts them once that archive exists.
    """
    frames = [ratings]
    if archive is not None and not archive.empty:
        covered = pd.MultiIndex.from_frame(archive[["office", "cycle"]].drop_duplicates())
        cells = pd.MultiIndex.from_frame(ratings[["office", "cycle"]])
        frames = [ratings.loc[~cells.isin(covered)], archive]
    merged = pd.concat(frames, ignore_index=True, sort=False)
    if min_cycle is not None:
        merged = merged.loc[merged["cycle"].ge(min_cycle)]
    return merged.drop_duplicates(["source", "source_id"], keep="last").reset_index(drop=True)
