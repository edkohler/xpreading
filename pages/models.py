from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.contrib.auth import get_user_model
import re

import os
import uuid

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
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:50]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AwardLevel(models.Model):
    name = models.CharField(max_length=50, unique=True)  # e.g., "Nominee", "Gold", "1st"
    order = models.IntegerField()  # Used to sort levels (e.g., 1 = "Gold", 2 = "Silver")

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name

class Author(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    categories = models.ManyToManyField(Category, through='BookCategory')
    isbn = models.CharField(max_length=13, blank=True, null=True)
    page_count = models.CharField(max_length=5, blank=True, null=True)
    bibliocommons_id = models.CharField(max_length=20, blank=True, null=True)
    asin = models.CharField(max_length=20, blank=True, null=True)
    slug = models.SlugField(blank=True)
    image = models.ImageField(
        upload_to=upload_to_book_images,  # Use the custom function
        blank=True,
        null=True
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = '-'.join((slugify(self.title), slugify(self.author.first_name), slugify(self.author.last_name)))[:50]

        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def title_url_friendly(self):
        return self.title.replace(' ', '+')

    @property
    def last_name_url_friendly(self):
        return self.author.last_name.replace(' ', '+')

    @property
    def first_name_url_friendly(self):
        return self.author.first_name.replace(' ', '+')

class BookCategory(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    year = models.IntegerField()  # Year of the award or nomination
    award_level = models.ForeignKey(AwardLevel, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = ('book', 'category', 'year')  # Ensure no duplicate entries
        ordering = ['year', 'award_level__order']

    def __str__(self):
        award = self.award_level.name if self.award_level else "No Award"
        return f"{self.book.title} ({self.category.name} - {award} - {self.year})"


class SharedList(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='shared_lists')
    recipient_email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)  # For secure sharing links
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Optional expiration date

    def __str__(self):
        return f"List shared by {self.owner.username} to {self.recipient_email}"


class UserBookCategory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_book_categories')
    book_category = models.ForeignKey(BookCategory, on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'book_category')

    def __str__(self):
        return f"{self.user.username} - {self.book_category} ({'Completed' if self.completed else 'Not Completed'})"

class WebPlatform(models.Model):
    name = models.CharField(max_length=100)
    url = models.URLField()

    def __str__(self):
        return self.name

class Library(models.Model):
    name = models.CharField(max_length=200)  # Library name
    state = models.CharField(max_length=20)  # State
    description = models.TextField(blank=True)  # Optional description
    url_prefix = models.URLField()  # Base URL before search query
    url_suffix = models.CharField(max_length=200, blank=True)  # URL part after search query
    web_platform = models.ForeignKey('WebPlatform', on_delete=models.CASCADE, blank=True, null=True)
    bibliocommons_id = models.CharField(max_length=400, blank=True)
    class Meta:
        ordering = ['state', 'name']  # Sort by state, then name

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
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)  # Longitude
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)  # Latitude
    description = models.TextField(blank=True)  # Optional description
    url_prefix = models.URLField(max_length=200, blank=True)  # Base URL before search query
    url_suffix = models.CharField(max_length=200, blank=True)  # URL part after search query
    web_platform = models.ForeignKey('WebPlatform', on_delete=models.CASCADE, blank=True, null=True)
    class Meta:
        ordering = ['state', 'name']  # Sort by state, then name

    def __str__(self):
        return f"{self.name} ({self.state})"

class UserBook(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_books')
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'book')  # A user can have only one entry per book

    def __str__(self):
        return f"{self.user.username} - {self.book.title} ({'Completed' if self.completed else 'Not Completed'})"



class UserFavoriteLibrary(models.Model):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    library = models.ForeignKey('Library', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'library']


class AwardYearLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="liked_award_years")
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    year = models.IntegerField()

    class Meta:
        unique_together = ('user', 'category', 'year')
        ordering = ['category__name', 'year']

    def __str__(self):
        return f"{self.user.username} likes {self.category.name} ({self.year})"
