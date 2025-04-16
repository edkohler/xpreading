from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

# Register your models here.
from .models import (Author, AwardLevel, Book, BookCategory, Category,
                     Illustrator, Library, UserBook, UserBookCategory,
                     WebPlatform)
from .resources import (AuthorResource, BookCategoryResource, BookResource,
                        CategoryResource, LibraryResource)


@admin.register(Author)
class AuthorAdmin(ImportExportModelAdmin):
    list_display = ("first_name", "last_name")


@admin.register(Illustrator)
class IllustratorAdmin(ImportExportModelAdmin):
    list_display = ("first_name", "last_name")


@admin.register(Book)
class BookAdmin(ImportExportModelAdmin):
    list_display = ("title", "author")
    search_fields = [
        "title",
        "author__first_name",
        "author__last_name",
        "bibliocommons_id",
        "asin",
    ]


@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    list_display = ("name", "new_books_release_day_of_year")


@admin.register(AwardLevel)
class AwardLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "order")


@admin.register(BookCategory)
class BookCategoryAdmin(ImportExportModelAdmin):
    list_display = ("book", "category", "year", "award_level")
    list_filter = ("category", "year", "award_level")


@admin.register(Library)
class LibraryAdmin(ImportExportModelAdmin):
    list_display = ("name", "state", "url_prefix")
    search_fields = ("name", "state")


@admin.register(WebPlatform)
class WebPlatformAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(UserBook)
class UserBookAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "completed")


@admin.register(UserBookCategory)
class UserBookCategoryAdmin(admin.ModelAdmin):
    list_display = ("user", "book_category", "completed")
