"""Deterministic matching of extracted entries against the existing database."""

import re
from collections import defaultdict

from unidecode import unidecode

_ARTICLES = re.compile(r"^(the|a|an|el|la|los|las|le|les)\s+")


def norm(text):
    text = unidecode(text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


def title_keys(title):
    """Full normalized title and the part before a subtitle colon/dash."""
    full = _ARTICLES.sub("", norm(title))
    keys = {full} if full else set()
    main = re.split(r"\s*[:—–(]\s*|\s+-\s+", title or "", maxsplit=1)[0]
    main_n = _ARTICLES.sub("", norm(main))
    if main_n and len(main_n) >= 4:
        keys.add(main_n)
    return keys


def primary_key(title):
    return _ARTICLES.sub("", norm(title))[:255]


def last_name_tokens(last_name):
    """'Black & Clare' -> {'black','clare'}; "O'Shaughnessy" -> {'oshaughnessy'}."""
    parts = re.split(r"\s*(?:&|\band\b|,)\s*", last_name or "")
    toks = set()
    for p in parts:
        n = norm(p)
        if n:
            toks.add(n)
            toks.add(n.split()[-1])  # "Van Allsburg" also matches "allsburg"
    return toks


def names_overlap(a_tokens, b_tokens):
    if a_tokens & b_tokens:
        return True
    # tolerate "DiCamillo" vs "Di Camillo" style differences
    a = {t.replace(" ", "") for t in a_tokens}
    b = {t.replace(" ", "") for t in b_tokens}
    return bool(a & b)


class MatchIndex:
    """In-memory index of books and category memberships (fits easily: ~15k books)."""

    def __init__(self, books, memberships):
        """books: iterable of (book_id, title, author_last, author_first, illustrator_last)
        memberships: iterable of (book_id, category_id, year)
        """
        self.by_key = defaultdict(list)
        self.book_info = {}
        for book_id, title, a_last, a_first, i_last in books:
            info = {
                "id": book_id,
                "title": title,
                "creators": last_name_tokens(a_last) | last_name_tokens(i_last),
                "author": f"{a_first or ''} {a_last or ''}".strip(),
            }
            self.book_info[book_id] = info
            for k in title_keys(title):
                self.by_key[k].append(book_id)
        self.cat_years = defaultdict(lambda: defaultdict(set))  # cat -> book -> {years}
        for book_id, cat_id, year in memberships:
            self.cat_years[cat_id][book_id].add(year)

    @classmethod
    def from_db(cls):
        from pages.models import Book, BookCategory

        books = Book.objects.values_list(
            "id",
            "title",
            "author__last_name",
            "author__first_name",
            "illustrator__last_name",
        )
        memberships = BookCategory.objects.values_list("book_id", "category_id", "year")
        return cls(books, memberships)

    def candidates(self, title):
        seen, out = set(), []
        keys = title_keys(title)
        full = primary_key(title)
        # full-title hits first, then main-title hits
        for k in [full] + sorted(keys - {full}):
            for b in self.by_key.get(k, []):
                if b not in seen:
                    seen.add(b)
                    out.append(b)
        return out

    def classify(self, category_id, year, title, creator_last_names):
        """Return dict(status, book_id, notes).

        status: 'already_listed' | 'existing_book' | 'new_book' | 'check'
        """
        creators = set()
        for ln in creator_last_names:
            creators |= last_name_tokens(ln)
        cands = self.candidates(title)
        in_cat = self.cat_years.get(category_id, {})

        # Same book already in this category?
        for b in cands:
            if b in in_cat:
                info = self.book_info[b]
                if not creators or names_overlap(creators, info["creators"]):
                    if year in in_cat[b]:
                        return {"status": "already_listed", "book_id": b, "notes": ""}
                    years = ", ".join(str(y) for y in sorted(in_cat[b]))
                    return {
                        "status": "check",
                        "book_id": b,
                        "notes": (
                            f"This book is already in this category under year {years}, "
                            f"Wikipedia lists it for {year}. Approve to add the {year} entry "
                            f"too, or fix the existing entry's year and reject this."
                        ),
                    }

        author_matches = [
            b
            for b in cands
            if creators and names_overlap(creators, self.book_info[b]["creators"])
        ]
        if author_matches:
            # Prefer exact full-title match, then the book in the most categories.
            full = primary_key(title)
            author_matches.sort(
                key=lambda b: (
                    primary_key(self.book_info[b]["title"]) != full,
                    -sum(1 for c in self.cat_years if b in self.cat_years[c]),
                )
            )
            return {
                "status": "existing_book",
                "book_id": author_matches[0],
                "notes": "",
            }
        if cands:
            others = "; ".join(
                f"#{b} '{self.book_info[b]['title']}' by {self.book_info[b]['author']}"
                for b in cands[:3]
            )
            return {
                "status": "check",
                "book_id": None,
                "notes": f"Similar title already exists with a different author: {others}. "
                f"Set 'Matched book' to link it, or approve as a new book.",
            }
        return {"status": "new_book", "book_id": None, "notes": ""}

    def add_membership(self, book_id, category_id, year):
        self.cat_years[category_id][book_id].add(year)
