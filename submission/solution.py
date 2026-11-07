"""
Knowledge system for the Dupaco snapshots.

Step 17: rate answers show distinct rates (no three copies of the same percentage).
Step 16: hours questions only consider chunks that contain times.
Step 14: link questions are answered from the site's own link text (anchor index).
Step 11: conflicts() compares table rows across pages and trusts the most authoritative page.
Step 18: say "I don't know" when the best chunks cannot answer (no rate shown, or the named branch is missing).
"""
import collections
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(next(d / "harness" for d in Path(__file__).resolve().parents if (d / "harness" / "contract.py").exists())))
from contract import Answer, Conflict, Snapshot, Source  # noqa: E402

WORD = re.compile(r"[a-z0-9$%.]+")
JUNK = re.compile(r"(?:\\+r\\+n)+")

MIN_CHUNK = 40
MERGE_BELOW = 80
TOP_K = 3
MAX_ANSWER = 900
PCT = re.compile(r"\d+(?:\.\d+)?\s*%")
PLAIN_NUM = re.compile(r"\$?\s*[\d,]+(\.\d+)?")
DATE = re.compile(r"effective as of\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
YEARS = re.compile(r"(20\d\d)\s*[–-]\s*(\d\d)\b")
GENERIC = {"loan", "rate", "dupaco", "account"}
LINK = re.compile(r"(?<!!)\[([^\]]{2,80})\]\((https?://[^)\s]+)\)")
BAD_LINK = re.compile(r"/hubfs/|\.(png|jpe?g|svg|gif|pdf|webp)(\?|$)|/tag/|/author/|youtu\.be|facebook|instagram|linkedin|twitter", re.I)
LINK_STOP = {"link", "url", "website", "page", "use", "dupaco", "site", "web", "address"}
LINK_WORDS = {"link", "url", "website", "page", "locator"}
ACTION_WORDS = {"join", "apply", "open", "enroll", "register"}
TIME = re.compile(r"\d{1,2}(:\d\d)?\s*(a\.?m\.?|p\.?m\.?)\b|\bnoon\b", re.I)
HOUR_WORDS = {"hour"}
RATE_WORDS = {"rate", "apr", "apy", "dividend", "yield", "interest"}
DONT_KNOW = "I don't know - the website doesn't list that. Please contact Dupaco directly."
STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "what", "whats", "do", "does", "did",
    "can", "could", "would", "you", "your", "yours", "i", "me", "my", "we", "our", "to", "of",
    "for", "on", "in", "at", "and", "or", "how", "much", "many", "tell", "give", "like", "know",
    "please", "get", "there", "it", "this", "that", "with", "about", "s", "have", "has",
    "general",
}


def tokens(text):
    out = []
    for w in WORD.findall(text.lower()):
        w = w.strip(".")
        if not w or w in STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def clean(md):
    return JUNK.sub(" ", md)


def is_rate_question(question):
    return bool(RATE_WORDS & set(tokens(question)))


def authority(url, rate_question):
    path = url.split("dupaco.com", 1)[-1]
    if path.startswith(("/rates", "/business-rates")):
        return 1.5 if rate_question else 0.5
    if path.startswith(("/calculators", "/business-calculators")):
        return 0.3
    if path.startswith(("/learn", "/newsroom")):
        return 0.5
    return 1.0


def chunk_page(title, md):
    chunks, context, header, para = [], title, None, []

    def flush():
        text = " ".join(para)
        para.clear()
        if len(text) >= MIN_CHUNK:
            chunks.append(f"{title} | {text}")

    for line in clean(md).splitlines():
        line = line.strip()
        if line.startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if header is None:
                header = cells
            else:
                pairs = "; ".join(f"{h}: {c}" for h, c in zip(header, cells))
                chunks.append(f"{context} | {pairs}")
        else:
            header = None
            if not line:
                if len(" ".join(para)) >= MERGE_BELOW:
                    flush()
            else:
                para.append(line)
                if len(line) < 80:
                    context = line
    flush()
    return chunks


