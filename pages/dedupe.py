"""
Duplicate-book matching for pages.Book.

Pure matching logic (no database writes). Used by the `dedupe_books`
management command, and usable on its own to check a new title before saving:

    from pages.dedupe import possible_duplicates
    possible_duplicates("The Giver", author_id=429)

Each pair of books gets a reason code and a confidence:
    high     titles match after normalising (punctuation, "The", case...),
             or a subtitle/typo difference backed by a shared ASIN or
             BiblioCommons ID
    medium   strong title evidence but no shared ID
    review   plausible but ambiguous (series name vs book 1, reworded titles)
    not_dup  look-alikes that are separate books (graphic novel editions,
             series siblings, Young Readers editions)
"""
import re
from collections import defaultdict
from itertools import combinations

from rapidfuzz import fuzz
from unidecode import unidecode

HIGH, MED, REVIEW, NOT_DUP = "high", "medium", "review", "not_dup"
RANK = {HIGH: 0, MED: 1, REVIEW: 2, NOT_DUP: 3}
LEVELS = {HIGH: (HIGH,), MED: (HIGH, MED), REVIEW: (HIGH, MED, REVIEW)}

# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
ARTICLES = r"(the|a|an|el|la|los|las)"
LEAD_ART = re.compile(rf"^{ARTICLES}\s+")
TRAIL_ART = re.compile(rf",\s*{ARTICLES}\s*$", re.I)  # "Lion of Mars, The"
BYLINE = re.compile(r"\s+by\s+[A-Z][\w.'-]+(\s+[A-Z][\w.'-]+){1,3}\s*$")
SUB_SPLIT = re.compile(
    r"\s*[:(\[]\s*|\s+[-–—]{1,2}\s+|\s*/\s*|\s*;\s*|,?\s+(?=and other\b)", re.I
)
BILING = re.compile(r"\s*/\s*|\s*=\s*")
ELLIPSIS = re.compile(r"(…|\.\.\.)\s*$")
ROMAN = {"ii", "iii", "iv", "vi", "vii", "viii", "ix"}
EDITION = re.compile(
    r"graphic novel|young readers?'?s?|picture book|adaptation|edition|"
    r"\bvol(ume)?\b|\bbook\s*\d|\bpart\s*\d|\bomnibus\b|boxed set|"
    r"en espa[nñ]ol|spanish edition|anniversary|illustrated edition|abridged|unabridged",
    re.I,
)


def l1(t):
    return re.sub(r"\s+", " ", str(t)).strip().casefold()


