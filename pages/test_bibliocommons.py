from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from pages import bibliocommons as bc
from pages.bibliocommons_sync import approve, books_to_check, reject, save_result
from pages.models import Author, BiblioCommonsLookup as Lookup, Book


def bib(rid, title, authors, fmt="BK", subtitle=""):
    return rid, {
        "id": rid,
        "briefInfo": {
            "title": title,
            "subtitle": subtitle,
            "authors": authors,
            "format": fmt,
        },
    }


def response(*bibs):
    return {
        "catalogSearch": {"results": [{"representative": rid} for rid, _ in bibs]},
        "entities": {"bibs": dict(bibs)},
    }


# Trimmed real HCLib responses (captured Nov 2026)
TOLLBOOTH = response(
    bib(
        "S109C1027736", "La caseta mágica", ["Juster, Norton, 1929-2021"], subtitle=None
    ),
    bib(
        "S109C4456689",
        "Shou fei ting li de xiao Miluo",
        ["Juster, Norton, 1929-2021"],
        subtitle="The phantom tollbooth",
    ),
    bib(
        "S109C5809358",
        "Bookends",
        ["Chabon, Michael"],
        subtitle="Collected Intros and Outros",
    ),
    bib(
        "S109C4583619", "The Annotated Phantom Tollbooth", ["Juster, Norton, 1929-2021"]
    ),
    bib("S109C4583618", "The Phantom Tollbooth", ["Juster, Norton, 1929-2021"]),
)
CREATURES = response(bib("S109C6053509", "1,001 Creatures", ["Merz, Laura"]))
AMULET = response(
    bib(
        "S109C6552534",
        "Amulet",
        ["Kibuishi, Kazu, 1978-"],
        "GRAPHIC_NOVEL",
        "Book Nine, Waverider",
    ),
    bib(
        "S109C5192163",
        "Amulet",
        ["Kibuishi, Kazu, 1978-"],
        "EBOOK",
        "Book 1, The Stonekeeper",
    ),
    bib(
        "S109C3154549",
        "Amulet",
        ["Kibuishi, Kazu, 1978-"],
        "GRAPHIC_NOVEL",
        "Book One, The Stonekeeper",
    ),
)
EMPTY = {"catalogSearch": {"results": []}, "entities": {"bibs": {}}}


class MatchingTests(SimpleTestCase):
    def test_norm(self):
        self.assertEqual(bc.norm("Kävik the Wolf-Dog"), "kavik the wolf dog")
        self.assertEqual(bc.norm("1,001 Creatures"), "1001 creatures")
        self.assertEqual(bc.norm_title("The Kid's Book & Me"), "kids book and me")

    def test_exact_match_skips_translations_and_annotated(self):
        m = bc.pick(TOLLBOOTH, "The Phantom Tollbooth", "Juster")
        self.assertEqual((m.match_type, m.record_id), (bc.EXACT, "S109C4583618"))

    def test_exact_with_subtitle_prefers_print_book(self):
        m = bc.pick(AMULET, "Amulet: Book One, The Stonekeeper", "Kibuishi")
        self.assertEqual((m.match_type, m.record_id), (bc.EXACT, "S109C3154549"))

    def test_close_match(self):
        m = bc.pick(AMULET, "Amulet", "Kibuishi")
        self.assertEqual(m.match_type, bc.CLOSE)

    def test_title_only_needs_permission(self):
        self.assertEqual(
            bc.pick(CREATURES, "1,001 Creatures", "Järvinen").match_type, bc.NOT_FOUND
        )
        m = bc.pick(CREATURES, "1,001 Creatures", "Järvinen", allow_title_only=True)
        self.assertEqual((m.match_type, m.authors), (bc.TITLE_ONLY, "Merz, Laura"))

    def test_author_suffixes(self):
        self.assertTrue(bc.author_matches(["Collard, Sneed B."], "Collard III"))
        self.assertTrue(bc.author_matches(["Seuss, Dr"], "Seuss"))
        self.assertFalse(bc.author_matches(["Gibbons, Gail"], "Cooper"))

    def test_queries(self):
        self.assertEqual(
            bc.queries_for("Bones: How They Work", "Steve", "Jenkins"),
            [
                "Bones: How They Work Steve Jenkins",
                "Bones: How They Work Jenkins",
                "Bones: How They Work",
                "Bones Jenkins",
                "Bones",
            ],
        )

    def test_client_stops_at_first_exact(self):
        client = bc.Client(delay=0)
        with mock.patch.object(client, "search", side_effect=[EMPTY, TOLLBOOTH]) as s:
            m = client.lookup("The Phantom Tollbooth", "Norton", "Juster")
        self.assertEqual(m.match_type, bc.EXACT)
        self.assertEqual(s.call_count, 2)
        self.assertEqual(m.query, "The Phantom Tollbooth Juster")

    def test_client_http_error(self):
        client = bc.Client(delay=0)
        resp = mock.Mock(status_code=403)
        with mock.patch.object(client.session, "get", return_value=resp):
            with self.assertRaises(bc.CatalogError):
                client.search("anything")


