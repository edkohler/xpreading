"""Orchestrates a sync run and applies approved proposals."""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import re

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from pages.models import (
    Author,
    AwardLevel,
    Book,
    BookCategory,
    Category,
    Illustrator,
    PendingAward,
    WikiPageState,
)

from . import extractor, wikipedia
from .matching import MatchIndex, primary_key

log = logging.getLogger(__name__)

EXAMPLES_PER_CATEGORY = 8


@dataclass
class PageResult:
    title: str
    status: str  # unchanged | processed | error | skipped
    revid: int = None
    created: int = 0
    already_listed: int = 0
    previously_reviewed: int = 0
    dropped: int = 0
    message: str = ""
    usage: dict = field(default_factory=dict)


def pages_to_categories(category_ids=None):
    """{wiki page title: [Category, ...]} for sync-enabled categories."""
    qs = (
        Category.objects.filter(wiki_sync_enabled=True)
        .exclude(wiki__isnull=True)
        .exclude(wiki="")
    )
    if category_ids:
        qs = qs.filter(id__in=category_ids)
    groups = defaultdict(list)
    for c in qs.order_by("id"):
        title = wikipedia.title_from_url(c.wiki)
        if title:
            groups[title].append(c)
    return dict(groups)


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize(value):
    """Strip NUL/control characters (PostgreSQL rejects NUL) from LLM output."""
    if isinstance(value, str):
        return _CONTROL_CHARS.sub("", value)
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    return value


def _person(p):
    return (p.get("first_name") or "").strip(), (p.get("last_name") or "").strip()


def category_context(category):
    rows = (
        BookCategory.objects.filter(category=category)
        .select_related("book__author", "book__illustrator", "award_level")
        .order_by("-year", "award_level__order", "book__title")
    )
    agg = rows.aggregate(Max("year"))
    years = list(rows.values_list("year", flat=True).distinct())
    level_counts = Counter(
        name or "none"
        for name in BookCategory.objects.filter(category=category).values_list(
            "award_level__name", flat=True
        )
    )
    examples = []
    for r in rows[:EXAMPLES_PER_CATEGORY]:
        b = r.book
        ill = f" / illus. {b.illustrator.full_name}" if b.illustrator else ""
        lvl = r.award_level.name if r.award_level else "none"
        examples.append(f"{r.year} | {lvl} | {b.title} | {b.author.full_name}{ill}")
    return {
        "id": category.id,
        "name": category.name,
        "section": wikipedia.section_from_url(category.wiki),
        "notes": category.wiki_sync_notes,
        "year_range": f"{min(years)}-{max(years)}" if years else "none yet",
        "max_year": agg["year__max"],
        "levels": ", ".join(f"{k} ({v})" for k, v in level_counts.most_common()),
        "examples": examples,
    }


BACKFILL_BATCH = 3  # new categories per OpenAI call when reading full history


def category_since(context, override=None):
    """First year to extract for a category.

    Categories with data: re-read the newest year we have (late honors get
    added) and everything after. New categories (no data yet): None = all years.
    """
    if override:
        return override
    if context["max_year"]:
        return context["max_year"] - 1
    return None


def extraction_batches(contexts):
    """Incremental categories share one call; new categories need their whole
    history, which is much more output, so they go a few at a time."""
    incremental = [c for c in contexts if c["since"]]
    backfill = [c for c in contexts if not c["since"]]
    batches = [incremental] if incremental else []
    for i in range(0, len(backfill), BACKFILL_BATCH):
        batches.append(backfill[i : i + BACKFILL_BATCH])
    return batches


