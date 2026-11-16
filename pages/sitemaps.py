"""
Sitemaps for Google Search Console.

Served at /sitemap.xml (see django_project/urls.py). Only public pages are
listed; login-only, staff-only and HTMX/AJAX endpoints are left out.

The domain comes from the SITEMAP_DOMAIN setting (default "xpreading.com")
rather than the django.contrib.sites Site record, so the URLs are correct
even if the Site row in the database still says "example.com".
"""

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Author, Book, Category, Illustrator


class BaseSitemap(Sitemap):
    protocol = "https"

    def get_domain(self, site=None):
        return getattr(settings, "SITEMAP_DOMAIN", "xpreading.com")


class StaticViewSitemap(BaseSitemap):
    changefreq = "weekly"

    # (url name, priority)
    pages = [
        ("home", 1.0),
        ("award_year_list", 0.9),
        ("most_completed_books", 0.7),
        ("library_list", 0.6),
        ("about", 0.5),
        ("terms_and_conditions", 0.2),
        ("privacy_policy", 0.2),
    ]

    def items(self):
        return self.pages

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]


class CategorySitemap(BaseSitemap):
    changefreq = "monthly"
    priority = 0.9

    def items(self):
        return Category.objects.exclude(slug="").order_by("name")

    def location(self, obj):
        return reverse("category_detail", kwargs={"slug": obj.slug})


class BookSitemap(BaseSitemap):
    changefreq = "monthly"
    priority = 0.8

    def items(self):
        return Book.objects.exclude(slug="").only("slug").order_by("id")

    def location(self, obj):
        return reverse("book_detail", kwargs={"book_slug": obj.slug})


class AuthorSitemap(BaseSitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        # Skip authors with no books (e.g. leftovers from consolidation)
        return (
            Author.objects.filter(books__isnull=False)
            .distinct()
            .only("id")
            .order_by("id")
        )

    def location(self, obj):
        return reverse("author_detail", kwargs={"author_id": obj.id})


class IllustratorSitemap(BaseSitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return (
            Illustrator.objects.filter(books__isnull=False)
            .distinct()
            .only("id")
            .order_by("id")
        )

    def location(self, obj):
        return reverse("illustrator_detail", kwargs={"illustrator_id": obj.id})


sitemaps = {
    "static": StaticViewSitemap,
    "categories": CategorySitemap,
    "books": BookSitemap,
    "authors": AuthorSitemap,
    "illustrators": IllustratorSitemap,
}
