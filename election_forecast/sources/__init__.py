"""External polling data source adapters."""

from .decision_labs import fetch_decision_labs_polls
from .fec import fetch_fec_candidates
from .fte_archive import fetch_fte_full_archive, fetch_fte_generic_archive
from .fte_history import fetch_fte_history
from .hobby import fetch_hobby_polls
from .polling_source import (
    fetch_polling_source,
    fetch_polling_source_catalog,
    fetch_polling_source_governors,
)
from .prediction_markets import fetch_prediction_markets
from .reference_results import (
    fetch_fte_reference_results,
    fetch_house_national_history,
    fetch_mit_2024_results,
)
from .silver_generic import fetch_silver_generic_ballot
from .two_seventy import fetch_270towin_polls

__all__ = [
    "fetch_fte_full_archive",
    "fetch_fte_generic_archive",
    "fetch_fte_history",
    "fetch_hobby_polls",
    "fetch_fte_reference_results",
    "fetch_house_national_history",
    "fetch_mit_2024_results",
    "fetch_fec_candidates",
    "fetch_decision_labs_polls",
    "fetch_polling_source",
    "fetch_polling_source_catalog",
    "fetch_polling_source_governors",
    "fetch_silver_generic_ballot",
    "fetch_270towin_polls",
    "fetch_prediction_markets",
]
