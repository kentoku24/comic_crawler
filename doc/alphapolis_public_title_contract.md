# alphapolis.co.jp public title/work contract

Issue: #199
Observed: 2026-04-08 JST

## Summary

`alphapolis.co.jp` can be treated as a Family B host whose canonical seed is the public title/work page:

- `https://www.alphapolis.co.jp/manga/official/<work_id>`

The title/work page exposes enough public information to define a stable normalize contract and a conditional latest detection contract without using login, browser automation, or private APIs.

## Accepted input URL

- Accepted now: public title/work URL
  - Example: `https://www.alphapolis.co.jp/manga/official/208000499`
- Not accepted yet in this issue:
  - landing page URLs such as `https://www.alphapolis.co.jp/manga/official`
  - episode URLs such as `/manga/official/<work_id>/<episode_no>`

## Canonical seed

- Canonical seed: `https://www.alphapolis.co.jp/manga/official/<work_id>`
- The public page exposes a canonical `<link rel="canonical">` that matches the title/work URL.

## Stable identifier

- `work_id` rule: `alphapolis:<mangaId>`
- Evidence:
  - page canonical URL contains the numeric title/work id
  - inline JSON under `#app-official-manga-toc` repeats the same `mangaId`

## Latest detection contract

The public title/work page contains an inline JSON payload under `#app-official-manga-toc` with:

- `mangaId`
- `mangaTitle`
- `episodes`

Rule:

1. Parse the title/work page.
2. Read the inline JSON payload.
3. If `episodes` is non-empty, use the last episode entry as the current latest public episode.
4. Build `latest_key` from the absolute episode URL:
   - `https://www.alphapolis.co.jp` + `episodes[-1].url`

For `https://www.alphapolis.co.jp/manga/official/208000499`, the observed latest public episode on 2026-04-08 was:

- `episodeNo`: `11676`
- `latest_key`: `https://www.alphapolis.co.jp/manga/official/208000499/11676`
- `upTime`: `2026.04.06更新`

## Blocker contract

Some title/work pages exist before the first public episode is released.

Observed pre-publication contract on `https://www.alphapolis.co.jp/manga/official/920000640`:

- canonical title/work page exists
- inline JSON exposes `mangaId` and `mangaTitle`
- `episodes` is an empty array
- page body exposes `2026.04.10公開予定`
- the "第1回を読む" button is disabled

For this state:

- normalize is possible
- canonical seed is stable
- `work_id` is stable
- latest episode detection is blocked until at least one public episode appears

This means the adapter contract must distinguish:

- `ready`: `episodes.length > 0`
- `blocked_prepublication`: `episodes.length == 0` and the page exposes a publish-scheduled marker

## Non-authoritative signals

These signals are useful for display or future canaries, but should not be the primary latest key:

- schedule text such as `毎月第3月曜日更新`
- next update text such as `次回更新日 : 2026.04.27`
- landing page "最近更新された漫画"

These are helpful hints, but they do not uniquely identify the latest public episode for a single work.

## Implementation-ready outcome

Alphapolis is implementation-ready for Family B if a follow-up adapter:

- accepts only title/work URLs
- normalizes to `https://www.alphapolis.co.jp/manga/official/<work_id>`
- derives `work_id = alphapolis:<mangaId>`
- derives `latest_key` from the last public episode URL when `episodes` is non-empty
- returns a clear blocker state for pre-publication pages with `episodes == []`
- adds representative fixtures for both:
  - an active title/work page with episodes
  - a pre-publication title/work page without episodes

## Evidence captured in this branch

- `tests/fixtures/alphapolis/contract/208000499.json`
- `tests/fixtures/alphapolis/contract/920000640.json`
- `tests/test_alphapolis_contract.py`
