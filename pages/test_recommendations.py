from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Author, AwardYearLike, Book, BookCategory, Category, UserBook
from .recommendations import suggest_books


class SuggestBooksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="reader", email="r@example.com", password="pw"
        )
        author = Author.objects.create(first_name="A", last_name="Writer")
        cls.cal = Category.objects.create(name="Caldecott Medal")
        cls.new = Category.objects.create(name="Newbery Medal")
        cls.other = Category.objects.create(name="Other Award")

        def book(title, pages):
            return Book.objects.create(title=title, author=author, page_count=pages)

        cls.read1, cls.read2, cls.read3 = book("R1", 32), book("R2", 32), book("R3", 200)
        cls.overlap = book("On Two Liked Lists", 250)    # last book on Cal + 1 of 2 on New
        cls.single = book("Last On One List", 40)        # last book on Other (liked)
        cls.far = book("Far Away", 300)                  # 1 of 2 left on Newbery
        cls.unliked_only = book("Unliked Only", 100)     # on an unliked list

        for b in (cls.read1, cls.overlap):
            BookCategory.objects.create(book=b, category=cls.cal, year=2020)
        for b in (cls.read3, cls.overlap, cls.far):
            BookCategory.objects.create(book=b, category=cls.new, year=2020)
        for b in (cls.read2, cls.single):
            BookCategory.objects.create(book=b, category=cls.other, year=2020)
        for b in (cls.read1, cls.unliked_only):
            BookCategory.objects.create(book=b, category=cls.other, year=2021)

        for b in (cls.read1, cls.read2, cls.read3):
            UserBook.objects.create(user=cls.user, book=b, completed=True)
        for cat in (cls.cal, cls.new, cls.other):
            AwardYearLike.objects.create(user=cls.user, category=cat, year=2020)

    def _suggest(self):
        books_by_list = {}
        for c, y, b in BookCategory.objects.values_list("category_id", "year", "book_id"):
            books_by_list.setdefault((c, y), []).append(b)
        completed = set(
            UserBook.objects.filter(user=self.user, completed=True).values_list("book_id", flat=True)
        )
        liked = set(AwardYearLike.objects.filter(user=self.user).values_list("category_id", "year"))
        cats = {c.id: {"name": c.name, "slug": c.slug} for c in Category.objects.all()}
        return suggest_books(books_by_list, completed, liked, cats)

    def test_book_on_multiple_nearly_done_lists_ranks_first(self):
        s = self._suggest()
        titles = [x["book"].title for x in s]
        self.assertEqual(titles[0], "On Two Liked Lists")
        top = s[0]
        self.assertEqual(top["list_score"], 500 + 250)
        self.assertEqual(top["liked_list_count"], 2)
        self.assertEqual(top["lists_finished_now"], 1)
        self.assertEqual(top["immediate_xp"], 250 + 100 + 500)

    def test_unliked_lists_count_at_reduced_weight(self):
        s = {x["book"].title: x for x in self._suggest()}
        self.assertEqual(s["Last On One List"]["list_score"], 500)
        self.assertEqual(s["Unliked Only"]["list_score"], 250)
        self.assertEqual(s["Unliked Only"]["immediate_xp"], 200)  # no list bonus until liked
        self.assertFalse(s["Unliked Only"]["lists"][0]["liked"])

    def test_completed_books_are_never_suggested(self):
        titles = {x["book"].title for x in self._suggest()}
        self.assertFalse(titles & {"R1", "R2", "R3"})

    def test_xp_report_shows_suggestions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("xp_report"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Best Next Reads")
        self.assertEqual(
            response.context["suggested_books"][0]["book"].title, "On Two Liked Lists"
        )
