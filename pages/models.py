import os
import re
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify

from django_project.storage_backends import MediaStorage


def upload_to_book_images(instance, filename):
    # Get the file extension (e.g., '.jpg', '.png')
    ext = os.path.splitext(filename)[1]
    # Generate a new unique filename
    new_filename = f"{uuid.uuid4()}{ext}"
    # Return the full path for the file
    return f"book_images/{new_filename}"


# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)  # e.g., "Caldecott", "Newbery"
    description = models.TextField(blank=True)
    new_books_release_day_of_year = models.IntegerField(
        blank=True, null=True
    )  # Day of the year when new books are released
    min_age = models.IntegerField(blank=True, null=True)  # Minimum recommended age
    max_age = models.IntegerField(blank=True, null=True)  # Maximum recommended age
    wiki = models.URLField(blank=True, null=True)  # Link to Wikipedia page
    slug = models.SlugField(max_length=256, unique=True, blank=True)
    # Wikipedia sync (see pages/wiki_sync/ and `manage.py sync_wikipedia_awards`)
    wiki_sync_enabled = models.BooleanField(
        default=True,
        help_text="Check this category's Wikipedia page for new books.",
    )
    wiki_sync_notes = models.TextField(
        blank=True,
        help_text=(
            "Optional hints for the Wikipedia reader, e.g. 'Only the table under "
            "the Picture Book heading belongs to this category' or 'Year column "
            "is the publication year; our year is the award year (+1)'."
        ),
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:100]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class AwardLevel(models.Model):
    name = models.CharField(
        max_length=50, unique=True
    )  # e.g., "Nominee", "Gold", "1st"
    order = (
        models.IntegerField()
    )  # Used to sort levels (e.g., 1 = "Gold", 2 = "Silver")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class Author(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    @property
    def full_name(self):
        """
        Returns the full name of the author.
        If first and last names are the same, returns only the first name.
        """
        if self.first_name.strip().lower() == self.last_name.strip().lower():
            return self.first_name.strip()
        return f"{self.first_name.strip()} {self.last_name.strip()}".strip()

    def __str__(self):
        return self.full_name

    class Meta:
        # Add indexes for better search performance
        indexes = [
            models.Index(fields=["first_name"]),
            models.Index(fields=["last_name"]),
            models.Index(fields=["first_name", "last_name"]),
        ]


class Illustrator(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    @property
    def full_name(self):
        """
        Returns the full name of the illustrator.
        If first and last names are the same, returns only the first name.
        """
        if self.first_name.strip().lower() == self.last_name.strip().lower():
            return self.first_name.strip()
        return f"{self.first_name.strip()} {self.last_name.strip()}".strip()

    def __str__(self):
        return self.full_name

    class Meta:
        # Add indexes for better search performance
        indexes = [
            models.Index(fields=["first_name"]),
            models.Index(fields=["last_name"]),
            models.Index(fields=["first_name", "last_name"]),
        ]


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    illustrator = models.ForeignKey(
        Illustrator,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="books",
    )
    categories = models.ManyToManyField(Category, through="BookCategory")
    isbn = models.CharField(max_length=13, blank=True, null=True)
    page_count = models.IntegerField(blank=True, null=True)
    bibliocommons_id = models.CharField(max_length=20, blank=True, null=True)
    asin = models.CharField(max_length=20, blank=True, null=True)
    slug = models.SlugField(max_length=256, blank=True, unique=True)
    image = models.ImageField(
        upload_to=upload_to_book_images,  # Use the custom function
        storage=MediaStorage(),
        blank=True,
        null=True,
    )
    summary = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            # Truncate title if it's too long (allowing space for author names)
            title_slug = slugify(self.title)[:100]  # Allocate more space for title
            first_name_slug = slugify(self.author.first_name)[:40]
            last_name_slug = slugify(self.author.last_name)[:40]

            # Join the components
            self.slug = "-".join(
                (
                    title_slug,
                    first_name_slug,
                    last_name_slug,
                )
            )[
                :200
            ]  # Keep the overall length constraint
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["title"]),
        ]

    @property
    def title_url_friendly(self):
        return self.title.replace(" ", "+")

    @property
    def last_name_url_friendly(self):
        return self.author.last_name.replace(" ", "+")

    @property
    def first_name_url_friendly(self):
        return self.author.first_name.replace(" ", "+")