def page_date(md):
    """Latest 'effective as of M/D/YYYY' date on a page, as (year, month, day)."""
    ds = [(int(y), int(m), int(d)) for m, d, y in DATE.findall(md)]
    return max(ds) if ds else (0, 0, 0)


def table_rows(md):
    """Yield (context_words, row_key, year_range, percent_text) for each table row that has a percent."""
    context, header = "", None
    for line in clean(md).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            header = None
            if line and len(line) < 80:
                context = line
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if header is None:
            header = cells
            continue
        label_cells = [c for c in cells if not PCT.search(c) and not PLAIN_NUM.fullmatch(c)]
        pct = next((PCT.search(c).group(0).replace(" ", "") for c in cells if PCT.search(c)), None)
        if not pct or not label_cells:
            continue
        label = " | ".join(label_cells).lower()
        m = YEARS.search(label)
        years = (int(m.group(1)), 2000 + int(m.group(2))) if m else None
        ctx = {t for t in tokens(context) if t not in GENERIC}
        yield ctx, YEARS.sub("Y", label), years, pct


def years_match(a, b):
    """Model-year ranges match when identical or overlapping by 3+ years (2023-26 ~ 2024-27)."""
    if a is None or b is None:
        return a == b
    return a == b or min(a[1], b[1]) - max(a[0], b[0]) + 1 >= 3


def short_url(u):
    return u.split("dupaco.com", 1)[-1] or "/"


def find_conflicts(pages):
    """pages: {url: markdown}. One Conflict per table-row fact that pages disagree on."""
    facts = collections.defaultdict(list)
    for url, md in pages.items():
        seen = set()
        for ctx, key, years, pct in table_rows(md):
            if (key, years, pct) in seen:
                continue
            seen.add((key, years, pct))
            facts[key].append((url, ctx, years, pct, authority(url, True), page_date(md)))

    out = []
    for key, entries in facts.items():
        # most trusted page first: higher authority, then later effective date
        entries.sort(key=lambda e: (-e[4], tuple(-x for x in e[5]), e[0]))
        win = entries[0]
        losers = [e for e in entries[1:]
                  if e[0] != win[0] and (e[1] & win[1]) and years_match(e[2], win[2])
                  and float(e[3].strip("%")) != float(win[3].strip("%"))]
        if not losers:
            continue
        if any(win[4] > e[4] for e in losers):
            reason = f"{short_url(win[0])} is the more authoritative page; the others are calculator, promo or secondary pages"
        else:
            reason = f"{short_url(win[0])} has the later 'effective as of' date"
        values = [win[3]] + list(dict.fromkeys(e[3] for e in losers))
        sources = [Source(url=win[0], quote=win[3])] + [Source(url=e[0], quote=e[3]) for e in losers]
        out.append(Conflict(topic=key, values=values, sources=sources, resolution=win[3], reason=reason))
    return out


class LinkIndex:
    """Which pages link where, and with what link text (e.g. 'Become a member' -> join.dupaco.com)."""

    def __init__(self, pages):          # pages: {url: markdown}
        anchors = collections.defaultdict(Counter)
        self.pages = collections.defaultdict(set)
        for url, md in pages.items():
            for text, target in LINK.findall(clean(md)):
                target = target.split('"')[0]
                if target.endswith("#") or BAD_LINK.search(target):
                    continue
                base = target.split("#")[0].split("?")[0].rstrip("/")
                anchors[base][text.lower().strip()] += 1
                self.pages[base].add(url)
        self.toks = {}
        self.df = Counter()
        for base, c in anchors.items():
            t = Counter(w for a, n in c.items() for w in tokens(a) for _ in range(n))
            self.toks[base] = t
            for w in t:
                self.df[w] += 1
        self.n = max(len(self.toks), 1)

    def search(self, question, k=3):
        q = {w for w in tokens(question) if w not in LINK_STOP}
        rate_q = is_rate_question(question)
        scored = []
        for base, t in self.toks.items():
            hit = [w for w in q if w in t]
            if not hit:
                continue
            s = sum(math.log(1 + self.n / self.df[w]) for w in hit) / (1 + 0.15 * len(t)) ** 0.5
            s *= 1 + math.log(len(self.pages[base]))     # linked from many pages = important
            s *= authority(base, rate_q)                 # blog and news targets count less
            scored.append((s, base))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [b for _, b in scored[:k]]


