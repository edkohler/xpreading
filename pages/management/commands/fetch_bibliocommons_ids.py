"""Find BiblioCommons record IDs for books that don't have one yet.

Usage:
    python manage.py fetch_bibliocommons_ids                 # all books due a search
    python manage.py fetch_bibliocommons_ids --limit 20      # try a few first
    python manage.py fetch_bibliocommons_ids --dry-run --limit 5
    python manage.py fetch_bibliocommons_ids --book 18501 --book 6070

Exact title + author matches are saved to Book.bibliocommons_id straight away.
Close and title-only matches go to Admin > Pages > Review matches, and books
with no result go to Admin > Pages > Not found in HCLib. Books that were not
found are searched again after --recheck-days (default 30).
"""

import time

from django.core.management.base import BaseCommand, CommandError

from pages import bibliocommons as bc
from pages.bibliocommons_sync import books_to_check, save_result, search_book


class Command(BaseCommand):
    help = "Look up missing BiblioCommons IDs in the library catalog"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="stop after this many books")
        parser.add_argument(
            "--book",
            type=int,
            action="append",
            dest="books",
            help="only this book id (repeatable); searched even if checked before",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="search and print, save nothing"
        )
        parser.add_argument(
            "--recheck-days",
            type=int,
            default=30,
            help="search 'not found' books again after this many days",
        )
        parser.add_argument(
            "--include-rejected",
            action="store_true",
            help="also re-search rejected review matches older than --recheck-days",
        )
        parser.add_argument(
            "--auto-approve-close",
            action="store_true",
            help="also fill IDs for close title matches instead of queueing them",
        )
        parser.add_argument(
            "--library",
            default=bc.DEFAULT_LIBRARY,
            help="BiblioCommons library code (default: hclib)",
        )
        parser.add_argument(
            "--delay", type=float, default=0.5, help="seconds between catalog requests"
        )
        parser.add_argument(
            "--max-errors",
            type=int,
            default=5,
            help="stop after this many failed searches in a row",
        )

    def handle(self, *args, **o):
        books = books_to_check(
            recheck_days=o["recheck_days"],
            include_rejected=o["include_rejected"],
            book_ids=o["books"],
        )
        if o["limit"]:
            books = books[: o["limit"]]
        books = list(books)
        dry = o["dry_run"]
        self.stdout.write(
            f"{len(books)} books to search in {o['library']}"
            + (self.style.WARNING(" (dry run, nothing saved)") if dry else "")
        )

        client = bc.Client(library=o["library"], delay=o["delay"])
        counts = {
            k: 0 for k in (bc.EXACT, bc.CLOSE, bc.TITLE_ONLY, bc.NOT_FOUND, bc.ERROR)
        }
        errors_in_row = 0
        started = time.monotonic()

        for n, book in enumerate(books, 1):
            try:
                match = search_book(client, book)
                errors_in_row = 0
            except bc.CatalogError as e:
                match = bc.Match(bc.ERROR, error=str(e), query=book.title)
                errors_in_row += 1
            counts[match.match_type] += 1

            line = (
                f"[{n}/{len(books)}] {book.title} / {book.author}: {match.match_type}"
            )
            if match.record_id:
                line += f" {match.record_id}"
                if match.match_type != bc.EXACT:
                    line += f" ({match.title} | {match.authors})"
            if match.error:
                line += f" - {match.error}"
            self.stdout.write(line)

            if not dry:
                save_result(
                    book,
                    match,
                    library=o["library"],
                    auto_approve_close=o["auto_approve_close"],
                )

            if errors_in_row >= o["max_errors"]:
                raise CommandError(
                    f"Stopping: {errors_in_row} searches failed in a row "
                    f"(last error: {match.error}). The catalog may be blocking "
                    "requests from this server."
                )

        mins = (time.monotonic() - started) / 60
        self.stdout.write(
            self.style.SUCCESS(
                f"Done in {mins:.1f} min: {counts[bc.EXACT]} exact (saved), "
                f"{counts[bc.CLOSE]} close, {counts[bc.TITLE_ONLY]} title only, "
                f"{counts[bc.NOT_FOUND]} not found, {counts[bc.ERROR]} errors."
            )
        )
