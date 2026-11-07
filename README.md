# Dupaco Knowledge System

A question-answering system that reads repeated crawls of a credit union's website and answers like a careful human expert: the **current** value, the **right tier**, a **source**, and an honest **"I don't know"** when the site doesn't say.

Pure Python standard library. No model calls, no network calls, nothing to install. Answers come back in about 0.2 seconds.

| Practice-set result | |
|---|---|
| QA score | **0.82** (started at 0.09) |
| Stale or wrong-tier values returned | **0** |
| Reworded-question and repeat consistency | **1.0 / 1.0** |
| p95 answer latency | **~0.2 s** |
| Time to ingest all 5 snapshots (~3,300 pages) | **~3 s** |

> Scores are from the 40 public practice questions with the kit's own scorer. The hidden question set may differ.

---

## The problem

The website is downloaded again and again; each download is a **snapshot**. Websites are messy, and a naive system gives wrong answers:

- A rate changes, but an old page still shows the old number.
- A table has tiers (by balance, by term, by model year), and reading it carelessly mixes them up.
- Blog posts and calculators quote old or example rates next to the real rate table.
- Sometimes the site simply doesn't say, and the right answer is "I don't know".

## Architecture

```
   Snapshot 1 (May)    Snapshot 2    Snapshot 3    Snapshot 4    Snapshot 5 (Sep, latest)
         |                  |             |             |                 |
         +------------------+------+------+-------------+-----------------+
                                   |
                                   v
              +------------------------------------------------+
              |  ingest(snapshot)   runs once per snapshot     |
              |                                                |
              |   1. Chunk every page                          |
              |        one chunk per table row                 |
              |        one chunk per paragraph                 |
              |   2. Build a BM25 search index                 |
              |   3. Build a link index                        |
              |        (anchor text -> target URL)             |
              +------------------------+-----------------------+
                                       |
                                       v
              +------------------------------------------------+
              |  Knowledge store: ONE separate index           |
              |  per snapshot, never merged                    |
              +----------+----------------------------+--------+
                         |                            |
                         v                            v
        +-------------------------------+  +---------------------------------+
        |  answer(question, as_of)      |  |  conflicts()                    |
        |                               |  |                                 |
        |  returns: text, sources,      |  |  returns: topic, values,        |
        |  confident                    |  |  sources, resolution, reason    |
        +-------------------------------+  +---------------------------------+
```

`as_of` selects the newest snapshot taken on or before that date, and with no `as_of` the latest snapshot is used. Because snapshots are never merged, an old value cannot leak into a current answer.

## How a question is answered

```
                          Question (+ optional as_of)
                                      |
                                      v
                    +------------------------------------+
                    | 1. Pick the snapshot               |
                    |    newest one taken <= as_of       |
                    +-----------------+------------------+
                                      |
                                      v
                    +------------------------------------+
                    | 2. Tokenise                        |
                    |    drop stop words, strip plurals, |
                    |    strip footnote digits           |
                    |    ("APR1" becomes "apr")          |
                    +-----------------+------------------+
                                      |
                                      v
                          +-----------------------+
                          | Hours question?       |
                          +-----+-----------+-----+
                            yes |           | no
                                v           |
              +----------------------+      |
              | keep only chunks     |      |
              | that contain a time  |      |
              | of day               |      |
              +----------+-----------+      |
                         |                  |
                         +--------+---------+
                                  |
                                  v
                    +------------------------------------+
                    | 3. Score every chunk with BM25     |
                    +-----------------+------------------+
                                      |
                                      v
                    +------------------------------------+
                    | 4. Adjust each score               |
                    |                                    |
                    |  page authority                    |
                    |    rate tables UP for rate Qs      |
                    |    blog / news / calculators DOWN  |
                    |  name boost                        |
                    |    chunk mentions every            |
                    |    capitalised name in the Q       |
                    +-----------------+------------------+
                                      |
                                      v
                    +------------------------------------+
                    | 5. Choose chunks                   |
                    |    skip rows that repeat a rate    |
                    |    already picked (unless the Q    |
                    |    names a dollar tier)            |
                    |    keep top 3  (6 for list Qs)     |
                    |    + the chunk right after the     |
                    |      best one                      |
                    +-----------------+------------------+
                                      |
                                      v
                       +-----------------------------+
                       | Can these chunks actually   |
                       | answer the question?        |
                       +---+-------------------+-----+
                       no  |                   | yes
                           v                   v
         +-------------------------+   +--------------------------+
         | "I don't know"          |   | Link question?           |
         | confident = False       |   |   yes: prepend the best  |
         | no numbers in the text  |   |   matching link targets  |
         +-------------------------+   +------------+-------------+
          triggers:                                 |
           - rate question, no                      v
             percentage in the text       +--------------------------+
           - hours question about a       | Answer + cited sources   |
             place the chunks never       +--------------------------+
             mention
```

### The decisions that mattered most

