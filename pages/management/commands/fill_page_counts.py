"""Look up page counts for books that don't have one, and fill them in.

Usage:
    python manage.py fill_page_counts                 # look up + save
    python manage.py fill_page_counts --dry-run       # look up and print results, save nothing
    python manage.py fill_page_counts --limit 20
    python manage.py fill_page_counts --id 19340 --id 19345
    python manage.py fill_page_counts --use-amazon    # also try ASINDATAAPI (paid)

Sources, tried in order until one gives a believable number:
    1. BiblioCommons record (when the book has a bibliocommons_id)
    2. Open Library by ISBN, then Google Books by ISBN (when the book has an isbn)
    3. Open Library title + author search
    4. Google Books title + author search
    5. Amazon via the existing ASINDATAAPI service (only with --use-amazon)

Search results are only accepted when the author's last name matches and the
title is a close match, so a wrong book doesn't sneak in. Optional settings /
env vars: GOOGLE_BOOKS_API_KEY (raises Google's quota), BIBLIOCOMMONS_LIBRARY
(subdomain, default "hclib").
"""

import difflib
import json
import os
import re
import time
import unicodedata

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from pages.models import Book

USER_AGENT = "xpreading-page-count-lookup/1.0 (https://github.com/edkohler/xpreading)"
MIN_PAGES = 10
MAX_PAGES = 2500

# "262 pages", "xii, 262 p.", "262 unnumbered pages", "1 volume (262 pages)"
PAGES_RE = re.compile(
    r"(?<![\d-])(\d{2,4})\s*(?:\[\d+\]\s*)?(?:unnumbered\s+)?(?:pages?|p\.|pp\.)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- helpers ---


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"^(the|a|an) ", "", text.strip())
    return re.sub(r"\s+", " ", text).strip()


def main_title(title):
    """Drop a subtitle: 'Lamb: The Gospel According to Biff' -> 'Lamb'."""
    return re.split(r"[:(]", title or "", maxsplit=1)[0]


def titles_match(ours, theirs):
    a, b = normalize(ours), normalize(theirs)
    if not a or not b:
        return False
    if a == b:
        return True
    a_main, b_main = normalize(main_title(ours)), normalize(main_title(theirs))
    if a_main and a_main == b_main:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def author_matches(last_name, author_names):
    target = normalize(last_name)
    if not target:
        return True
    return any(target in normalize(name) for name in author_names or [])


def pages_from_text(text):
    """Pull a page count out of a physical description string."""
    for match in PAGES_RE.finditer(text or ""):
        n = int(match.group(1))
        if MIN_PAGES <= n <= MAX_PAGES:
            return n
    return None


