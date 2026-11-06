# Dupaco knowledge system

No API keys, no network calls, no third-party packages (standard library only).

## How it works

**Snapshots.** `ingest()` keeps each of the five snapshots whole, as its own
`{url: page}` map, plus a keyword index per snapshot. `answer(q, as_of)` uses the
newest snapshot taken on or before `as_of` (the latest one if no date is given),
so "as of May 2026" questions are answered from the website as it stood then.

**Retrieval.** Pages are cleaned and split into chunks: one per table row (with
its column headers and section label) and one per paragraph. Search is BM25 with
stopword removal and light plural stripping. Ties are broken by position so the
same question always gives the same answer. The answer is the top chunks, plus the
chunk right after the best one (FAQ answers follow their question).

**What counts as current.** Pages are weighted by where they live on the site:
the rates pages (`/rates`, `/business-rates`) are boosted for rate questions;
calculators, blog posts and news releases are down-weighted because they often keep
old numbers. Newer snapshot beats older.

**Conflicts.** `conflicts()` looks at table rows in the newest snapshot. Rows with
the same label (product, tier, term) but different percentages on different pages
are a conflict. The winner is the most authoritative page, and ties go to the
later "effective as of" date. Rows are matched by tier and term, so different
tiers are not reported as conflicts.

## Known gaps
- Questions the site cannot answer ("I don't know") are not handled yet.
- Conflicts in prose (for example branch counts) are not detected, only table rows.