class BookCategory(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    year = models.IntegerField()  # Year of the award or nomination
    award_level = models.ForeignKey(
        AwardLevel, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        unique_together = ("book", "category", "year")  # Ensure no duplicate entries
        ordering = ["year", "award_level__order"]

    def __str__(self):
        award = self.award_level.name if self.award_level else "No Award"
        return f"{self.book.title} ({self.category.name} - {award} - {self.year})"


class SharedList(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_lists"
    )
    recipient_email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)  # For secure sharing links
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Optional expiration date

    def __str__(self):
        return f"List shared by {self.owner.username} to {self.recipient_email}"


class UserBookCategory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_book_categories",
    )
    book_category = models.ForeignKey(BookCategory, on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("user", "book_category")

    def __str__(self):
        return f"{self.user.username} - {self.book_category} ({'Completed' if self.completed else 'Not Completed'})"


class WebPlatform(models.Model):
    name = models.CharField(max_length=100)
    url = models.URLField()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Library(models.Model):
    name = models.CharField(max_length=200)  # Library name
    state = models.CharField(max_length=20)  # State
    description = models.TextField(blank=True)  # Optional description
    url_prefix = models.URLField()  # Base URL before search query
    url_suffix = models.CharField(
        max_length=200, blank=True
    )  # URL part after search query
    web_platform = models.ForeignKey(
        "WebPlatform", on_delete=models.CASCADE, blank=True, null=True
    )
    bibliocommons_id = models.CharField(max_length=400, blank=True)
    bibliocommons_number = models.IntegerField(blank=True, null=True)

    class Meta:
        ordering = ["state", "name"]  # Sort by state, then name

    def __str__(self):
        return f"{self.name} ({self.state})"

    @property
    def bibliocommons_library_id(self):
        """
        Extracts the subdomain from the url_prefix field.
        Example: "https://hclib.bibliocommons.com/v2/search?query="
        Returns: "hclib"
        """
        match = re.search(r"https://([\w-]+)\.bibliocommons\.com", self.url_prefix)
        return match.group(1) if match else None


class LocalBookstore(models.Model):
    name = models.CharField(max_length=200)  # Library name
    address = models.CharField(max_length=200, blank=True, null=True)  # Address
    state = models.CharField(max_length=20)  # State
    zip_code = models.CharField(max_length=10)  # Zip code
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )  # Longitude
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )  # Latitude
    description = models.TextField(blank=True)  # Optional description
    url_prefix = models.URLField(
        max_length=200, blank=True
    )  # Base URL before search query
    url_suffix = models.CharField(
        max_length=200, blank=True
    )  # URL part after search query
    web_platform = models.ForeignKey(
        "WebPlatform", on_delete=models.CASCADE, blank=True, null=True
    )

    class Meta:
        ordering = ["state", "name"]  # Sort by state, then name

    def __str__(self):
        return f"{self.name} ({self.state})"


class UserBook(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_books"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("user", "book")  # A user can have only one entry per book

    def __str__(self):
        return f"{self.user.username} - {self.book.title} ({'Completed' if self.completed else 'Not Completed'})"


class UserFavoriteLibrary(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    library = models.ForeignKey("Library", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "library"]
        ordering = ["library__name"]


class AwardYearLike(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liked_award_years",
    )
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    year = models.IntegerField()

    class Meta:
        unique_together = ("user", "category", "year")
        ordering = ["category__name", "year"]

    def __str__(self):
        return f"{self.user.username} likes {self.category.name} ({self.year})"


class WikiPageState(models.Model):
    """One row per Wikipedia page that one or more categories point to."""

    title = models.CharField(max_length=300, unique=True)  # e.g. "Newbery_Medal"
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_seen_revid = models.BigIntegerField(null=True, blank=True)
    last_processed_revid = models.BigIntegerField(null=True, blank=True)
    last_processed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title.replace("_", " ")

    @property
    def url(self):
        return f"https://en.wikipedia.org/wiki/{self.title}"


class PendingAward(models.Model):
    """A book/award entry found on Wikipedia that is not yet in BookCategory.

    Created by the sync command, reviewed and approved in the admin.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    MATCH_EXISTING = "existing_book"
    MATCH_NEW = "new_book"
    MATCH_CONFLICT = "check"
    MATCH_CHOICES = [
        (MATCH_EXISTING, "Existing book - add to category"),
        (MATCH_NEW, "New book"),
        (MATCH_CONFLICT, "Needs a look"),
    ]

    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    wiki_page = models.ForeignKey(
        WikiPageState, on_delete=models.SET_NULL, null=True, blank=True
    )
    wiki_revid = models.BigIntegerField(null=True, blank=True)
    year = models.IntegerField()
    title = models.CharField(max_length=200)
    author_first_name = models.CharField(max_length=100, blank=True)
    author_last_name = models.CharField(max_length=100)
    illustrator_first_name = models.CharField(max_length=100, blank=True)
    illustrator_last_name = models.CharField(max_length=100, blank=True)
    award_level = models.ForeignKey(
        AwardLevel, on_delete=models.SET_NULL, null=True, blank=True
    )
    level_text = models.CharField(
        max_length=100, blank=True, help_text="Level wording used on Wikipedia"
    )
    source_text = models.TextField(blank=True, help_text="Wikipedia text it came from")
    match_type = models.CharField(max_length=20, choices=MATCH_CHOICES)
    matched_book = models.ForeignKey(
        Book, on_delete=models.SET_NULL, null=True, blank=True
    )
    match_notes = models.TextField(blank=True)
    normalized_key = models.CharField(max_length=255, editable=False)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    book_category = models.ForeignKey(
        BookCategory, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["status", "category__name", "-year", "title"]
        constraints = [
            # A rejected proposal stays rejected: the sync never re-proposes it.
            models.UniqueConstraint(
                fields=["category", "year", "normalized_key"],
                name="unique_pending_award",
            )
        ]

    def __str__(self):
        return f"{self.title} ({self.category.name} {self.year})"

    @property
    def author_display(self):
        return f"{self.author_first_name} {self.author_last_name}".strip()