def l2(t):
    t = unidecode(str(t)).lower()
    t = t.replace("&", " and ").replace("+", " and ")
    t = re.sub(r"\b'til\b|\btil\b", "till", t)
    t = re.sub(r"\b(number|no\.?)\s+(?=\d)", "", t)
    t = re.sub(r"['`‘’]", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def l3(t):
    t = TRAIL_ART.sub("", str(t))
    return LEAD_ART.sub("", l2(t))


def split_title(t):
    parts = SUB_SPLIT.split(str(t).strip(), maxsplit=1)
    main = parts[0]
    sub = parts[1].rstrip(")]").strip() if len(parts) > 1 else ""
    return main, sub


def nums(t):
    return {x for x in l2(t).split() if x.isdigit() or x in ROMAN}


def norm_asin(a):
    a = (a or "").strip().upper()
    if re.fullmatch(r"[0-9]{1,9}X?", a) and len(a) < 10:  # ISBN-10 lost leading zeros
        a = a.zfill(10)
    return a


def prep(r):
    """r: dict with id, title, author_id, illustrator_id, asin, bibliocommons_id."""
    t = r["title"] or ""
    main, sub = split_title(t)
    return dict(
        r,
        _l1=l1(t), _l2=l2(t), _ns=l2(t).replace(" ", ""), _l3=l3(t),
        _by=l3(BYLINE.sub("", t)),
        _main=l3(main), _sub=l2(sub), _sub_raw=sub,
        _after=l3(sub) if ":" in t else "",
        _nums=nums(t), _main_nums=nums(main),
        _parts={l3(p) for p in BILING.split(t) if l3(p)} if BILING.search(t) else set(),
        _asin=norm_asin(r.get("asin")),
        _bc=(r.get("bibliocommons_id") or "").strip().upper(),
        _author=r.get("author_id"),
        _ill=r.get("illustrator_id"),
        _trunc=bool(ELLIPSIS.search(t)),
    )


# --------------------------------------------------------------------------
# Pair classification
# --------------------------------------------------------------------------
def corroboration(a, b):
    c = []
    if a["_asin"] and a["_asin"] == b["_asin"]:
        c.append("same_asin")
    if a["_bc"] and a["_bc"] == b["_bc"]:
        c.append("same_bibliocommons")
    if a["_ill"] and a["_ill"] == b["_ill"]:
        c.append("same_illustrator")
    return c


def title_reason(a, b, series_mains):
    if a["title"] == b["title"]:
        return "EXACT_TITLE", HIGH
    if a["_l1"] == b["_l1"]:
        return "CASE_WHITESPACE", HIGH
    if a["_l2"] == b["_l2"]:
        return "PUNCTUATION_ACCENTS_AMPERSAND", HIGH
    if a["_ns"] == b["_ns"]:
        return "WORD_SPACING", HIGH
    if a["_l3"] == b["_l3"]:
        return "LEADING_OR_TRAILING_ARTICLE", HIGH
    if a["_by"] == b["_by"]:
        return "AUTHOR_NAME_IN_TITLE", HIGH

    if a["_main"] and a["_main"] == b["_main"]:
        sa, sb = a["_sub"], b["_sub"]
        longer = a if len(sa) > len(sb) else b
        if EDITION.search(a["_sub_raw"] + " " + b["_sub_raw"]):
            return "EDITION_VARIANT", NOT_DUP
        if a["_main_nums"] != b["_main_nums"]:
            return "NUMBERED_SERIES_ENTRY", NOT_DUP
        if not sa or not sb:
            if (a["_author"], a["_main"]) in series_mains:
                return "SERIES_NAME_VS_ENTRY", REVIEW
            return "SUBTITLE_MISSING", MED
        if longer["_trunc"] or sa.startswith(sb) or sb.startswith(sa):
            return "SUBTITLE_TRUNCATED", MED
        if fuzz.ratio(sa, sb) >= 75 or fuzz.token_set_ratio(sa, sb) >= 85:
            return "SUBTITLE_WORDING_VARIANT", MED
        return "DIFFERENT_SUBTITLES", NOT_DUP

    for x, y in ((a, b), (b, a)):
        if x["_parts"] and y["_l3"] in x["_parts"]:
            return "BILINGUAL_HALF_TITLE", MED
    for x, y in ((a, b), (b, a)):
        if x["_after"] and x["_after"] == y["_l3"]:
            return "SERIES_NAME_PREFIX", MED
    for x, y in ((a, b), (b, a)):
        if x["_trunc"] and y["_l2"].startswith(x["_l2"]):
            return "TITLE_TRUNCATED", MED

    if a["_nums"] != b["_nums"]:
        return None
    r = fuzz.ratio(a["_l3"], b["_l3"])
    if r >= 85:
        ta, tb = set(a["_l3"].split()), set(b["_l3"].split())
        da, db = sorted(ta - tb), sorted(tb - ta)
        near = da and db and all(max(fuzz.ratio(w, v) for v in db) >= 70 for w in da)
        if near or not da or not db:
            short = min(len(a["_l3"]), len(b["_l3"])) < 8
            return "SPELLING_TYPO", (MED if r >= 93 and not short else REVIEW)
        return "SIMILAR_TITLE_DIFFERENT_WORD", "needs_id"
    if a["_main"] and b["_main"] and fuzz.ratio(a["_main"], b["_main"]) >= 90 and (
        not a["_sub"] or not b["_sub"] or fuzz.ratio(a["_sub"], b["_sub"]) >= 85
    ):
        return "SPELLING_TYPO_PLUS_SUBTITLE", REVIEW
    return None


def classify(a, b, series_mains=frozenset()):
    """Return {reason, confidence, corroboration} or None if unrelated."""
    tr = title_reason(a, b, series_mains)
    corr = corroboration(a, b)
    id_corr = [c for c in corr if c != "same_illustrator"]
    same_author = a["_author"] == b["_author"]

    if tr is None:
        if id_corr and same_author and fuzz.token_set_ratio(a["_l3"], b["_l3"]) >= 80:
            tr = ("REWORDED_TITLE_SAME_ID", "review_fixed")
        else:
            return None
    reason, conf = tr

    if conf == "needs_id":  # one real word swapped: a series sibling unless IDs agree
        conf = REVIEW if id_corr else NOT_DUP
    if conf == NOT_DUP and reason == "EDITION_VARIANT" and id_corr:
        reason, conf = "EDITION_OR_VOLUME_MARKER_SAME_ID", REVIEW
    if reason == "SERIES_NAME_VS_ENTRY" and id_corr:
        reason, conf = "SUBTITLE_MISSING", MED

    if conf == NOT_DUP:
        return dict(reason=reason, confidence=NOT_DUP, corroboration=";".join(corr))

    if conf == "review_fixed":
        conf = REVIEW
    elif id_corr and conf in (MED, REVIEW) and reason not in (
        "SERIES_NAME_VS_ENTRY", "EDITION_OR_VOLUME_MARKER_SAME_ID", "SIMILAR_TITLE_DIFFERENT_WORD"
    ):
        conf = HIGH if conf == MED else MED

    if not same_author:
        if not corr and reason != "EXACT_TITLE":
            return None  # same title, different author, nothing in common: different books
        reason = "DIFFERENT_AUTHOR_ID+" + reason
        conf = MED if (conf == HIGH and id_corr) else REVIEW

    return dict(reason=reason, confidence=conf, corroboration=";".join(corr))


# --------------------------------------------------------------------------
# Whole-catalogue search + grouping
# --------------------------------------------------------------------------
def _series_mains(rows):
    subs = defaultdict(set)
    for r in rows:
        subs[(r["_author"], r["_main"])].add(r["_sub"])

    def distinct(v):
        v = sorted(v - {""})
        return any(
            fuzz.ratio(x, y) < 75 and not (x.startswith(y) or y.startswith(x))
            for x, y in combinations(v, 2)
        )

    return {k for k, v in subs.items() if distinct(v)}


def find_pairs(records):
    """records: iterable of dicts (see prep). Returns (prepped_rows, pairs)."""
    rows = [prep(r) for r in records]
    by_id = {r["id"]: r for r in rows}
    series_mains = _series_mains(rows)

    cand = set()

    def block(key_fn):
        blk = defaultdict(list)
        for r in rows:
            k = key_fn(r)
            if k:
                blk[k].append(r["id"])
        for ids in blk.values():
            if 1 < len(ids) < 200:
                cand.update(tuple(sorted(p)) for p in combinations(ids, 2))

    block(lambda r: r["_author"])  # everything by the same author
    block(lambda r: r["_l3"])  # cross-author: same normalised title
    block(lambda r: r["_main"] if len(r["_main"]) > 3 else None)
    block(lambda r: r["_asin"])
    block(lambda r: r["_bc"])

    pairs = []
    for i, j in cand:
        res = classify(by_id[i], by_id[j], series_mains)
        if res:
            pairs.append(dict(id_a=i, id_b=j, **res))
    return rows, pairs


def group_pairs(pairs, confidence=HIGH):
    """Union-find the pairs at or above `confidence` into groups of book ids.

    Returns a list of dicts: {ids, confidence, reasons}."""
    include = LEVELS[confidence]
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = [p for p in pairs if p["confidence"] in include]
    for p in edges:
        parent[find(p["id_a"])] = find(p["id_b"])
    members, edge_by_root = defaultdict(set), defaultdict(list)
    for p in edges:
        root = find(p["id_a"])
        members[root].update((p["id_a"], p["id_b"]))
        edge_by_root[root].append(p)
    out = []
    for root, ids in members.items():
        ge = edge_by_root[root]
        out.append(dict(
            ids=sorted(ids),
            confidence=max((p["confidence"] for p in ge), key=RANK.get),
            reasons=sorted({p["reason"] for p in ge}),
        ))
    return out


def possible_duplicates(title, author_id, illustrator_id=None, asin="", bibliocommons_id="",
                        exclude_id=None, confidence=MED):
    """Check one (unsaved) book against the catalogue. Returns a list of
    (Book, reason, confidence), best matches first."""
    from django.db.models import Q

    from pages.models import Book

    new = prep(dict(id=None, title=title, author_id=author_id, illustrator_id=illustrator_id,
                    asin=asin, bibliocommons_id=bibliocommons_id))
    q = Q(author_id=author_id)
    if new["_asin"]:
        q |= Q(asin__iexact=new["_asin"]) | Q(asin__iexact=new["_asin"].lstrip("0"))
    if new["_bc"]:
        q |= Q(bibliocommons_id__iexact=new["_bc"])
    first_word = new["_main"].split(" ")[0] if new["_main"] else ""
    if len(first_word) > 3:
        q |= Q(title__icontains=first_word)
    qs = Book.objects.filter(q)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    hits = []
    for b in qs.only("id", "title", "author_id", "illustrator_id", "asin", "bibliocommons_id"):
        other = prep(dict(id=b.id, title=b.title, author_id=b.author_id,
                          illustrator_id=b.illustrator_id, asin=b.asin,
                          bibliocommons_id=b.bibliocommons_id))
        res = classify(new, other)
        if res and res["confidence"] in LEVELS[confidence]:
            hits.append((b, res["reason"], res["confidence"]))
    return sorted(hits, key=lambda h: RANK[h[2]])
