from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from pages.models import (
    Author,
    AwardLevel,
    Book,
    BookCategory,
    Category,
    PendingAward,
    WikiPageState,
)
from pages.wiki_sync import extractor, service, wikipedia
from pages.wiki_sync.matching import title_keys


def P(first, last):
    return {"first_name": first, "last_name": last}


def entry(cat, year, title, authors, level, illustrators=()):
    return {
        "category_id": cat.id,
        "year": year,
        "title": title,
        "authors": [P(*a) for a in authors],
        "illustrators": [P(*i) for i in illustrators],
        "award_level": level,
        "level_text": level or "",
        "source_text": title,
    }


class HelpersTest(TestCase):
    def test_title_from_url(self):
        self.assertEqual(
            wikipedia.title_from_url(
                "https://en.wikipedia.org/wiki/Golden_Duck_Award#Hal_Clement_Award"
            ),
            "Golden_Duck_Award",
        )
        self.assertEqual(
            wikipedia.title_from_url(
                "https://en.wikipedia.org/wiki/Am%C3%A9ricas_Award"
            ),
            "Américas_Award",
        )
        self.assertIsNone(wikipedia.title_from_url("https://example.com/x"))

    def test_clean_wikitext_keeps_rows_drops_refs(self):
        raw = (
            '== Recipients ==\n{| class=wikitable\n|- style="background:#fff7c9\n'
            '! rowspan="5" |2026\n|{{sort|Watson,Renée|[[Renée Watson (author)|Renée Watson]]}}'
            "<ref>{{cite web|url=x}}</ref>\n|''[[All the Blues in the Sky]]''\n|}\n"
            "== References ==\n{{reflist}}\n[[Category:Awards]]"
        )
        out = wikipedia.clean_wikitext(raw)
        self.assertIn("All the Blues in the Sky", out)
        self.assertIn("2026", out)
        self.assertNotIn("<ref", out)
        self.assertNotIn("reflist", out)
        self.assertNotIn("Category:", out)

    def test_title_keys(self):
        self.assertIn("mexikid", title_keys("Mexikid: A Graphic Memoir"))
        self.assertEqual(title_keys("The Wrong Way Home"), title_keys("Wrong Way Home"))


