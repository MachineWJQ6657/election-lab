from datetime import date

import pandas as pd
import pytest

from election_forecast.sources.enjoyer import RELEASE_URL, parse_enjoyer_release
from election_forecast.sources.merge import merge_current_polls

PAYLOAD = b"""<meta property="article:published_time" content="2026-09-29T13:40:49.853Z">
<main>The poll was conducted by Cygnal in conjunction with Beacon Research
among 600 likely 2026 general election voters in Michigan from Sept. 18-21, 2026.
<h3><span>1.</span>Governor</h3><table><caption>Governor</caption>
<tr><th>Jocelyn Benson (Democratic)</th><td><div>chart</div></td><td>45%</td></tr>
<tr><td>Definitely</td><td>34%</td></tr>
<tr><td>John James (Republican)</td><td>38%</td></tr></table>
<h3>2 . U.S. Senate</h3><table><caption>U.S. Senate</caption>
<tr><td>Abdul El-Sayed (Democratic)</td><td>45%</td></tr>
<tr><td>Mike Rogers (Republican)</td><td>40%</td></tr></table>
<h3>5 . Michigan House (generic ballot)</h3><table><caption>Michigan House</caption>
<tr><td>Democratic candidate</td><td>46%</td></tr>
<tr><td>Republican candidate</td><td>40%</td></tr></table></main>"""


def test_primary_michigan_scopes_toplines_not_subanswers_or_state_house():
    result = parse_enjoyer_release(PAYLOAD, as_of=date(2026, 10, 19))
    assert result.office.tolist() == ["governor", "senate"]
    assert result.margin.tolist() == [7, 5]
    assert set(result.end_date) == {"2026-09-21"}
    assert set(result.publication_date) == {"2026-09-29"}
    assert set(result.population) == {"lv"}
    assert result.partisan.isna().all()  # Joint firm's affiliations are not a party sponsor.
    with pytest.raises(ValueError, match="not available"):
        parse_enjoyer_release(PAYLOAD, as_of=date(2026, 9, 28))
    with pytest.raises(ValueError, match="scoped Governor"):
        parse_enjoyer_release(PAYLOAD.replace(b"<caption>Governor</caption>", b""), as_of=date.max)


def test_primary_release_corroborates_existing_aggregator_without_adding_votes():
    result = parse_enjoyer_release(PAYLOAD, as_of=date(2026, 10, 19))
    aggregator = result.copy()
    aggregator["source"] = "aggregator"
    aggregator["end_date"] = "2026-09-29"  # Publisher's release date, not fieldwork.
    aggregator["primary_source_verified"] = False
    merged = merge_current_polls(pd.concat([aggregator, result], ignore_index=True))
    assert len(merged) == 2
    assert set(merged.source_count) == {2}
    assert set(merged.source) == {"enjoyer_primary"}
    assert set(merged.end_date) == {"2026-09-21"}
    assert set(merged.source_url) == {RELEASE_URL}
