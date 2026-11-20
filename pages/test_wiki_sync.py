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

    def test_slice_sections(self):
        text = (
            "Intro text.\n== Recipients ==\n=== Fiction ===\n"
            "==== Young adult (2006–) ====\nFICTION-YA\n"
            "=== Graphic novel ===\n==== Young adult (2006–) ====\nGRAPHIC-YA\n"
            "=== Poetry (2006–) ===\nPOETRY\n== References ==\nrefs"
        )
        out = wikipedia.slice_sections(text, ["Young adult (2006–) 2"])
        self.assertIn("GRAPHIC-YA", out)
        self.assertIn("=== Graphic novel ===", out)  # parent heading kept
        self.assertNotIn("FICTION-YA", out)
        self.assertNotIn("POETRY", out)
        self.assertIn("Intro text.", out)
        url = "https://en.wikipedia.org/wiki/Cybils_Award#Poetry_(2006%E2%80%93)"
        out = wikipedia.slice_sections(text, [wikipedia.section_from_url(url)])
        self.assertIn("POETRY", out)
        self.assertNotIn("GRAPHIC-YA", out)
        # unknown or missing anchor -> whole page
        self.assertEqual(wikipedia.slice_sections(text, ["Nope"]), text)
        self.assertEqual(wikipedia.slice_sections(text, ["Poetry (2006–)", ""]), text)

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

        def extract(
            title, ctxs, levels, text, other_categories=(), model=None, api_key=None
        ):
            self.seen_titles.append(title)
            self.calls.append(
                {
                    "title": title,
                    "since": {c["id"]: c["since"] for c in ctxs},
                    "others": list(other_categories),
                }
            )
            ids = {c["id"] for c in ctxs}
            entries = [e for e in self.entries if e["category_id"] in ids]
            return (
                (entries if title == "Newbery_Medal" else []),
                "",
                {"total_tokens": 10},
            )

        self.seen_titles = []
        self.calls = []
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
        newbery_call = [c for c in self.calls if c["title"] == "Newbery_Medal"][0]
        # newest year we have (2025) minus one
        self.assertEqual(newbery_call["since"], {self.cat.id: 2024})
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

    def test_new_categories_get_full_history_in_batches(self):
        page = "https://en.wikipedia.org/wiki/Cybils_Award"
        new = [Category.objects.create(name=f"Cybils {i}", wiki=page) for i in range(7)]
        old_entry = entry(new[0], 2008, "Old Book", [("Ann", "Writer")], "Winner")
        self.entries = [old_entry]
        self._run("--page", "Cybils_Award")
        calls = [c for c in self.calls if c["title"] == "Cybils_Award"]
        self.assertEqual(len(calls), 7)  # one new category per call
        for c in calls:
            self.assertTrue(all(v is None for v in c["since"].values()))  # all years
            self.assertEqual(len(c["others"]), 7 - len(c["since"]))
        state = WikiPageState.objects.get(title="Cybils_Award")
        self.assertEqual(
            sorted(int(k) for k in state.processed_category_ids), [c.id for c in new]
        )
        self.assertEqual(state.last_processed_revid, self.revid)

    def test_failed_batch_keeps_other_batches_and_is_retried(self):
        page = "https://en.wikipedia.org/wiki/Cybils_Award"
        a = Category.objects.create(name="Cybils A", wiki=page)
        b = Category.objects.create(name="Cybils B", wiki=page)
        self.entries = [
            entry(a, 2010, "Book A", [("Ann", "Writer")], "Winner"),
            entry(b, 2010, "Book B", [("Bob", "Writer")], "Winner"),
        ]
        attempts = []

        def latest(titles):
            return {t: {"revid": self.revid, "missing": False} for t in titles}

        def extract(title, ctxs, levels, text, other_categories=(), **kw):
            ids = {c["id"] for c in ctxs}
            attempts.append(ids)
            if b.id in ids and len(attempts) <= 2:
                raise extractor.ExtractionError("OpenAI request failed: timed out")
            return [e for e in self.entries if e["category_id"] in ids], "", {}

        def run():
            with mock.patch.object(
                wikipedia, "latest_revisions", latest
            ), mock.patch.object(
                wikipedia, "fetch_wikitext", lambda t: (self.revid, "")
            ), mock.patch.object(
                extractor, "extract_entries", extract
            ), mock.patch.object(
                service, "log"
            ):
                out = StringIO()
                call_command(
                    "sync_wikipedia_awards",
                    "--no-email",
                    "--page",
                    "Cybils_Award",
                    stdout=out,
                )
                return out.getvalue()

        out = run()
        self.assertIn("1 of 2 batches failed", out)
        self.assertTrue(PendingAward.objects.filter(title="Book A").exists())  # kept
        state = WikiPageState.objects.get(title="Cybils_Award")
        self.assertIsNone(state.last_processed_revid)  # page not complete
        self.assertIn("timed out", state.last_error)
        # second run: b's call is attempt #3, which succeeds
        self.assertEqual(len(attempts), 2)
        run()
        self.assertEqual(attempts[2:], [{b.id}])  # only the failed category re-read
        self.assertTrue(PendingAward.objects.filter(title="Book B").exists())
        state.refresh_from_db()
        self.assertEqual(state.last_processed_revid, self.revid)
        self.assertEqual(state.last_error, "")

    def test_category_added_to_unchanged_page_is_read(self):
        self._run()
        self.assertIn("Newbery_Medal", self.seen_titles)
        self._run()
        self.assertNotIn("Newbery_Medal", self.seen_titles)  # unchanged
        added = Category.objects.create(
            name="Newbery (new sub-list)",
            wiki="https://en.wikipedia.org/wiki/Newbery_Medal",
        )
        self._run()
        calls = [c for c in self.calls if c["title"] == "Newbery_Medal"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["since"], {added.id: None})  # only the new one
        self.assertEqual(calls[0]["others"], ["Newbery Medal"])
        self._run()
        self.assertNotIn("Newbery_Medal", self.seen_titles)

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