| Decision | Why |
|---|---|
| One chunk per **table row**, prefixed with the section label and column headers | A row such as "Auto and Motorcycle Loans, 2024-27 Model Year, 60 Months, 5.39%" is self-contained, so the right tier can be retrieved on its own. |
| Page-authority weights from real URL paths | The `/rates` tables are the source of truth for rate questions. Blog posts, news and calculators repeat stale or example numbers. |
| Skip repeated rates when picking chunks | Near-identical rows would otherwise fill every slot with the same rate and hide other tiers. |
| Decline when the evidence can't answer | A rate question whose chosen text contains no percentage, or an hours question about a place the chunks never mention, is better answered with "I don't know" than with a nearby number. |
| One index per snapshot | Time-aware answers with zero cross-contamination. |

## How conflicts are found

```
              Newest snapshot, every page
                          |
                          v
        +------------------------------------+
        | Read every table row that has a    |
        | percentage                         |
        +-----------------+------------------+
                          |
                          v
        +------------------------------------+
        | Key each row by its label cells    |
        |   plain numbers dropped            |
        |   dollar-tier cells KEPT           |
        |   model-year ranges normalised     |
        +-----------------+------------------+
                          |
                          v
        +------------------------------------+
        | Group rows with the same key       |
        | across different pages             |
        +-----------------+------------------+
                          |
                          v
            +-------------------------------+
            | Same context words, years     |
            | overlap, percentage differs?  |
            +------+----------------+-------+
              no   |                | yes
                   v                v
        +----------------+  +----------------------------------+
        | Not a conflict |  | Rank the pages                   |
        +----------------+  |   1. page authority              |
                            |      (rate tables beat           |
                            |       calculators and promos)    |
                            |   2. latest "effective as of"    |
                            |      date                        |
                            +----------------+-----------------+
                                             |
                                             v
                            +----------------------------------+
                            | One Conflict per fact:           |
                            |   every disagreeing value        |
                            |   every page that holds it       |
                            |   the winner, and the reason     |
                            +----------------------------------+
```

Tier cells are kept in the key so that different balance tiers are never reported as a contradiction. Model-year ranges such as 2023-26 and 2024-27 are treated as the same product when they overlap by three years or more.

## How the score improved

Each step was measured against the practice set before it was kept. Several ideas were tried and **rejected** because they scored worse or triggered stale-value hits (for example a boost for any chunk containing a percentage, and answering with five chunks).

| Step | What changed | QA score |
|---|---|---|
| Baseline | Starter solution | 0.09 |
| Per-snapshot indexes | Answers come from the right point in time | 0.13 |
| Row and paragraph chunking with BM25 | Table rows become self-contained chunks | 0.26 |
| Page-authority weighting and tuning | Rate tables beat blogs, news and calculators | 0.49 |
| Link questions | Anchor-text index for "where do I..." questions | 0.52 |
| Hours filter | Hours questions only consider chunks with times | 0.60 |
| Distinct rates | Near-identical rows no longer crowd out other tiers | 0.65 |
| "I don't know" rules | Decline when the evidence can't answer | 0.74 |
| Footnote-digit fix | "APR1" now matches "apr" | 0.76 |
| Wider list answers | 6 chunks for "rates", "cards", "accounts" | 0.79 |
| Softer news penalty for non-rate questions | Press releases can answer entity questions | 0.81 |
| Name boost | Capitalised names in the question must appear | **0.82** |

Conflict detection is scored as a separate pillar, so it does not appear in this QA column.

## Known limits

Listed honestly, and also in [`submission/NOTES.md`](submission/NOTES.md):

- Answers are built from the top few chunks rather than a single extracted value. On the practice set this returned zero stale values, but a chunk with a correct answer could in principle sit beside a stale number on a larger question set.
- Conflicts that exist **only in prose** (for example "22 branches" versus "24 branches") are not detected. Only table rows are compared.
- Retrieval is word-based, so questions that rely on meaning rather than shared words ("recognition" versus "recognized") can miss. No embeddings are used.
- A few facts are spread across two small chunks and only one is retrieved (for example the states in the membership area).
- The "no percentage means decline" rule would wrongly decline a rate question whose true answer is a dollar fee. No such case appears in the practice set.
- Tuning constants were chosen against the 40 practice questions. Nearby values give the same results, but they are not validated on unseen questions.

## Run it

Requires Python 3.9 or newer. Python 3.11 and 3.13 were both tested.

```bash
# from the top folder, with the snapshot zips in snapshots_zip/
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

Optionally check conflict scoring against a gold list:

```bash
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl --conflicts-gold mini_gold.json
```

## Repository layout

```
submission/solution.py    the whole system (build, ingest, answer, conflicts)
submission/NOTES.md       design notes and known gaps
submission/requirements.txt
harness/                  the scorer supplied with the assignment
eval/public_eval.jsonl    the 40 practice questions
```

Website snapshots and API keys are intentionally not in the repository.