class SyncTest(TestCase):
    def setUp(self):
        self.winner = AwardLevel.objects.create(name="Winner", order=1)
        self.honor = AwardLevel.objects.create(name="Honor", order=2)
        self.cat = Category.objects.create(
            name="Newbery Medal", wiki="https://en.wikipedia.org/wiki/Newbery_Medal"
        )
        self.other = Category.objects.create(
            name="Other", wiki="https://en.wikipedia.org/wiki/Other_Award"
        )
        self.off = Category.objects.create(
            name="Disabled",
            wiki="https://en.wikipedia.org/wiki/Off",
            wiki_sync_enabled=False,
        )
        kelly = Author.objects.create(first_name="Erin Entrada", last_name="Kelly")
        behar = Author.objects.create(first_name="Ruth", last_name="Behar")
        watson = Author.objects.create(first_name="Renée", last_name="Watson")
        self.first_state = Book.objects.create(
            title="The First State of Being", author=kelly
        )
        self.seas = Book.objects.create(title="Across So Many Seas", author=behar)
        self.blues = Book.objects.create(
            title="All the Blues in the Sky", author=watson
        )
        # first_state entered with the wrong year; seas correct; blues only in another category
        BookCategory.objects.create(
            book=self.first_state, category=self.cat, year=1943, award_level=self.winner
        )
        BookCategory.objects.create(
            book=self.seas, category=self.cat, year=2025, award_level=self.honor
        )
        BookCategory.objects.create(book=self.blues, category=self.other, year=2025)
        self.entries = [
            entry(
                self.cat,
                2025,
                "The First State of Being",
                [("Erin Entrada", "Kelly")],
                "Winner",
            ),
            entry(self.cat, 2025, "Across So Many Seas", [("Ruth", "Behar")], "Honor"),
            entry(
                self.cat,
                2026,
                "All the Blues in the Sky",
                [("Renée", "Watson")],
                "Winner",
            ),
            entry(
                self.cat,
                2026,
                "A Sea of Lemon Trees",
                [("María Dolores", "Águila")],
                "Honor",
                [("Some", "Illustrator")],
            ),
            entry(
                self.cat, 2026, "Across So Many Seas", [("Someone", "Else")], "Honor"
            ),
        ]
        self.revid = 100

    def _run(self, *args):
        def latest(titles):
            return {t: {"revid": self.revid, "missing": False} for t in titles}

        def fetch(title):
            return self.revid, "{| class=wikitable\n|}"

        def extract(title, since, ctxs, levels, text, model=None, api_key=None):
            self.seen_titles.append(title)
            self.since = since
            return (
                (self.entries if title == "Newbery_Medal" else []),
                "",
                {"total_tokens": 10},
            )

        self.seen_titles = []
        out = StringIO()
        with mock.patch.object(
            wikipedia, "latest_revisions", latest
        ), mock.patch.object(wikipedia, "fetch_wikitext", fetch), mock.patch.object(
            extractor, "extract_entries", extract
        ):
            call_command("sync_wikipedia_awards", "--no-email", *args, stdout=out)
        return out.getvalue()

    def test_full_flow(self):
        self._run()
        self.assertCountEqual(
            self.seen_titles, ["Newbery_Medal", "Other_Award"]
        )  # disabled skipped
        self.assertEqual(self.since, 2024)  # newest year we have (2025) minus one
        pend = {(p.title, p.year): p for p in PendingAward.objects.all()}
        self.assertNotIn(("Across So Many Seas", 2025), pend)  # already listed
        fs = pend[("The First State of Being", 2025)]
        self.assertEqual(fs.match_type, PendingAward.MATCH_CONFLICT)
        self.assertEqual(fs.matched_book, self.first_state)
        self.assertIn("1943", fs.match_notes)
        blues = pend[("All the Blues in the Sky", 2026)]
        self.assertEqual(blues.match_type, PendingAward.MATCH_EXISTING)
        self.assertEqual(blues.matched_book, self.blues)
        lemon = pend[("A Sea of Lemon Trees", 2026)]
        self.assertEqual(lemon.match_type, PendingAward.MATCH_NEW)
        dup_title = pend[("Across So Many Seas", 2026)]
        self.assertEqual(
            dup_title.match_type, PendingAward.MATCH_CONFLICT
        )  # different author
        self.assertIsNone(dup_title.matched_book)

        # unchanged revision -> page not re-read
        self._run()
        self.assertEqual(self.seen_titles, [])
        # forced re-read -> no duplicates
        n = PendingAward.objects.count()
        self._run("--force")
        self.assertEqual(PendingAward.objects.count(), n)

        # approvals
        service.approve(blues)
        self.assertTrue(
            BookCategory.objects.filter(
                book=self.blues, category=self.cat, year=2026, award_level=self.winner
            ).exists()
        )
        service.approve(lemon)
        book = Book.objects.get(title="A Sea of Lemon Trees")
        self.assertEqual(book.author.last_name, "Águila")
        self.assertEqual(book.illustrator.last_name, "Illustrator")
        self.assertTrue(
            BookCategory.objects.filter(
                book=book, category=self.cat, year=2026
            ).exists()
        )
        service.approve(fs, move_existing=True)
        self.assertFalse(
            BookCategory.objects.filter(book=self.first_state, year=1943).exists()
        )
        self.assertTrue(
            BookCategory.objects.filter(
                book=self.first_state, category=self.cat, year=2025
            ).exists()
        )
        service.reject(dup_title)

        # rejected items are not proposed again, approved ones are now 'already listed'
        self._run("--force")
        self.assertEqual(PendingAward.objects.count(), n)
        self.assertEqual(
            PendingAward.objects.filter(status=PendingAward.STATUS_PENDING).count(), 0
        )

    def test_control_characters_are_stripped(self):
        self.entries = [
            entry(self.cat, 2026, "Nul\x00 Title", [("A\x00", "Writer\x00")], "Winner"),
        ]
        self.entries[0]["source_text"] = "row\x00text\x07"
        self._run()
        p = PendingAward.objects.get()
        self.assertEqual(p.title, "Nul Title")
        self.assertEqual(p.author_last_name, "Writer")
        self.assertEqual(p.source_text, "rowtext")

    def test_dry_run_writes_nothing(self):
        out = self._run("--dry-run")
        self.assertIn("A Sea of Lemon Trees", out)
        self.assertEqual(PendingAward.objects.count(), 0)
        self.assertFalse(
            WikiPageState.objects.exclude(last_processed_revid=None).exists()
        )

    def test_errors_are_recorded_and_retried(self):
        def boom(*a, **k):
            raise extractor.ExtractionError("OpenAI HTTP 500")

        with mock.patch.object(
            wikipedia,
            "latest_revisions",
            lambda t: {x: {"revid": 5, "missing": False} for x in t},
        ), mock.patch.object(
            wikipedia, "fetch_wikitext", lambda t: (5, "")
        ), mock.patch.object(
            extractor, "extract_entries", boom
        ), mock.patch.object(
            service, "log"
        ):  # don't send test errors to Sentry
            out = StringIO()
            call_command("sync_wikipedia_awards", "--no-email", stdout=out)
        state = WikiPageState.objects.get(title="Newbery_Medal")
        self.assertIn("HTTP 500", state.last_error)
        self.assertIsNone(state.last_processed_revid)  # so the next run tries again

    def test_admin_pages_render(self):
        self._run()
        User = get_user_model()
        u = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.client.force_login(u)
        r = self.client.get("/admin/pages/pendingaward/")
        self.assertEqual(r.status_code, 200)
        p = PendingAward.objects.first()
        r = self.client.get(f"/admin/pages/pendingaward/{p.id}/change/")
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            "/admin/pages/pendingaward/",
            {"action": "approve_selected", "_selected_action": [p.id]},
        )
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, PendingAward.STATUS_APPROVED)


class PromptTest(TestCase):
    def test_prompt_contains_context(self):
        txt = extractor.build_user_prompt(
            "Newbery_Medal",
            2025,
            [
                {
                    "id": 1,
                    "name": "Newbery",
                    "section": "",
                    "notes": "award year",
                    "year_range": "1922-2026",
                    "levels": "Winner (1)",
                    "examples": ["2026 | Winner | X | Y"],
                }
            ],
            ["Winner", "Honor"],
            "WIKITEXT",
        )
        for s in (
            "since_year: 2025",
            "category_id 1",
            "Notes: award year",
            "2026 | Winner | X | Y",
            "WIKITEXT",
        ):
            self.assertIn(s, txt)
        schema = extractor._schema([1, 2], ["Winner", "Honor"])
        self.assertEqual(
            schema["schema"]["properties"]["entries"]["items"]["properties"][
                "category_id"
            ]["enum"],
            [1, 2],
        )
