from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

# Register your models here.
from .models import (
    Author,
    AwardLevel,
    Book,
    BookCategory,
    Category,
    Illustrator,
    Library,
    PendingAward,
    UserBook,
    UserBookCategory,
    WebPlatform,
    WikiPageState,
)
from .resources import (
    AuthorResource,
    BookCategoryResource,
    BookResource,
    CategoryResource,
    LibraryResource,
)


@admin.register(Author)
class AuthorAdmin(ImportExportModelAdmin):
    list_display = ("id", "first_name", "last_name")
    search_fields = [
        "first_name",
        "last_name",
    ]


@admin.register(Illustrator)
class IllustratorAdmin(ImportExportModelAdmin):
    list_display = ("id", "first_name", "last_name")


@admin.register(Book)
class BookAdmin(ImportExportModelAdmin):
    list_display = ("id", "title", "author")
    search_fields = [
        "title",
        "author__first_name",
        "author__last_name",
        "bibliocommons_id",
        "asin",
    ]


@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    list_display = ("id", "name", "new_books_release_day_of_year", "wiki_sync_enabled")
    list_filter = ("wiki_sync_enabled",)
    search_fields = ["name", "wiki"]


@admin.register(AwardLevel)
class AwardLevelAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "order")


@admin.register(BookCategory)
class BookCategoryAdmin(ImportExportModelAdmin):
    list_display = ("id", "book", "category", "year", "award_level")
    list_filter = ("category", "year", "award_level")


@admin.register(Library)
class LibraryAdmin(ImportExportModelAdmin):
    list_display = ("id", "name", "state", "url_prefix")
    search_fields = ("name", "state")


@admin.register(WebPlatform)
class WebPlatformAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(UserBook)
class UserBookAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "book", "completed")


@admin.register(UserBookCategory)
class UserBookCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "book_category", "completed")


# ------------------------------------------------------------- Wikipedia sync


@admin.register(PendingAward)
class PendingAwardAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "author_display",
        "category",
        "year",
        "award_level",
        "level_text",
        "match_type",
        "matched_book",
        "status",
        "created_at",
    )
    list_filter = ("status", "match_type", "year", "category")
    search_fields = ("title", "author_last_name", "category__name")
    raw_id_fields = ("matched_book", "book_category")
    readonly_fields = (
        "wiki_link",
        "wiki_revid",
        "source_text",
        "match_notes",
        "created_at",
        "reviewed_at",
        "book_category",
    )
    fields = (
        "status",
        "category",
        "year",
        "title",
        ("author_first_name", "author_last_name"),
        ("illustrator_first_name", "illustrator_last_name"),
        ("award_level", "level_text"),
        "match_type",
        "matched_book",
        "match_notes",
        "source_text",
        "wiki_link",
        "wiki_revid",
        "book_category",
        "created_at",
        "reviewed_at",
    )
    actions = ["approve_selected", "approve_moving_existing", "reject_selected"]
    list_per_page = 100

    @admin.display(description="Author")
    def author_display(self, obj):
        return obj.author_display

    @admin.display(description="Wikipedia")
    def wiki_link(self, obj):
        from django.utils.html import format_html

        if not obj.wiki_page:
            return "-"
        url = obj.wiki_page.url
        if obj.wiki_revid:
            url = f"https://en.wikipedia.org/w/index.php?oldid={obj.wiki_revid}"
        return format_html('<a href="{}" target="_blank">{}</a>', url, obj.wiki_page)

    @admin.action(
        description="Approve selected (add to category, create book if needed)"
    )
    def approve_selected(self, request, queryset, move_existing=False):
        from pages.wiki_sync.service import approve

        done, failed = 0, []
        for p in queryset.exclude(status=PendingAward.STATUS_APPROVED):
            try:
                approve(p, move_existing=move_existing)
                done += 1
            except Exception as e:
                failed.append(f"{p.title}: {e}")
        self.message_user(request, f"Approved {done}.")
        if failed:
            self.message_user(
                request, "Failed: " + "; ".join(failed[:10]), level="error"
            )

    @admin.action(
        description="Approve, fixing the year of the existing entry (for 'already in "
        "this category under year X' items)"
    )
    def approve_moving_existing(self, request, queryset):
        return self.approve_selected(request, queryset, move_existing=True)

    @admin.action(description="Reject selected (won't be proposed again)")
    def reject_selected(self, request, queryset):
        from pages.wiki_sync.service import reject

        n = 0
        for p in queryset.filter(status=PendingAward.STATUS_PENDING):
            reject(p)
            n += 1
        self.message_user(request, f"Rejected {n}.")


@admin.register(WikiPageState)
class WikiPageStateAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "last_checked_at",
        "last_processed_at",
        "last_processed_revid",
        "has_error",
    )
    search_fields = ("title",)
    readonly_fields = ("last_seen_revid",)

    @admin.display(boolean=True, description="Error")
    def has_error(self, obj):
        return bool(obj.last_error)