class ExtractorRequestTest(TestCase):
    def test_reasoning_effort_and_retry(self):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"entries": [], "notes": ""}'},
                }
            ]
        }
        calls = []

        def post(url, headers, json, timeout):
            calls.append(json)
            if len(calls) == 1:
                import requests

                raise requests.ReadTimeout("timed out")
            return ok

        with mock.patch("pages.wiki_sync.extractor.requests.post", post), mock.patch(
            "pages.wiki_sync.extractor.time.sleep"
        ):
            entries, _, _ = extractor.extract_entries(
                "P",
                [{"id": 1, "name": "C", "since": None}],
                ["Winner"],
                "W",
                api_key="k",
                model="gpt-5-mini",
            )
        self.assertEqual(entries, [])
        self.assertEqual(len(calls), 2)  # retried once after the timeout
        self.assertEqual(calls[0]["reasoning_effort"], "low")


class PromptTest(TestCase):
    def test_prompt_contains_context(self):
        txt = extractor.build_user_prompt(
            "Newbery_Medal",
            [
                {
                    "id": 1,
                    "since": 2025,
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
            other_categories=["Newbery Honor sub-list"],
        )
        for s in (
            "Extract: years >= 2025",
            "Other categories on this page (skip their entries):",
            "- Newbery Honor sub-list",
            "category_id 1",
            "Notes: award year",
            "2026 | Winner | X | Y",
            "WIKITEXT",
        ):
            self.assertIn(s, txt)
        new = extractor.build_user_prompt(
            "Cybils_Award", [{"id": 2, "name": "Cybils", "since": None}], [], "W"
        )
        self.assertIn("Extract: ALL years", new)
        schema = extractor._schema([1, 2], ["Winner", "Honor"])
        self.assertEqual(
            schema["schema"]["properties"]["entries"]["items"]["properties"][
                "category_id"
            ]["enum"],
            [1, 2],
        )