class SyncTests(TestCase):
    def setUp(self):
        self.author = Author.objects.create(first_name="Norton", last_name="Juster")
        self.book = Book.objects.create(
            title="The Phantom Tollbooth", author=self.author
        )
        self.other = Book.objects.create(
            title="The Dot and the Line", author=self.author
        )

    def test_exact_fills_book(self):
        save_result(self.book, bc.Match(bc.EXACT, "S1", "The Phantom Tollbooth"))
        self.book.refresh_from_db()
        self.assertEqual(self.book.bibliocommons_id, "S1")
        self.assertEqual(
            self.book.bibliocommons_lookup.review_status, Lookup.STATUS_AUTO
        )

    def test_close_waits_for_review_then_approve(self):
        lookup = save_result(self.book, bc.Match(bc.CLOSE, "S2", "x"))
        self.book.refresh_from_db()
        self.assertIsNone(self.book.bibliocommons_id)
        approve(lookup)
        self.book.refresh_from_db()
        self.assertEqual(self.book.bibliocommons_id, "S2")

    def test_auto_approve_close(self):
        save_result(self.book, bc.Match(bc.CLOSE, "S2", "x"), auto_approve_close=True)
        self.book.refresh_from_db()
        self.assertEqual(self.book.bibliocommons_id, "S2")

    def test_books_to_check(self):
        save_result(self.book, bc.Match(bc.NOT_FOUND))
        self.assertEqual(list(books_to_check()), [self.other])
        Lookup.objects.update(checked_at=timezone.now() - timedelta(days=40))
        self.assertEqual(set(books_to_check()), {self.book, self.other})
        # pending review is never re-searched; rejected only when asked
        lookup = save_result(self.book, bc.Match(bc.CLOSE, "S2", "x"))
        Lookup.objects.update(checked_at=timezone.now() - timedelta(days=40))
        self.assertEqual(list(books_to_check()), [self.other])
        reject(lookup)
        self.assertEqual(list(books_to_check()), [self.other])
        self.assertEqual(
            set(books_to_check(include_rejected=True)), {self.book, self.other}
        )

    def test_command(self):
        fake = mock.Mock()
        fake.lookup.side_effect = [
            bc.Match(bc.EXACT, "S9", "t"),
            bc.Match(bc.NOT_FOUND),
        ]
        out = StringIO()
        with mock.patch("pages.bibliocommons.Client", return_value=fake):
            call_command("fetch_bibliocommons_ids", stdout=out)
        self.book.refresh_from_db()
        self.assertEqual(self.book.bibliocommons_id, "S9")
        self.assertEqual(
            self.other.bibliocommons_lookup.match_type, Lookup.MATCH_NOT_FOUND
        )
        self.assertIn("1 exact (saved)", out.getvalue())

    def test_command_dry_run_saves_nothing(self):
        fake = mock.Mock()
        fake.lookup.return_value = bc.Match(bc.EXACT, "S9", "t")
        with mock.patch("pages.bibliocommons.Client", return_value=fake):
            call_command("fetch_bibliocommons_ids", "--dry-run", stdout=StringIO())
        self.assertFalse(Lookup.objects.exists())

    def test_command_stops_when_blocked(self):
        fake = mock.Mock()
        fake.lookup.side_effect = bc.CatalogError("HTTP 403")
        from django.core.management.base import CommandError

        with mock.patch("pages.bibliocommons.Client", return_value=fake):
            with self.assertRaises(CommandError):
                call_command(
                    "fetch_bibliocommons_ids", "--max-errors", "2", stdout=StringIO()
                )


class AdminReportTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("a", "a@x.com", "pw")
        self.client.force_login(self.admin)
        author = Author.objects.create(first_name="Aino", last_name="Järvinen")
        self.b1 = Book.objects.create(title="1,001 Creatures", author=author)
        self.b2 = Book.objects.create(title="Lobster Cop", author=author)
        self.match = save_result(
            self.b1, bc.Match(bc.TITLE_ONLY, "S6", "1,001 Creatures", "Merz, Laura")
        )
        save_result(self.b2, bc.Match(bc.NOT_FOUND))

    def test_review_page_lists_match_and_approves(self):
        url = reverse("admin:pages_bibliocommonsreviewmatch_changelist")
        resp = self.client.get(url)
        self.assertContains(resp, "1,001 Creatures")
        self.assertContains(resp, "S6")
        self.assertNotContains(resp, "Lobster Cop")
        self.client.post(
            url, {"action": "approve_selected", "_selected_action": [self.match.pk]}
        )
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.bibliocommons_id, "S6")
        self.assertContains(self.client.get(url), "0 Review matches")

    def test_reject_moves_to_not_found(self):
        url = reverse("admin:pages_bibliocommonsreviewmatch_changelist")
        self.client.post(
            url, {"action": "reject_selected", "_selected_action": [self.match.pk]}
        )
        resp = self.client.get(reverse("admin:pages_bibliocommonsnotfound_changelist"))
        self.assertContains(resp, "Lobster Cop")
        self.assertContains(resp, "Rejected match")
