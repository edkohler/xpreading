from import_export import resources
from .models import Library, Book, Author

class LibraryResource(resources.ModelResource):
    class Meta:
        model = Library
        fields = ('id', 'name', 'state', 'description', 'url_prefix', 'url_suffix', 'web_platform__name')  # Specify fields to include
        export_order = ('id', 'name', 'state', 'description', 'url_prefix', 'url_suffix', 'web_platform__name')  # Order of fields


class BookResource(resources.ModelResource):
    class Meta:
        model = Library
        fields = ('id', 'title', 'author', 'categories', 'isbn', 'page_count', 'bibliocommons_id', 'asin')  # Specify fields to include
        export_order = ('id', 'title', 'author', 'categories', 'isbn', 'page_count', 'bibliocommons_id', 'asin')  # Order of fields


class AuthorResource(resources.ModelResource):
    class Meta:
        model = Author
        fields = ('id', 'first_name', 'last_name')  # Specify fields to include
        export_order = ('id', 'first_name', 'last_name')  # Order of fields