def sync_page(
    title,
    categories,
    *,
    all_categories=None,
    since_year=None,
    dry_run=False,
    model=None,
    index=None,
    stdout=None,
):
    """Read one Wikipedia page for the given categories.

    all_categories: every category linked to the page (defaults to
    `categories`); the extra ones are named in the prompt so their entries
    are not mis-assigned.
    """
    all_categories = all_categories or categories
    state, _ = WikiPageState.objects.get_or_create(title=title)
    result = PageResult(title=title, status="processed")
    try:
        revid, raw = wikipedia.fetch_wikitext(title)
        text = wikipedia.clean_wikitext(raw)
        contexts = [category_context(c) for c in categories]
        for c in contexts:
            c["since"] = category_since(c, since_year)
        levels = list(
            AwardLevel.objects.order_by("order").values_list("name", flat=True)
        )
        entries, notes, total_tokens = [], [], 0
        batches = extraction_batches(contexts)
        for n, batch in enumerate(batches, 1):
            ids = {c["id"] for c in batch}
            others = [c.name for c in all_categories if c.id not in ids]
            if stdout and len(batches) > 1:
                names = ", ".join(c["name"] for c in batch)
                stdout.write(f"    batch {n}/{len(batches)}: {names}")
            batch_entries, batch_notes, usage = extractor.extract_entries(
                title, batch, levels, text, other_categories=others, model=model
            )
            entries += batch_entries
            if batch_notes:
                notes.append(batch_notes)
            total_tokens += (usage or {}).get("total_tokens", 0)
        entries = _sanitize(entries)
        result.revid, result.usage = revid, {"total_tokens": total_tokens}
        if notes:
            result.message = _sanitize(" | ".join(notes))[:300]
    except Exception as e:  # network, API, parsing
        log.exception("wiki sync failed for %s", title)
        state.last_error = f"{timezone.now():%Y-%m-%d %H:%M} {e}"[:2000]
        state.last_checked_at = timezone.now()
        if not dry_run:
            state.save()
        result.status, result.message = "error", str(e)[:300]
        return result

    since_by_cat = {c["id"]: c["since"] for c in contexts}
    index = index or MatchIndex.from_db()
    cats = {c.id: c for c in categories}
    level_by_name = {l.name: l for l in AwardLevel.objects.all()}
    seen = set()

    for e in entries:
        cat = cats.get(e["category_id"])
        title_txt = (e.get("title") or "").strip().strip("'\"*")
        authors = [_person(p) for p in e.get("authors") or [] if _person(p)[1]]
        illustrators = [
            _person(p) for p in e.get("illustrators") or [] if _person(p)[1]
        ]
        year = e.get("year")
        if (
            not cat
            or not title_txt
            or not year
            or (since_by_cat.get(cat.id) and year < since_by_cat[cat.id])
            or not (authors or illustrators)
        ):
            result.dropped += 1
            continue
        if not authors:  # only one creator shown -> treat as author
            authors, illustrators = illustrators, []
        key = primary_key(title_txt)
        if (cat.id, year, key) in seen:
            continue
        seen.add((cat.id, year, key))

        creator_lasts = [a[1] for a in authors] + [i[1] for i in illustrators]
        m = index.classify(cat.id, year, title_txt, creator_lasts)
        if m["status"] == "already_listed":
            result.already_listed += 1
            continue
        if PendingAward.objects.filter(
            category=cat, year=year, normalized_key=key
        ).exists():
            result.previously_reviewed += 1
            continue

        notes = m["notes"]
        if len(authors) > 1:
            extra = ", ".join(f"{f} {l}".strip() for f, l in authors[1:])
            notes = (
                notes + " " if notes else ""
            ) + f"Co-author(s) on Wikipedia: {extra}."
        if len(illustrators) > 1:
            extra = ", ".join(f"{f} {l}".strip() for f, l in illustrators[1:])
            notes = (
                notes + " " if notes else ""
            ) + f"Additional illustrator(s): {extra}."
        match_type = {
            "existing_book": PendingAward.MATCH_EXISTING,
            "new_book": PendingAward.MATCH_NEW,
        }.get(m["status"], PendingAward.MATCH_CONFLICT)

        if dry_run:
            result.created += 1
            if stdout:
                stdout.write(
                    f"    + [{cat.name}] {year} {e.get('award_level') or '-'}: {title_txt} "
                    f"by {authors[0][0]} {authors[0][1]} ({match_type}"
                    f"{' #' + str(m['book_id']) if m['book_id'] else ''}) {m['notes'][:120]}"
                )
            continue
        try:
            with transaction.atomic():
                PendingAward.objects.create(
                    category=cat,
                    wiki_page=state,
                    wiki_revid=revid,
                    year=year,
                    title=title_txt[:200],
                    author_first_name=authors[0][0][:100],
                    author_last_name=authors[0][1][:100],
                    illustrator_first_name=(illustrators[0][0] if illustrators else "")[
                        :100
                    ],
                    illustrator_last_name=(illustrators[0][1] if illustrators else "")[
                        :100
                    ],
                    award_level=level_by_name.get(e.get("award_level")),
                    level_text=(e.get("level_text") or "")[:100],
                    source_text=(e.get("source_text") or "")[:1000],
                    match_type=match_type,
                    matched_book_id=m["book_id"],
                    match_notes=notes.strip(),
                    normalized_key=key,
                )
            result.created += 1
        except IntegrityError:
            result.previously_reviewed += 1
        except DatabaseError as exc:  # one bad row must not stop the run
            log.warning(
                "wiki sync: could not save %r for %s: %s", title_txt, title, exc
            )
            result.dropped += 1

    if not dry_run:
        now = timezone.now()
        state.last_seen_revid = revid
        state.last_processed_revid = revid
        state.processed_category_ids = sorted(
            set(state.processed_category_ids or []) | {c.id for c in categories}
        )
        state.last_processed_at = now
        state.last_checked_at = now
        state.last_error = ""
        state.save()
    return result


