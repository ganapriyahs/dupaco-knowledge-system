# Dupaco knowledge system: notes

Pure Python standard library. No network calls, no model calls, nothing to install.
`build()` returns an object with `ingest(snapshot)`, `answer(question, as_of=None)` and `conflicts()`.

## How it works

**Snapshots and time.** Every snapshot is kept whole, with its own search index.
`as_of` picks the newest snapshot taken on or before that date; with no `as_of` the
latest snapshot is used. Old values are never mixed into a current answer.

**Chunking.** One chunk per table row (section label + column headers + cells, so a
rate row reads "Auto & Motorcycle Loans | Loan Program: 2024-27 Model Year; Term: 60
Months; ... 5.39%"), one chunk per paragraph. Short paragraphs merge into the next one,
tiny fragments are dropped, and the crawl's `\r\n` junk text is removed.

**Retrieval.** BM25 (written by hand, deterministic tie-breaks) over each snapshot's chunks.
Words are lower-cased, stop words dropped, plurals lightly stripped, and footnote digits
removed ("APR1" matches "apr"). Adjustments on top of the raw score:
- *Page authority:* rate-table pages (`/rates`, `/business-rates`) are boosted for rate
  questions and down-weighted otherwise; calculators count 0.3; blog and news pages count
  0.5 for rate questions (they quote stale rates) and 0.65 otherwise.
- *Names:* a chunk that contains every capitalised name in the question (Visa, Forbes,
  Hy-Vee) gets a 1.6x boost.
- *Hours questions:* only chunks that contain a time of day are candidates.
- *Distinct rates:* for questions that name no dollar amount, rows that repeat a rate
  already picked are skipped, so near-identical rows don't crowd out other tiers.

**Answer.** The top 3 chunks (6 for list questions such as "rates", "cards", "accounts"),
plus the chunk right after the best one (FAQ answers follow their questions), up to 900
characters (1800 for list questions). Sources are the pages those chunks came from.

**Link questions.** An index of every link's anchor text and target is built per snapshot.
Questions about a link/URL/page, or "how do I join/apply/open...", get the best-matching
link targets prepended and cited.

**"I don't know".** The answer is declined (`confident=False`, no numbers) when the best
chunks cannot answer: a rate question whose chosen text contains no percentage, or an
hours question naming a place (a rare word) that none of the chosen chunks mention.

**Conflicts.** `conflicts()` compares table rows across the pages of the newest snapshot.
Rows are keyed by their label cells (plain numbers dropped, dollar-tier cells kept);
model-year ranges like 2023-26 and 2024-27 count as the same product when they overlap
by 3+ years. Pages must share context words. Per fact the winner is the most authoritative
page (the rates table beats calculators and promo pages), then the latest "effective as of"
date. One conflict is reported per fact, listing every disagreeing page.

## Known gaps

- Conflicts that exist only in prose (for example "22 branches" vs "24 branches", or
  Forbes "fourth" vs "fifth") are not detected; only table rows are compared.
- Retrieval is word-based, so questions that rely on meaning rather than shared words
  ("recognition" vs "recognized") can miss; no embeddings are used.
- Some single-fact questions (membership eligibility across Iowa, Illinois and Wisconsin)
  need information from two small chunks and only one is retrieved.
- The "no percentage means decline" rule would wrongly decline a rate question whose
  true answer is a dollar fee; no such case appears in the practice set.
- Tuning constants (boosts, penalties, chunk counts) were chosen against the 40 practice
  questions. I checked that results are stable across nearby values, but they are not
  validated against unseen questions.

## Results on the practice set

Local QA score 0.82, 0 stale-value hits, paraphrase and repeat consistency 1.0,
p95 latency about 0.2 s, ingesting all 5 snapshots takes about 3 s.