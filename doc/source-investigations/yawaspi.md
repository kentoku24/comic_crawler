# yawaspi.com investigation

Issue: #201

Captured evidence date: 2026-04-08

## Decision

`yawaspi.com` is implementation-ready for a follow-up source-adapter issue.

- accepted input URL: public work page `https://yawaspi.com/<slug>/index.html`
- canonical seed: the same public work page URL exposed in `meta[property="og:url"]`
- work_id: `yawaspi:<slug>`
- latest_key: the first main-story comic URL under `/<slug>/comic/*.html`, skipping `sp*.html` promo / special entries

The public series catalog at `https://yawaspi.com/series/index.html` is useful for discovery, but it does not need to be accepted as a watchlist seed for the first implementation lane.

## Evidence

- `tests/fixtures/yawaspi/investigation_contract/01-series.html` shows the catalog links to per-work pages shaped as `/<slug>/index.html`.
- `tests/fixtures/yawaspi/investigation_contract/02-itsuwari-work.html` shows a simple work page whose top `page__read` card is the latest main-story comic URL.
- `tests/fixtures/yawaspi/investigation_contract/03-yakutohi-work.html` shows a mixed page where the newest entry is a promo card `comic/sp001_001.html`, and the latest main-story candidate is the next non-`sp` card `comic/005_001.html`.

## Contract notes

- Public source of truth should be the work page, not the catalog.
- Work pages expose a stable slug-scoped seed through `og:url`.
- Work pages list comic entries newest-first in both the update list and `page__read` card section.
- Promo / announcement entries use `comic/sp*.html` and must not become `latest_key`.
- If a work page has no non-`sp` comic entry, the future adapter should fail loudly instead of silently treating promo content as the latest episode.

## Follow-up implementation lane

- Normalize only public work page URLs in the first pass.
- Reject catalog URLs and other surface types as unsupported URL types until a separate issue widens accepted inputs.
- Fixture / parser tests should cover at least:
  - newest card is immediately usable (`itsuwari`)
  - newest card is promo content and must be skipped (`yakutohi`)
  - missing non-`sp` comic entry fails parse
