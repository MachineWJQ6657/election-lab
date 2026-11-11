# 2026 general-election results scoring

Results retrieved through 2026-11-11T05:37:53.299208+00:00.
Frozen baseline: `final_2026_20261103T064943Z`; all 23 file hashes unchanged.

## Coverage and interpretation

509 frozen rows → 507 central contest/aggregate rows; 2 alternative matchups excluded before looking at outcomes.
Status counts: {"called": 57, "preliminary": 42, "unresolved": 408}.
This is a partial public-source snapshot, not a complete national election score. Missing or uncalled contests and preliminary leaders are unscored.
Called results are media projections. A call does not certify the attached vote totals. Certified-only metrics are empty until certification evidence is imported.

## Provisional comparisons

Probability scores: 53 comparable resolved forecasts; winner accuracy 84.91%, Brier 0.103847, log loss 0.360915.
Vote margins: 4 comparable resolved poll-model forecasts; MAE 8.5993 percentage points. The vote_result_status column identifies preliminary versus certified totals.

| Office | Probability N | Accuracy | Brier | Margin N | Margin MAE (pp) |
|---|---:|---:|---:|---:|---:|
| generic_ballot | 0 | — | — | 0 | — |
| governor | 13 | 0.8462 | 0.0629 | 1 | 9.2444 |
| house | 9 | 0.5556 | 0.3586 | 0 | — |
| senate | 31 | 0.9355 | 0.0470 | 3 | 8.3842 |

## Definitions

Brier = (p − y)² for the frozen named Democratic-side candidate event; independents retain candidate identity and are not silently treated as Democrats. Log loss clips p to [1e-15, 1−1e-15]. A 0.5 forecast receives half-credit.
Margin = 100 × (Democratic-side candidate votes − Republican-side candidate votes) / all candidate votes. Error = forecast − observed; positive bias is toward the D side. Third-party/write-in votes stay in the denominator. House rating priors have no validated margin and are excluded from margin error.
Probability scores exclude pairwise-only forecasts and unmatched winners. When a vote list is available both frozen candidates must match uniquely. Winner-only calls are labeled called_winner_only; they do not verify the full ballot matchup. RCV/runoff margins, unresolved races, alternative matchups and incomplete national generic-ballot totals are excluded. Partial coverage cannot establish chamber control.
Aggregates separate status, offices, and poll-model/rating-prior forecasts. The all_resolved view is provisional and includes certified outcomes if present.

## Authoritative sources

For Senate, House and governor, use the relevant state election authority and its contest-specific canvass/certification document. authoritative_sources.json includes all 50 FEC-listed authorities; race_scores.csv links each forecast to its authority. The FEC compiles certified federal results; states publish governor results. National House popular-vote comparison requires complete compatible district returns including unopposed contests. AP/CBS/WRAL provide calls, not certification.

## Retrieval / parsing gaps

- minnesota_governor: Minnesota response is not 2026 unofficial returns (may be CAPTCHA)
- minnesota_house: Minnesota response is not 2026 unofficial returns (may be CAPTCHA)
- ap_senate_calls: Client error '403 Forbidden' for url 'https://www.ap.org/the-definitive-source/behind-the-news/calling-control-of-congress-in-the-2026-midterm-elections/'
- ap_texas: Client error '403 Forbidden' for url 'https://apnews.com/article/6e285484736b5116629a3b6e37e1dda5'
- ap_nh_governor: Client error '403 Forbidden' for url 'https://apnews.com/article/9661abe26ba84eaba966abd0c9ad10b8'
- ap_california_house_07: Client error '403 Forbidden' for url 'https://apnews.com/article/9306dd0fd0604c4295cf9325e8cbfa9a'
