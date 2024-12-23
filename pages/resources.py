from import_export import resources
from .models import Library

class LibraryResource(resources.ModelResource):
    class Meta:
        model = Library
        fields = ('id', 'name', 'state', 'description', 'url_prefix', 'url_suffix', 'web_platform__name')  # Specify fields to include
        export_order = ('id', 'name', 'state', 'description', 'url_prefix', 'url_suffix', 'web_platform__name')  # Order of fields