def wants_link(question):
    t = set(tokens(question))
    return bool(t & LINK_WORDS) or (bool(t & ACTION_WORDS) and question.lower().startswith("how"))


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.tf = [Counter(tokens(t)) for _, t in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / max(len(docs), 1)
        df = Counter(w for c in self.tf for w in c)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}
        self.k1, self.b = k1, b

    def search(self, query, k=5, rate_question=False):
        q = tokens(query)
        hours = bool(set(q) & HOUR_WORDS)          # an hours question needs a chunk with times in it
        scored = []
        for i, c in enumerate(self.tf):
            if hours and not TIME.search(self.docs[i][1]):
                continue
            s = 0.0
            for w in q:
                if w in c:
                    f = c[w]
                    norm = 1 - self.b + self.b * self.len[i] / self.avg
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * norm)
            if s > 0:
                s *= authority(self.docs[i][0], rate_question)
                scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[:k]


class Knowledge:
    def __init__(self):
        self.snaps = []
        self.index = {}
        self.links = {}

    def ingest(self, snapshot: Snapshot) -> None:
        pages = {p.url: p for p in snapshot.pages}
        self.snaps.append((snapshot.taken_on, snapshot.snapshot_id, pages))
        docs = []
        for p in snapshot.pages:
            for text in chunk_page(p.title, p.markdown):
                docs.append((p.url, text))
        self.index[snapshot.snapshot_id] = BM25(docs)
        self.links[snapshot.snapshot_id] = LinkIndex({p.url: p.markdown for p in snapshot.pages})

    def site_as_of(self, as_of=None):
        if as_of is None:
            return self.snaps[-1]
        eligible = [s for s in self.snaps if s[0] <= as_of]
        return eligible[-1] if eligible else self.snaps[0]

    def answer(self, question, as_of=None):
        _, sid, _ = self.site_as_of(as_of)
        bm = self.index[sid]
        raw = bm.search(question, k=12, rate_question=is_rate_question(question))
        hits, seen = [], set()
        for s_, i_ in raw:
            m = PCT.search(bm.docs[i_][1])
            key = m.group(0) if m else None
            if key is not None and key in seen and "$" not in question:
                continue          # same rate as a row we already picked: skip it
            if key is not None:
                seen.add(key)
            hits.append((s_, i_))
        hits = hits[:TOP_K]
        if not hits:
            return Answer(text="I don't know.", confident=False)
        best = hits[0][1]
        order = [best]
        if best + 1 < len(bm.docs) and bm.docs[best + 1][0] == bm.docs[best][0]:
            order.append(best + 1)
        for _, i in hits[1:]:
            if i not in order:
                order.append(i)
        text = " ... ".join(bm.docs[i][1] for i in order)[:MAX_ANSWER]
        if self.unsupported(question, bm, order, text):
            return Answer(text=DONT_KNOW, confident=False)
        urls = list(dict.fromkeys(bm.docs[i][0] for i in order))
        if wants_link(question):
            links = self.links[sid].search(question)
            if links:
                text = "Relevant links: " + ", ".join(links) + " ... " + text
                urls = links + [u for u in urls if u not in links]
        return Answer(text=text, sources=[Source(url=u, snapshot_id=sid) for u in urls])

    def unsupported(self, question, bm, order, text):
        """True when the best chunks cannot actually answer: no rate shown, or the named place is missing."""
        q = set(tokens(question))
        if q & RATE_WORDS and not PCT.search(text):
            return True
        if q & HOUR_WORDS:
            body = " ".join(bm.docs[i][1] for i in order).lower()
            rare = [w for w in q if bm.idf.get(w, 0) > 7.5 and w not in HOUR_WORDS]
            if any(w not in body for w in rare):
                return True
        return False

    def conflicts(self):
        _, _, pages = self.snaps[-1]          # contradictions in the newest snapshot
        return find_conflicts({u: p.markdown for u, p in pages.items()})


def build():
    return Knowledge()