def plausible(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    return n if MIN_PAGES <= n <= MAX_PAGES else None


# ---------------------------------------------------------------- sources ---


class PageCountFinder:
    def __init__(self, timeout=15, use_amazon=False, log=print):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.log = log
        self.google_key = getattr(settings, "GOOGLE_BOOKS_API_KEY", None) or os.environ.get(
            "GOOGLE_BOOKS_API_KEY"
        )
        self.bc_library = getattr(settings, "BIBLIOCOMMONS_LIBRARY", None) or os.environ.get(
            "BIBLIOCOMMONS_LIBRARY", "hclib"
        )
        self.amazon = None
        if use_amazon:
            api_key = getattr(settings, "ASINDATAAPI", None)
            if api_key:
                from pages.services import AmazonBookMatcher, BookDataEnricher

                self.amazon = BookDataEnricher(AmazonBookMatcher(api_key))
            else:
                self.log("  (--use-amazon ignored: ASINDATAAPI is not set)")

    def _get(self, url, **kwargs):
        try:
            resp = self.session.get(url, timeout=self.timeout, **kwargs)
            if resp.status_code == 200:
                return resp
            self.log(f"    {url.split('/')[2]} returned HTTP {resp.status_code}")
        except requests.RequestException as e:
            self.log(f"    {url.split('/')[2]} error: {e}")
        return None

    def find(self, book):
        """Return (page_count, source) or (None, None)."""
        title = book.title
        first = book.author.first_name if book.author_id else ""
        last = book.author.last_name if book.author_id else ""
        isbn = re.sub(r"[^0-9Xx]", "", book.isbn or "")

        steps = []
        if book.bibliocommons_id:
            steps.append(("bibliocommons", lambda: self.bibliocommons(book.bibliocommons_id)))
        if isbn:
            steps.append(("openlibrary-isbn", lambda: self.openlibrary_isbn(isbn)))
            steps.append(("google-isbn", lambda: self.google(f"isbn:{isbn}", None, None)))
        steps.append(("openlibrary-search", lambda: self.openlibrary_search(title, first, last)))
        steps.append(
            (
                "google-search",
                lambda: self.google(
                    f'intitle:"{main_title(title).strip()}" inauthor:"{last}"', title, last
                ),
            )
        )
        if self.amazon and book.asin:
            steps.append(("amazon", lambda: plausible(self.amazon._get_page_count(book.asin))))

        for source, fn in steps:
            pages = fn()
            if pages:
                return pages, source
        return None, None

    # BiblioCommons -----------------------------------------------------------

    def bibliocommons(self, bib_id):
        # 1) JSON gateway used by BiblioCommons' own front end
        resp = self._get(
            f"https://gateway.bibliocommons.com/v2/libraries/{self.bc_library}/bibs/{bib_id}"
        )
        if resp is not None:
            try:
                pages = self._pages_in_json(resp.json())
                if pages:
                    return pages
            except ValueError:
                pass
        # 2) The public record page
        resp = self._get(f"https://{self.bc_library}.bibliocommons.com/v2/record/{bib_id}")
        if resp is None:
            return None
        html = resp.text
        for m in re.finditer(r'"physicalDescription"\s*:\s*(\[[^\]]*\]|"[^"]*")', html):
            pages = pages_from_text(m.group(1))
            if pages:
                return pages
        # visible "Physical Description" field on the details panel
        m = re.search(r"Physical Description.{0,400}", html, re.IGNORECASE | re.DOTALL)
        if m:
            return pages_from_text(re.sub(r"<[^>]+>", " ", m.group(0)))
        return None

    def _pages_in_json(self, data):
        """Find a physicalDescription anywhere in a JSON blob."""
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() in ("physicaldescription", "physical_description"):
                    pages = pages_from_text(json.dumps(value))
                    if pages:
                        return pages
                pages = self._pages_in_json(value)
                if pages:
                    return pages
        elif isinstance(data, list):
            for item in data:
                pages = self._pages_in_json(item)
                if pages:
                    return pages
        return None

    # Open Library ------------------------------------------------------------

    def openlibrary_isbn(self, isbn):
        resp = self._get(f"https://openlibrary.org/isbn/{isbn}.json")
        if resp is None:
            return None
        data = resp.json()
        return plausible(data.get("number_of_pages")) or pages_from_text(
            data.get("pagination", "")
        )

    def openlibrary_search(self, title, first, last):
        resp = self._get(
            "https://openlibrary.org/search.json",
            params={
                "title": title,
                "author": f"{first} {last}".strip(),
                "fields": "title,subtitle,author_name,number_of_pages_median",
                "limit": 5,
            },
        )
        if resp is None:
            return None
        for doc in resp.json().get("docs", []):
            full_title = doc.get("title", "")
            if doc.get("subtitle"):
                full_title += ": " + doc["subtitle"]
            if (
                titles_match(title, full_title)
                and author_matches(last, doc.get("author_name"))
                and plausible(doc.get("number_of_pages_median"))
            ):
                return int(doc["number_of_pages_median"])
        return None

    # Google Books ------------------------------------------------------------

    def google(self, query, title, last):
        params = {"q": query, "maxResults": 10, "printType": "books"}
        if self.google_key:
            params["key"] = self.google_key
        resp = self._get("https://www.googleapis.com/books/v1/volumes", params=params)
        if resp is None:
            return None
        counts = []
        for item in resp.json().get("items", []):
            info = item.get("volumeInfo", {})
            full_title = info.get("title", "")
            if info.get("subtitle"):
                full_title += ": " + info["subtitle"]
            if title is not None and not (
                titles_match(title, full_title) and author_matches(last, info.get("authors"))
            ):
                continue
            n = plausible(info.get("pageCount"))
            if n:
                counts.append(n)
        if not counts:
            return None
        # Several editions usually come back; take the median to skip outliers
        counts.sort()
        return counts[len(counts) // 2]


# ---------------------------------------------------------------- command ---


class Command(BaseCommand):
    help = "Look up and fill in page counts for books that are missing one"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Look up but don't save")
        parser.add_argument("--limit", type=int, help="Process at most this many books")
        parser.add_argument("--id", type=int, action="append", dest="ids", help="Only this book id (repeatable)")
        parser.add_argument("--delay", type=float, default=1.0, help="Seconds between books (default 1)")
        parser.add_argument("--use-amazon", action="store_true", help="Also try ASINDATAAPI (paid) when a book has an ASIN")

    def handle(self, *args, **opts):
        books = (
            Book.objects.filter(page_count__isnull=True)
            .select_related("author")
            .order_by("title")
        )
        if opts["ids"]:
            books = books.filter(id__in=opts["ids"])
        if opts["limit"]:
            books = books[: opts["limit"]]
        books = list(books)

        dry_run = opts["dry_run"]
        self.stdout.write(f"{len(books)} book(s) without a page count")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing will be saved"))

        finder = PageCountFinder(use_amazon=opts["use_amazon"], log=self.stdout.write)
        found = 0

        for i, book in enumerate(books, 1):
            author = book.author
            label = f"[{i}/{len(books)}] {book.title} - {author.first_name} {author.last_name}".strip()

            if normalize(book.title) in ("", "untitled"):
                pages, source = None, "skipped (no real title)"
            else:
                pages, source = finder.find(book)

            if pages:
                found += 1
                self.stdout.write(self.style.SUCCESS(f"{label}: {pages} pages ({source})"))
                if not dry_run:
                    book.page_count = pages
                    book.save(update_fields=["page_count"])
            else:
                self.stdout.write(f"{label}: not found" + (f" - {source}" if source else ""))

            if opts["delay"] and i < len(books):
                time.sleep(opts["delay"])

        verb = "found" if dry_run else "filled in"
        self.stdout.write(
            self.style.SUCCESS(f"Done: {verb} {found} of {len(books)}; {len(books) - found} still missing")
        )
