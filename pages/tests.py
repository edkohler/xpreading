from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Author, Book, BookCategory, Category, Illustrator


@override_settings(SITEMAP_DOMAIN="xpreading.com")
class SitemapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Caldecott Medal")
        cls.author = Author.objects.create(first_name="Jane", last_name="Doe")
        cls.illustrator = Illustrator.objects.create(first_name="Sam", last_name="Lee")
        cls.lonely_author = Author.objects.create(first_name="No", last_name="Books")
        cls.book = Book.objects.create(
            title="A Test Book", author=cls.author, illustrator=cls.illustrator
        )
        BookCategory.objects.create(book=cls.book, category=cls.category, year=2024)

    def test_sitemap_lists_public_pages(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        base = "https://xpreading.com"
        self.assertIn(f"<loc>{base}/</loc>", body)
        self.assertIn(f"<loc>{base}/about/</loc>", body)
        self.assertIn(f"<loc>{base}/book_lists/</loc>", body)
        self.assertIn(f"<loc>{base}/categories/{self.category.slug}/</loc>", body)
        self.assertIn(f"<loc>{base}/book/{self.book.slug}/</loc>", body)
        self.assertIn(f"<loc>{base}/author/{self.author.id}/</loc>", body)
        self.assertIn(f"<loc>{base}/illustrator/{self.illustrator.id}/</loc>", body)

    def test_sitemap_skips_authors_without_books_and_private_pages(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertNotIn(f"/author/{self.lonely_author.id}/<", body)
        self.assertNotIn("/my-books/", body)
        self.assertNotIn("/admin/", body)

    def test_robots_txt_points_to_sitemap(self):
        response = self.client.get(reverse("robots_txt"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("Sitemap: https://xpreading.com/sitemap.xml", response.content.decode())
