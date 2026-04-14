# ganganonline.com public title/chapter contract

Issue: #200
Observed: 2026-04-08 JST

## Summary

`ganganonline.com` can be treated as a Family B host whose canonical seed is the public title page:

- `https://www.ganganonline.com/title/<title_id>`

The public title page exposes enough structured data in `__NEXT_DATA__` to define a stable normalize contract and a latest public chapter detection contract without login, browser automation, or private APIs.

The public chapter page also exposes enough information to normalize `/title/<title_id>/chapter/<chapter_id>` back to the canonical title seed.

## Accepted input URL

- Accepted now: public title URL
  - Example: `https://www.ganganonline.com/title/2250`
- Accepted now: public chapter URL
  - Example: `https://www.ganganonline.com/title/2250/chapter/121212`
- Not accepted in this issue:
  - top-level landing pages such as `https://www.ganganonline.com/`
  - list pages such as `/rensai`, `/finish`, `/search`
  - app-deep-link URLs under `ganganonline.onelink.me`

## Canonical seed

- Canonical seed: `https://www.ganganonline.com/title/<title_id>`
- Evidence:
  - the title page route itself is stable and public
  - the chapter page `__NEXT_DATA__` includes `titleDetailUrl = /title/2250`, which points back to the title seed

## Stable identifier

- `work_id` rule: `ganganonline:<title_id>`
- Evidence:
  - the title page `__NEXT_DATA__` includes `titleId = 2250`
  - the chapter route and chapter page `titleDetailUrl` both carry the same title identifier

## Latest detection contract

The title page `__NEXT_DATA__` payload contains:

- `titleId`
- `titleName`
- `chapters[]`

Observed chapter-card contract on `https://www.ganganonline.com/title/2250`:

- future or app-only cards carry `appLaunchUrl`
- the current public chapter card does not carry `appLaunchUrl`
- chapter cards are ordered newest-first

Rule:

1. Parse the title page `__NEXT_DATA__`.
2. Read `chapters[]` in order.
3. Skip cards that contain `appLaunchUrl`, because those cards route to app info rather than a public web chapter.
4. Select the first remaining chapter card as the latest public web chapter.
5. Build `latest_key` from the public chapter route:
   - `https://www.ganganonline.com/title/<title_id>/chapter/<chapter_id>`

For `https://www.ganganonline.com/title/2250`, the observed latest public chapter on 2026-04-08 was:

- future/app-only card: chapter `121209`
  - `mainText`: `次回更新：4月15日`
  - has `appLaunchUrl`
- latest public web chapter: chapter `121212`
  - `mainText`: `9.-2`
  - `publishingPeriod`: `2026.04.08〜2026.04.14`
  - `latest_key`: `https://www.ganganonline.com/title/2250/chapter/121212`

## Chapter URL normalization contract

Observed public chapter page contract on `https://www.ganganonline.com/title/2250/chapter/121212`:

- the route is public and returns HTML without login
- chapter page `__NEXT_DATA__` includes:
  - `titleDetailUrl = /title/2250`
  - `chapterName = 9.-2`
  - `lastPage.sns.url = https://www.ganganonline.com/share/2250/121212`

This means a chapter input URL can be normalized by:

1. reading `titleDetailUrl` from chapter page `__NEXT_DATA__`
2. resolving it against `https://www.ganganonline.com`
3. storing the canonical seed as `https://www.ganganonline.com/title/<title_id>`

## Failure and blocker contract

- If title-page `__NEXT_DATA__` is missing, normalization must fail loudly.
- If `chapters[]` is missing or empty, latest detection must fail loudly instead of guessing from decorative DOM text.
- If every newest card exposes only `appLaunchUrl`, the host should return a blocker state such as `blocked_app_only_latest` instead of pretending a public latest chapter exists.
- `status` values appear in the payload, but this issue does not treat them as authoritative because the public/public-vs-app distinction is already observable through `appLaunchUrl`.

## Non-authoritative signals

These signals are useful for display or follow-up canaries, but should not be the primary latest key:

- the page `<title>` or `og:*` metadata
- card badge text such as `更新`
- card `publishingPeriod`
- share URLs under `/share/...`

They help confirm the observation, but the durable contract is the title route plus `chapters[].id` and the absence of `appLaunchUrl`.

## Drift canary defer reason

This issue is an investigation lane, not an adapter implementation lane.

- focused contract fixtures and tests are added here
- live source drift canary wiring is deferred to the follow-up implementation issue, where the adapter seed URL and parser signal will be introduced together

## Implementation-ready outcome

ganganonline is implementation-ready for Family B if a follow-up adapter:

- accepts public title URLs and public chapter URLs
- normalizes both to `https://www.ganganonline.com/title/<title_id>`
- derives `work_id = ganganonline:<title_id>`
- derives `latest_key` from the first chapter card without `appLaunchUrl`
- fails loudly when the `__NEXT_DATA__` payload or `chapters[]` contract drifts
- returns a clear blocker when only app-routed newest cards remain

## Evidence captured in this branch

- `tests/fixtures/ganganonline/contract/2250-title.json`
- `tests/fixtures/ganganonline/contract/2250-chapter-121212.json`
- `tests/test_ganganonline_contract.py`