def run_sync(
    *,
    force=False,
    dry_run=False,
    only_pages=None,
    category_ids=None,
    since_year=None,
    model=None,
    stdout=None,
):
    groups = pages_to_categories(category_ids)
    if only_pages:
        wanted = {p.replace(" ", "_") for p in only_pages}
        groups = {t: c for t, c in groups.items() if t in wanted}
    revs = wikipedia.latest_revisions(groups.keys())
    index = MatchIndex.from_db()
    results = []
    for title, cats in sorted(groups.items()):
        info = revs.get(title, {})
        state = WikiPageState.objects.filter(title=title).first()
        if info.get("missing"):
            r = PageResult(title, "error", message="page not found on Wikipedia")
            if state and not dry_run:
                state.last_error = r.message
                state.last_checked_at = timezone.now()
                state.save()
            results.append(r)
            continue
        to_read = cats
        if not force and state and state.last_processed_revid == info.get("revid"):
            # Page unchanged: only read categories added since the last read.
            done = set(state.processed_category_ids or [])
            to_read = [c for c in cats if c.id not in done]
            if not to_read:
                if not dry_run:
                    state.last_checked_at = timezone.now()
                    state.last_seen_revid = info.get("revid")
                    state.save(update_fields=["last_checked_at", "last_seen_revid"])
                results.append(PageResult(title, "unchanged", revid=info.get("revid")))
                continue
        if stdout:
            n = len(to_read)
            extra = f" of {len(cats)}" if n != len(cats) else ""
            stdout.write(
                f"  {title} ({n}{extra} categor{'y' if n == 1 else 'ies'}) ..."
            )
        try:
            results.append(
                sync_page(
                    title,
                    to_read,
                    all_categories=cats,
                    since_year=since_year,
                    dry_run=dry_run,
                    model=model,
                    index=index,
                    stdout=stdout,
                )
            )
        except Exception as exc:  # keep going with the other pages
            log.exception("wiki sync crashed on %s", title)
            results.append(PageResult(title, "error", message=str(exc)[:300]))
    return results


# ---------------------------------------------------------------- approval


def _get_or_create_person(model, first, last):
    first, last = (first or "").strip(), (last or "").strip()
    if not first:
        first = last  # single-name creators are stored with first == last
    obj = model.objects.filter(first_name__iexact=first, last_name__iexact=last).first()
    return obj or model.objects.create(first_name=first, last_name=last)


def _unique_slug(book):
    from django.utils.text import slugify

    base = "-".join(
        (
            slugify(book.title)[:100],
            slugify(book.author.first_name)[:40],
            slugify(book.author.last_name)[:40],
        )
    )[:200]
    slug, n = base, 2
    while Book.objects.filter(slug=slug).exists():
        slug = f"{base[:195]}-{n}"
        n += 1
    return slug


@transaction.atomic
def approve(pending, move_existing=False):
    """Create/link the book and the BookCategory row. Returns the BookCategory.

    move_existing=True: if the matched book is already in this category under a
    different year (a data-entry error), change that row's year instead of
    adding a second row.
    """
    if pending.status == PendingAward.STATUS_APPROVED and pending.book_category_id:
        return pending.book_category
    if move_existing and pending.matched_book_id:
        existing = BookCategory.objects.filter(
            book_id=pending.matched_book_id, category=pending.category
        ).exclude(year=pending.year)
        if (
            existing.count() == 1
            and not BookCategory.objects.filter(
                book_id=pending.matched_book_id,
                category=pending.category,
                year=pending.year,
            ).exists()
        ):
            bc = existing.get()
            bc.year = pending.year
            if pending.award_level_id:
                bc.award_level = pending.award_level
            bc.save(update_fields=["year", "award_level"])
            pending.book_category = bc
            pending.status = PendingAward.STATUS_APPROVED
            pending.reviewed_at = timezone.now()
            pending.save()
            return bc
    book = pending.matched_book
    if book is None:
        author = _get_or_create_person(
            Author, pending.author_first_name, pending.author_last_name
        )
        illustrator = None
        if pending.illustrator_last_name:
            illustrator = _get_or_create_person(
                Illustrator,
                pending.illustrator_first_name,
                pending.illustrator_last_name,
            )
        book = Book(title=pending.title, author=author, illustrator=illustrator)
        book.slug = _unique_slug(book)
        book.save()
        pending.matched_book = book
    bc, created = BookCategory.objects.get_or_create(
        book=book,
        category=pending.category,
        year=pending.year,
        defaults={"award_level": pending.award_level},
    )
    if not created and bc.award_level_id is None and pending.award_level_id:
        bc.award_level = pending.award_level
        bc.save(update_fields=["award_level"])
    pending.book_category = bc
    pending.status = PendingAward.STATUS_APPROVED
    pending.reviewed_at = timezone.now()
    pending.save()
    return bc


def reject(pending):
    pending.status = PendingAward.STATUS_REJECTED
    pending.reviewed_at = timezone.now()
    pending.save(update_fields=["status", "reviewed_at"])
