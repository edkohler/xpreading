from import_export import resources

from .models import Author, Book, BookCategory, Category, Illustrator, Library


class LibraryResource(resources.ModelResource):
    class Meta:
        model = Library
        fields = (
            "id",
            "name",
            "state",
            "description",
            "url_prefix",
            "url_suffix",
            "web_platform__name",
        )  # Specify fields to include
        export_order = (
            "id",
            "name",
            "state",
            "description",
            "url_prefix",
            "url_suffix",
            "web_platform__name",
        )  # Order of fields


class BookResource(resources.ModelResource):
    class Meta:
        model = Library
        fields = (
            "id",
            "title",
            "author",
            "categories",
            "isbn",
            "page_count",
            "bibliocommons_id",
            "asin",
        )  # Specify fields to include
        export_order = (
            "id",
            "title",
            "author",
            "categories",
            "isbn",
            "page_count",
            "bibliocommons_id",
            "asin",
        )  # Order of fields


class AuthorResource(resources.ModelResource):
    class Meta:
        model = Author
        fields = ("id", "first_name", "last_name")  # Specify fields to include
        export_order = ("id", "first_name", "last_name")  # Order of fields


class IllustratorResource(resources.ModelResource):
    class Meta:
        model = Illustrator
        fields = ("id", "first_name", "last_name")  # Specify fields to include
        export_order = ("id", "first_name", "last_name")  # Order of fields


class BookCategoryResource(resources.ModelResource):
    class Meta:
        model = BookCategory
        fields = (
            "id",
            "book",
            "category",
            "award_level",
            "year",
        )  # Specify fields to include
        export_order = (
            "id",
            "book",
            "category",
            "award_level",
            "year",
        )  # Order of fields


class CategoryResource(resources.ModelResource):
    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "description",
            "new_books_release_day_of_year",
        )  # Specify fields to include
        export_order = (
            "id",
            "name",
            "description",
            "new_books_release_day_of_year",
        )  # Order of fields
