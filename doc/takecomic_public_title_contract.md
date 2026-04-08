# takecomic.jp public title/work contract

Issue: #203
Observed: 2026-04-08 JST

## Summary

`takecomic.jp` can be treated as a Family B host whose canonical seed is the public series page:

- `https://takecomic.jp/series/<series_hash>`

The historical root `https://mangalifewin.takeshobo.co.jp/` now redirects to `https://takecomic.jp/`, which is enough to establish the service-level successor mapping. That historical root redirect does not, by itself, identify a specific work seed.

The current public series page exposes enough information to define a stable normalize contract and a latest detection contract without login, browser automation, or private APIs.

## Historical/current mapping

- Observed on 2026-04-08:
  - `https://mangalifewin.takeshobo.co.jp/` returns `302`
  - redirect target: `https://takecomic.jp/`
  - final landing page canonical: `https://takecomic.jp`

Decision:

- historical bare-root input proves the domain successor mapping from `mangalifewin.takeshobo.co.jp` to `takecomic.jp`
- historical bare-root input is not an accepted canonical work seed
- work-level normalization still needs a current `takecomic.jp/series/<series_hash>` URL

## Accepted input URL

- Accepted now: public series URL
  - Example: `https://takecomic.jp/series/a3c3f4363f8d5`
- Not accepted yet in this issue:
  - landing page URLs such as `https://takecomic.jp/`
  - RSS URLs such as `https://takecomic.jp/series/<series_hash>/rss`
  - episode URLs such as `https://takecomic.jp/episodes/<episode_id>/`
  - bare historical root `https://mangalifewin.takeshobo.co.jp/`

## Canonical seed

- Canonical seed: `https://takecomic.jp/series/<series_hash>`
- The public series page exposes a canonical `<link rel="canonical">` that matches the series URL.

## Stable identifier

- `work_id` rule: `takecomic:<series_hash>`
- Evidence on `https://takecomic.jp/series/a3c3f4363f8d5`:
  - the existing takecomic adapter and fixtures already key the work by `series_hash`
  - canonical URL carries the same public `series_hash`
  - the public Next payload also repeats a numeric `series.indexId` of `15055`
  - the same payload also exposes `series.name`, `updatedOn`, and `numEpisodes`

This preserves backward compatibility with the current runtime/state contract while keeping the accepted seed on the public series URL. `series.indexId` remains useful as corroborating metadata, but not as the primary `work_id`.

## Latest detection contract

The public series page exposes a latest marker in the Next payload:

- `lastEpisode.id`
- `lastEpisode.title`
- `lastEpisode.datePublished`

Rule:

1. Parse the public series page.
2. Read `lastEpisode.id` from the public payload.
3. Build the normalized latest episode URL as:
   - `https://takecomic.jp/episodes/<lastEpisode.id>`

For `https://takecomic.jp/series/a3c3f4363f8d5`, the observed latest public episode on 2026-04-08 was:

- `lastEpisode.id`: `110db269ebfe8`
- `lastEpisode.title`: `5話`
- `latest_key`: `https://takecomic.jp/episodes/110db269ebfe8`

## RSS corroboration

The public series page links to an RSS feed at:

- `https://takecomic.jp/series/<series_hash>/rss`

For the representative series:

- RSS self URL: `https://takecomic.jp/series/a3c3f4363f8d5/rss`
- latest item guid: `110db269ebfe8`
- latest item link: `https://takecomic.jp/episodes/110db269ebfe8/?utm_source=rss&utm_medium=referral`

The RSS latest item matches the series-page `lastEpisode.id` after normalizing away the RSS tracking query string and removing the optional trailing slash. This makes RSS a useful corroborating surface, but not a required seed surface.

## Non-authoritative signals

These signals are useful for display or future canaries, but should not be the primary latest key:

- schedule label such as `水曜更新`
- landing page featured-series links
- thumbnail image URLs under `cdn-public.comici.jp`

## Implementation-ready outcome

takecomic is implementation-ready for Family B if a follow-up adapter:

- accepts only `https://takecomic.jp/series/<series_hash>` seeds
- records the historical domain successor note from `mangalifewin.takeshobo.co.jp` to `takecomic.jp`
- preserves `work_id = takecomic:<series_hash>` for backward compatibility
- derives `latest_key = https://takecomic.jp/episodes/<lastEpisode.id>`
- optionally cross-checks the public RSS item for the same latest episode id

## Evidence captured in this branch

- `tests/fixtures/takecomic/contract/historical_root_redirect.json`
- `tests/fixtures/takecomic/contract/series_a3c3f4363f8d5.json`
- `tests/test_takecomic_contract.py`
