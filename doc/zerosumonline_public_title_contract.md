# zerosumonline.com public title/work contract

Issue: #202
Observed: 2026-04-08 JST

## Summary

`online.ichijinsha.co.jp/zerosum` now fronts the `zerosumonline.com` experience, but the current public work listing surface is not the previously assumed bare `/works` URL.

Observed current public contract:

- legacy landing entry: `https://online.ichijinsha.co.jp/zerosum/`
- current active listing page: `https://zerosumonline.com/works/series`
- current title detail page: `https://zerosumonline.com/detail/<tag>`
- current public chapter route shape: `https://zerosumonline.com/episode/<tag>/chapter/<latestChapterId>`

This issue remains investigation-only. Adapter implementation is a non-goal here.

## Accepted input URL

- Accepted now:
  - current title detail URL such as `https://zerosumonline.com/detail/shinryu`
  - current active listing URL `https://zerosumonline.com/works/series`
  - legacy landing entry `https://online.ichijinsha.co.jp/zerosum/` as a source-family clue
- Not accepted yet in this issue:
  - direct adapter support for every category page
  - chapter ingestion or protobuf decoding implementation

## Route blocker recorded in this lane

The issue body's earlier assumption that `https://zerosumonline.com/works` is the public works listing is no longer correct as observed on 2026-04-08:

- requesting `https://zerosumonline.com/works` returns a page whose `og:url` is `https://zerosumonline.com`
- the active works listing lives at `https://zerosumonline.com/works/series`
- the active listing page title is `連載作品 | ゼロサムオンライン`

This means follow-up work must treat `/works/series` as the public series listing seed instead of bare `/works`.

## Canonical seed

- Canonical public title seed: `https://zerosumonline.com/detail/<tag>`
- Representative observed title seed: `https://zerosumonline.com/detail/shinryu`

The detail page exposes stable public metadata:

- `og:url = https://zerosumonline.com/detail/shinryu`
- `og:image = https://contents.zerosumonline.com/title_thumbnail/197.webp`

## Stable identifier

- Candidate `work_id` rule: `zerosumonline:<tag>`
- Representative evidence: the public detail route is keyed by `tag`, and both listing and detail bundles route users by that same `tag`

## Listing contract

The works category bundle calls:

- API base: `https://api.zerosumonline.com/api/v1`
- list endpoint: `GET /list`
- observed query shape for active series page: `category=series&sort=date`

The works category page links each title to:

- `/detail/<tag>`

So a follow-up adapter can treat `/works/series` as the public discovery/list seed for active titles.

## Latest detection contract

The public detail bundle calls:

- title endpoint: `GET /title?tag=<tag>`

The shipped protobuf schema and detail-page bundle expose these signals:

- `Title.latestChapterId`
- `TitleView.chapters`
- public chapter route template `/episode/<tag>/chapter/<chapterId>`

Bounded rule established in this issue:

1. Normalize the title to `https://zerosumonline.com/detail/<tag>`.
2. Fetch the public title payload from `/title?tag=<tag>`.
3. Read the latest chapter identifier from the public title payload.
4. Materialize `latest_key` as:
   - `https://zerosumonline.com/episode/<tag>/chapter/<latestChapterId>`

This lane proves the route contract and the payload fields required for latest detection. It does not implement protobuf decoding.

## Implementation-ready outcome

Zerosum Online is implementation-ready for a Family B follow-up if that adapter:

- accepts current detail URLs under `/detail/<tag>`
- uses `/works/series` as the active public listing seed
- derives `work_id = zerosumonline:<tag>`
- decodes the public `/title?tag=<tag>` payload
- derives `latest_key = https://zerosumonline.com/episode/<tag>/chapter/<latestChapterId>`
- treats bare `/works` as a blocked or obsolete listing seed, not the canonical public listing page

## Evidence captured in this branch

- `tests/fixtures/zerosumonline/contract/detail_shinryu.json`
- `tests/fixtures/zerosumonline/contract/works_series.json`
- `tests/fixtures/zerosumonline/contract/works_root_blocked.json`
- `tests/test_zerosumonline_contract.py`
