"""Look up a book's BiblioCommons record ID in a library catalog (default: HCLib).

The catalog search API is the one the BiblioCommons website itself calls:
    https://gateway.bibliocommons.com/v2/libraries/<library>/bibs/search
Each search result group has a "representative" record ID, which is the ID the
website's result link points to (https://<library>.bibliocommons.com/v2/record/<id>)
and the ID that stays in the URL after the record page loads.

Matching rules (same as the one-off spreadsheet runs):
  * exact       title matches (ignoring case, punctuation, accents and a leading
                The/A/An, with or without the catalog subtitle) and the catalog
                author includes the book's author last name
  * close       one title is the other plus a subtitle/series part, author matches
  * title_only  exact title but a different author (often an illustrator, editor or
                misspelled name in our data, sometimes a different book entirely)
  * not_found   nothing usable
Print books are preferred when several records match equally well.
"""

import re
import time
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

DEFAULT_LIBRARY = "hclib"
SEARCH_URL = "https://gateway.bibliocommons.com/v2/libraries/{library}/bibs/search"
RECORD_URL = "https://{library}.bibliocommons.com/v2/record/{id}"
SEARCH_PAGE_URL = (
    "https://{library}.bibliocommons.com/v2/search?query={query}&searchType=smart"
)

EXACT = "exact"
CLOSE = "close"
TITLE_ONLY = "title_only"
NOT_FOUND = "not_found"
ERROR = "error"
_RANK = {EXACT: 3, CLOSE: 2, TITLE_ONLY: 1, NOT_FOUND: 0, ERROR: 0}


class CatalogError(Exception):
    """The catalog could not be searched (HTTP error, blocked, bad response)."""


# --------------------------------------------------------------------- matching


def norm(text):
    """Lowercase, strip accents and punctuation, collapse spaces."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"(\d),(\d)", r"\1\2", text)  # 1,001 -> 1001
    text = re.sub(r"['’]", "", text)  # don't -> dont
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_title(text):
    return re.sub(r"^(the|a|an) ", "", norm(text))


def main_title(title):
    """Title without its subtitle: 'Bones: Skeletons and...' -> 'Bones'."""
    return re.split(r"[:(]", title or "", maxsplit=1)[0].strip()


def author_matches(catalog_authors, last_name):
    """True if the book's author last name appears in the catalog author list."""
    authors = norm(" ".join(catalog_authors or []))
    last = re.sub(r"^the ", "", norm(last_name))
    if not last:
        return True
    if last in authors:
        return True
    # "Collard III", "Smith Jr." etc: any longer word of the name is enough
    words = [w for w in last.split() if len(w) >= 4]
    return bool(words) and any(w in authors for w in words)


def title_match(book_title, catalog_title, catalog_subtitle):
    """Return EXACT, CLOSE or None for two titles."""
    nt = norm_title(book_title)
    bt = norm_title(catalog_title)
    bs = norm_title(f"{catalog_title or ''} {catalog_subtitle or ''}")
    if not nt or not bt:
        return None
    if nt in (bt, bs):
        return EXACT
    main = norm_title(main_title(book_title))
    if (
        bt.startswith(nt + " ")
        or nt.startswith(bt + " ")
        or bs.startswith(nt + " ")
        or (len(main) > 3 and main == bt)
    ):
        return CLOSE
    return None


@dataclass
class Match:
    match_type: str
    record_id: str = ""
    title: str = ""
    authors: str = ""
    format: str = ""
    query: str = ""
    error: str = ""


def pick(data, book_title, author_last, allow_title_only=False):
    """Choose the best record from one search response (the API's JSON)."""
    bibs = (data.get("entities") or {}).get("bibs") or {}
    found = {EXACT: [], CLOSE: [], TITLE_ONLY: []}
    for group in (data.get("catalogSearch") or {}).get("results") or []:
        rid = group.get("representative")
        bib = bibs.get(rid)
        if not bib:
            continue
        info = bib.get("briefInfo") or {}
        level = title_match(book_title, info.get("title"), info.get("subtitle"))
        if not level:
            continue
        authors = info.get("authors") or []
        if not author_matches(authors, author_last):
            if not (allow_title_only and level == EXACT):
                continue
            level = TITLE_ONLY
        title = info.get("title") or ""
        if info.get("subtitle"):
            title = f"{title}: {info['subtitle']}"
        found[level].append(
            Match(level, rid, title, "; ".join(authors), info.get("format") or "")
        )
    # A bare series title ("Amulet") equals the main title of every volume
    # ("Amulet: Book One...", "Amulet: Book Nine..."). If the exact matches
    # carry different subtitles we can't tell which volume is meant.
    subtitles = {norm(m.title) for m in found[EXACT]}
    if len(subtitles) > 1 and all(":" in m.title for m in found[EXACT]):
        for m in found[EXACT]:
            m.match_type = CLOSE
        found[CLOSE] = found[EXACT] + found[CLOSE]
        found[EXACT] = []
    for level in (EXACT, CLOSE, TITLE_ONLY):
        if found[level]:
            return next((m for m in found[level] if m.format == "BK"), found[level][0])
    return Match(NOT_FOUND)


def queries_for(title, first, last):
    """Searches to try, in order: the full one first, then looser ones."""
    qs = [
        " ".join(p for p in (title, first, last) if p),
        " ".join(p for p in (title, last) if p),
        title,
    ]
    main = main_title(title)
    if main and main != title and len(main) > 3:
        qs += [f"{main} {last}".strip(), main]
    out = []
    for q in qs:  # drop duplicates, keep order
        if q and q not in out:
            out.append(q)
    return out


# ----------------------------------------------------------------------- client


@dataclass
class Client:
    library: str = DEFAULT_LIBRARY
    delay: float = 0.5  # seconds between requests; be polite to the library
    timeout: float = 20
    session: requests.Session = field(default_factory=requests.Session)
    _last: float = 0.0

    def __post_init__(self):
        origin = f"https://{self.library}.bibliocommons.com"
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; xpreading-catalog-lookup)",
                "Origin": origin,
                "Referer": origin + "/",
            }
        )

    def search(self, query):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = SEARCH_URL.format(library=self.library)
        params = {"query": query, "searchType": "smart", "view": "grouped", "limit": 10}
        last_error = None
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp.json()
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code in (401, 403, 404):
                    break  # retrying won't help
            except (requests.RequestException, ValueError) as e:
                last_error = str(e)
            time.sleep(2 * (attempt + 1))
        raise CatalogError(last_error or "unknown error")

    def lookup(self, title, first, last):
        """Run the searches for one book and return the best Match."""
        best = Match(NOT_FOUND)
        for i, query in enumerate(queries_for(title, first, last)):
            m = pick(self.search(query), title, last, allow_title_only=i >= 2)
            m.query = query
            if m.match_type == EXACT:
                return m
            if _RANK[m.match_type] > _RANK[best.match_type]:
                best = m
        if not best.query:
            best.query = queries_for(title, first, last)[0]
        return best


def record_url(record_id, library=DEFAULT_LIBRARY):
    return RECORD_URL.format(library=library, id=record_id)


def search_page_url(query, library=DEFAULT_LIBRARY):
    return SEARCH_PAGE_URL.format(library=library, query=quote(query))
