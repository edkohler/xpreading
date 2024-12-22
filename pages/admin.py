from django.contrib import admin

# Register your models here.
from .models import Author, Book, Category, AwardLevel, BookCategory, Library

@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name')

@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'author')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(AwardLevel)
class AwardLevelAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')

@admin.register(BookCategory)
class BookCategoryAdmin(admin.ModelAdmin):
    list_display = ('book', 'category', 'year', 'award_level')
    list_filter = ('category', 'year', 'award_level')


@admin.register(Library)
class LibraryAdmin(admin.ModelAdmin):
    list_display = ('name', 'state', 'url_prefix')
    search_fields = ('name', 'state')
