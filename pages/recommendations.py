"""
"Best next reads" for the XP report.

XP rules (see xp_report): 1 point per page, 100 per finished book, and 500 per
finished book list (category + year) that the user has liked.

Pages and the per-book bonus are earned whichever book a reader picks, so what
separates one choice from another is how much it moves them toward list
bonuses. Each unread book gets a share of every list it appears on:

    list credit = 500 / (unread books left on that list)

A book that is the last one left on a list earns the full 500; one of four left
earns 125. Credits add up, so a single book that sits on several nearly-finished
lists rises to the top. Lists the user hasn't liked don't pay out yet, so they
count at UNLIKED_WEIGHT and are only considered once the reader has already made
real progress on them (the same threshold the report uses for "Other Lists").
"""

from collections import defaultdict

from .models import Book

POINTS_PER_BOOK = 100
POINTS_PER_LIST = 500
UNLIKED_WEIGHT = 0.5
UNLIKED_MIN_PROGRESS = 0.3


def suggest_books(
    books_by_list,
    user_completed_books,
    liked_award_years,
    categories_info,
    limit=10,
):
    """
    Return up to ``limit`` suggested books, best first.

    Arguments are the structures xp_report already builds, so no extra
    BookCategory queries are needed:
      books_by_list: {(category_id, year): [book_id, ...]}
      user_completed_books: set of completed book ids
      liked_award_years: set of (category_id, year)
      categories_info: {category_id: {"name": ..., "slug": ...}}
    """
    # book_id -> list of contributions from each list it would advance
    contributions = defaultdict(list)

    for (category_id, year), book_ids in books_by_list.items():
        list_books = set(book_ids)
        unread = list_books - user_completed_books
        if not unread:
            continue  # already finished

        liked = (category_id, year) in liked_award_years
        progress = 1 - len(unread) / len(list_books)
        if not liked and progress < UNLIKED_MIN_PROGRESS:
            continue

        remaining = len(unread)
        credit = POINTS_PER_LIST / remaining
        weight = 1.0 if liked else UNLIKED_WEIGHT
        list_info = {
            "category": categories_info[category_id]["name"],
            "category_slug": categories_info[category_id]["slug"],
            "year": year,
            "liked": liked,
            "remaining": remaining,
            "completes_list": remaining == 1,
            "credit": round(credit),
        }
        for book_id in unread:
            contributions[book_id].append((credit * weight, list_info))

    if not contributions:
        return []

    books = Book.objects.filter(id__in=contributions.keys()).select_related(
        "author", "illustrator"
    )
    suggestions = []
    for book in books:
        entries = contributions[book.id]
        list_score = sum(score for score, _ in entries)
        lists = [info for _, info in entries]
        lists.sort(key=lambda i: (not i["liked"], i["remaining"]))
        liked_lists = [i for i in lists if i["liked"]]
        pages = book.page_count or 0
        lists_finished_now = [i for i in liked_lists if i["completes_list"]]
        suggestions.append(
            {
                "book": book,
                "pages": book.page_count,
                "list_score": round(list_score),
                "lists": lists,
                "liked_list_count": len(liked_lists),
                "lists_finished_now": len(lists_finished_now),
                # XP banked immediately on finishing this book
                "immediate_xp": pages
                + POINTS_PER_BOOK
                + POINTS_PER_LIST * len(lists_finished_now),
            }
        )

    # Highest list credit first; then books touching more liked lists; then
    # shorter books (quicker XP) as the tie-breaker.
    suggestions.sort(
        key=lambda s: (
            -s["list_score"],
            -s["liked_list_count"],
            s["pages"] if s["pages"] else 10**6,
            s["book"].title,
        )
    )
    return suggestions[:limit]
