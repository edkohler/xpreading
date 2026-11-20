"""Save catalog lookups and apply review decisions (used by the command and admin)."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from pages import bibliocommons as bc
from pages.models import BiblioCommonsLookup as Lookup
from pages.models import Book


def books_to_check(recheck_days=30, include_rejected=False, book_ids=None):
    """Books with no BiblioCommons ID that are due for a (re)search.

    Due: never searched, last search failed, or "not found" more than
    `recheck_days` ago (catalogs add records over time). Books waiting in
    "Review matches" are skipped so a decision isn't overwritten.
    """
    qs = Book.objects.filter(Q(bibliocommons_id__isnull=True) | Q(bibliocommons_id=""))
    if book_ids:
        return qs.filter(id__in=book_ids).select_related("author")
    due = Q(bibliocommons_lookup__isnull=True) | Q(
        bibliocommons_lookup__match_type=Lookup.MATCH_ERROR
    )
    if recheck_days is not None:
        cutoff = timezone.now() - timedelta(days=recheck_days)
        due |= Q(
            bibliocommons_lookup__match_type=Lookup.MATCH_NOT_FOUND,
            bibliocommons_lookup__checked_at__lt=cutoff,
        )
        if include_rejected:
            due |= Q(
                bibliocommons_lookup__review_status=Lookup.STATUS_REJECTED,
                bibliocommons_lookup__checked_at__lt=cutoff,
            )
    return qs.filter(due).select_related("author").order_by("id")


def search_book(client, book):
    author = book.author
    return client.lookup(book.title, author.first_name, author.last_name)


@transaction.atomic
def save_result(book, match, library=bc.DEFAULT_LIBRARY, auto_approve_close=False):
    """Store a Match for a book; fill the book's ID when it's safe to."""
    auto = match.match_type == bc.EXACT or (
        auto_approve_close and match.match_type == bc.CLOSE
    )
    if match.match_type in (bc.NOT_FOUND, bc.ERROR):
        status = Lookup.STATUS_PENDING
    else:
        status = Lookup.STATUS_AUTO if auto else Lookup.STATUS_PENDING
    lookup, _ = Lookup.objects.update_or_create(
        book=book,
        defaults=dict(
            library=library,
            match_type=match.match_type,
            review_status=status,
            candidate_id=match.record_id,
            catalog_title=match.title[:500],
            catalog_author=match.authors[:300],
            catalog_format=match.format[:50],
            query=match.query[:500],
            error=match.error,
            checked_at=timezone.now(),
            reviewed_at=None,
        ),
    )
    if auto and match.record_id:
        Book.objects.filter(pk=book.pk).update(bibliocommons_id=match.record_id)
    return lookup


@transaction.atomic
def approve(lookup):
    if not lookup.candidate_id:
        raise ValueError("no candidate record to approve")
    Book.objects.filter(pk=lookup.book_id).update(bibliocommons_id=lookup.candidate_id)
    lookup.review_status = Lookup.STATUS_APPROVED
    lookup.reviewed_at = timezone.now()
    lookup.save(update_fields=["review_status", "reviewed_at"])


def reject(lookup):
    lookup.review_status = Lookup.STATUS_REJECTED
    lookup.reviewed_at = timezone.now()
    lookup.save(update_fields=["review_status", "reviewed_at"])
