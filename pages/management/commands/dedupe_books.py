"""
Find duplicate books in the database and merge them.

    python manage.py dedupe_books                      # dry run, high-confidence groups
    python manage.py dedupe_books --report dupes.csv   # also write the groups to a CSV
    python manage.py dedupe_books --apply              # merge high-confidence groups
    python manage.py dedupe_books --confidence medium  # include medium (or review)
    python manage.py dedupe_books --decisions dupes.csv --apply
        # merge exactly the groups marked "merge" in the Decision column;
        # the row whose action is "KEEP" is the book kept (move it to override)

Merging a group:
  * keeps the most complete record (BiblioCommons ID, ASIN, page count, image,
    clean slug; then most award entries; then lowest id) and its slug
  * sets its title to the longest title in the group (ignoring titles cut short
    with "…" and "by Author" suffixes)
  * fills its empty fields (isbn, page_count, bibliocommons_id, asin,
    illustrator, image) from the duplicates
  * moves award entries (BookCategory); where the kept book already has the
    same category + year, the two are combined, keeping the better award level
  * moves users' checkmarks (UserBookCategory) and read marks (UserBook);
    a user with marks on both copies keeps one, completed if either was
  * points Wikipedia-sync PendingAward rows (matched_book, book_category)
    at the kept book and award entry
  * deletes the duplicates, then (after the transaction commits) deletes their
    cover images from storage unless another book still uses the file

Each group is merged in its own transaction. A dry run performs the same work
and rolls it back, so its counts are exact.
"""
import csv
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pages.dedupe import (BYLINE, ELLIPSIS, HIGH, LEVELS, find_pairs, group_pairs, l3,
                          norm_asin, split_title)
from pages.models import Book, BookCategory, PendingAward, UserBook, UserBookCategory

LEADING_ARTICLE = re.compile(r"^(The|A|An)\s+", re.I)
FILL_FIELDS = ["isbn", "page_count", "bibliocommons_id", "asin", "illustrator_id"]


class DryRun(Exception):
    pass


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def completeness(book, award_count):
    score = 0
    score += 3 if not _blank(book.bibliocommons_id) else 0
    score += 2 if not _blank(book.asin) else 0
    score += 1 if book.page_count else 0
    score += 1 if book.image else 0
    score += 1 if not re.search(r"-\d+$", book.slug or "") else 0
    return (score, award_count, -book.id)


def best_title(books, keeper):
    """Longest title, skipping truncated ones and dropping "by Author" suffixes."""
    cands = [BYLINE.sub("", b.title).strip() for b in books if not ELLIPSIS.search(b.title)]
    cands = cands or [keeper.title]
    longest = max(len(t) for t in cands)
    keeper_clean = BYLINE.sub("", keeper.title).strip()
    if len(keeper_clean) == longest:  # prefer the kept book's spelling on a tie
        title = keeper_clean
    else:
        title = next(t for t in cands if len(t) == longest)
    # "Dark-Thirty: Southern Tales" + "The Dark-Thirty" -> "The Dark-Thirty: Southern Tales"
    if not LEADING_ARTICLE.match(title):
        main = l3(split_title(title)[0])
        for b in books:
            m = LEADING_ARTICLE.match(b.title.strip())
            if m and l3(split_title(b.title)[0]) == main:
                return f"{m.group(1)} {title}"
    return title


def better_level(a, b):
    """Lower AwardLevel.order is the better award (1 = Gold). None is worst."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a.order <= b.order else b


class Command(BaseCommand):
    help = "Find duplicate books and merge them (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write changes. Without it, nothing is saved.")
        parser.add_argument("--confidence", choices=list(LEVELS), default=HIGH,
                            help="Lowest confidence to merge (default: high).")
        parser.add_argument("--decisions", metavar="CSV",
                            help="Merge only the groups marked 'merge' in this CSV "
                                 "(columns: group, id, Decision), instead of detecting.")
        parser.add_argument("--report", metavar="CSV",
                            help="Write the groups found to this CSV (with an empty Decision column).")
        parser.add_argument("--keep-images", action="store_true",
                            help="Don't delete duplicates' cover images from storage.")
        parser.add_argument("--limit", type=int, help="Only process the first N groups.")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self._check_relations()
        if opts["decisions"]:
            groups = self._groups_from_csv(opts["decisions"])
        else:
            groups = self._detect(opts["confidence"])
        if opts["limit"]:
            groups = groups[: opts["limit"]]
        if not groups:
            self.stdout.write("No duplicate groups found.")
            return

        books = Book.objects.in_bulk([i for g in groups for i in g["ids"]])
        award_counts = {}
        for bc in BookCategory.objects.filter(book_id__in=books).values_list("book_id", flat=True):
            award_counts[bc] = award_counts.get(bc, 0) + 1

        report_rows, totals = [], dict(groups=0, deleted=0, awards_moved=0, awards_combined=0,
                                       marks_moved=0, marks_combined=0, images=0, errors=0)
        mode = "APPLYING" if opts["apply"] else "DRY RUN (nothing will be saved)"
        self.stdout.write(self.style.WARNING(f"{mode}: {len(groups)} groups\n"))

        for n, g in enumerate(groups, 1):
            members = [books[i] for i in g["ids"] if i in books]
            if len(members) < 2:
                continue
            members.sort(key=lambda b: completeness(b, award_counts.get(b.id, 0)), reverse=True)
            if g.get("keep") in books:  # KEEP chosen in the decisions file
                members.sort(key=lambda b: b.id != g["keep"])
            elif g.get("keep"):
                self.stdout.write(self.style.ERROR(
                    f"[{n}] KEEP book {g['keep']} no longer exists; skipping group"))
                continue
            keeper, dups = members[0], members[1:]
            new_title = best_title(members, keeper)

            self.stdout.write(f"[{n}] {g['confidence']}: {', '.join(g['reasons'])}")
            self.stdout.write(f"    KEEP  {keeper.id}: {keeper.title}  ({keeper.slug})")
            for d in dups:
                self.stdout.write(f"    merge {d.id}: {d.title}  ({d.slug})")
            if new_title != keeper.title:
                self.stdout.write(f"    title -> {new_title}")

            for b in members:
                report_rows.append([n, g["confidence"], " | ".join(g["reasons"]),
                                    "KEEP" if b is keeper else f"merge into {keeper.id}",
                                    b.id, b.title, b.author_id, b.asin or "",
                                    b.bibliocommons_id or "", b.slug, award_counts.get(b.id, 0), ""])

            try:
                stats = self._merge(keeper, dups, new_title, opts["apply"], opts["keep_images"])
            except Exception as e:  # one bad group shouldn't stop the run
                totals["errors"] += 1
                self.stdout.write(self.style.ERROR(f"    FAILED, group left unchanged: {e}"))
                continue
            self.stdout.write(
                f"    awards moved {stats['awards_moved']}, combined {stats['awards_combined']}; "
                f"user marks moved {stats['marks_moved']}, combined {stats['marks_combined']}; "
                f"images to delete {stats['images']}"
            )
            totals["groups"] += 1
            totals["deleted"] += len(dups)
            for k in stats:
                totals[k] += stats[k]

        if opts["report"]:
            with open(opts["report"], "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["group", "confidence", "reasons", "action", "id", "title", "author_id",
                            "asin", "bibliocommons_id", "slug", "award_entries", "Decision"])
                w.writerows(report_rows)
            self.stdout.write(f"\nReport written to {opts['report']}")

        verb = "Merged" if opts["apply"] else "Would merge"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb} {totals['groups']} groups, deleting {totals['deleted']} books. "
            f"Awards moved {totals['awards_moved']}, combined {totals['awards_combined']}. "
            f"User marks moved {totals['marks_moved']}, combined {totals['marks_combined']}. "
            f"Images {'deleted' if opts['apply'] else 'to delete'}: {totals['images']}. "
            f"Failed groups: {totals['errors']}."
        ))

    # ------------------------------------------------------------------
    def _check_relations(self):
        """Refuse to run if a model we don't know how to merge points at Book
        or BookCategory (a new model would otherwise be silently cascaded)."""
        handled = {
            Book: {BookCategory, UserBook, PendingAward},
            BookCategory: {UserBookCategory, PendingAward},
        }
        unknown = [
            f"{rel.related_model._meta.label}.{rel.field.name}"
            for model, ok in handled.items()
            for rel in model._meta.related_objects
            if rel.related_model not in ok and not rel.many_to_many
        ]
        if unknown:
            raise CommandError(
                "These models reference Book and aren't handled by the merge yet: "
                + ", ".join(unknown)
            )

    def _detect(self, confidence):
        records = Book.objects.values("id", "title", "author_id", "illustrator_id",
                                      "asin", "bibliocommons_id")
        _, pairs = find_pairs(records)
        groups = group_pairs(pairs, confidence)
        return sorted(groups, key=lambda g: (g["confidence"] != HIGH, g["ids"][0]))

    def _groups_from_csv(self, path):
        groups = {}
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                g = groups.setdefault(row["group"], dict(ids=[], merge=False, keep=[]))
                g["ids"].append(int(row["id"]))
                if row.get("action", "").upper() == "KEEP":
                    g["keep"].append(int(row["id"]))
                if row.get("decision", "").lower() == "merge":
                    g["merge"] = True
        out = []
        for name, g in groups.items():
            if not g["merge"]:
                continue
            if len(g["keep"]) > 1:
                raise CommandError(f"Group {name} in {path} has more than one KEEP row.")
            out.append(dict(ids=sorted(g["ids"]), confidence="decided",
                            reasons=["from " + path], keep=g["keep"][0] if g["keep"] else None))
        return out

    # ------------------------------------------------------------------
    def _merge(self, keeper, dups, new_title, apply, keep_images):
        stats = dict(awards_moved=0, awards_combined=0, marks_moved=0, marks_combined=0, images=0)
        images_to_delete = []
        try:
            with transaction.atomic():
                keeper = Book.objects.select_for_update().get(pk=keeper.pk)
                changed = set()
                if new_title != keeper.title:
                    keeper.title = new_title
                    changed.add("title")

                for dup in dups:
                    dup = Book.objects.select_for_update().get(pk=dup.pk)

                    # fill empty fields on the kept book
                    for field in FILL_FIELDS:
                        if _blank(getattr(keeper, field)) and not _blank(getattr(dup, field)):
                            value = getattr(dup, field)
                            if field == "asin":
                                value = norm_asin(value)
                            setattr(keeper, field, value)
                            changed.add(field)
                    if not keeper.image and dup.image:
                        keeper.image = dup.image.name  # reuse the file, don't delete it
                        changed.add("image")
                    elif dup.image and dup.image.name != keeper.image.name:
                        images_to_delete.append(dup.image.name)

                    self._move_awards(keeper, dup, stats)
                    self._move_user_books(keeper, dup, stats)
                    PendingAward.objects.filter(matched_book=dup).update(matched_book=keeper)

                    leftover = BookCategory.objects.filter(book=dup).count() + \
                        UserBook.objects.filter(book=dup).count()
                    if leftover:
                        raise RuntimeError(f"book {dup.id} still has {leftover} related rows")
                    dup.delete()

                if changed:
                    keeper.save(update_fields=sorted(changed))

                stats["images"] = 0 if keep_images else len(set(images_to_delete))
                if not apply:
                    raise DryRun()
                if not keep_images and images_to_delete:
                    names = set(images_to_delete)
                    transaction.on_commit(lambda: self._delete_images(names))
        except DryRun:
            pass
        return stats

    def _move_awards(self, keeper, dup, stats):
        for bc in BookCategory.objects.filter(book=dup).select_related("award_level"):
            existing = (BookCategory.objects.select_related("award_level")
                        .filter(book=keeper, category_id=bc.category_id, year=bc.year).first())
            if existing is None:
                bc.book = keeper
                bc.save(update_fields=["book"])
                stats["awards_moved"] += 1
                continue
            level = better_level(existing.award_level, bc.award_level)
            if level != existing.award_level:
                existing.award_level = level
                existing.save(update_fields=["award_level"])
            for ubc in UserBookCategory.objects.filter(book_category=bc):
                mine = UserBookCategory.objects.filter(user_id=ubc.user_id,
                                                       book_category=existing).first()
                if mine is None:
                    ubc.book_category = existing
                    ubc.save(update_fields=["book_category"])
                    stats["marks_moved"] += 1
                else:
                    if ubc.completed and not mine.completed:
                        mine.completed = True
                        mine.save(update_fields=["completed"])
                    ubc.delete()
                    stats["marks_combined"] += 1
            PendingAward.objects.filter(book_category=bc).update(book_category=existing)
            bc.delete()
            stats["awards_combined"] += 1

    def _move_user_books(self, keeper, dup, stats):
        for ub in UserBook.objects.filter(book=dup):
            mine = UserBook.objects.filter(user_id=ub.user_id, book=keeper).first()
            if mine is None:
                ub.book = keeper
                ub.save(update_fields=["book"])
                stats["marks_moved"] += 1
            else:
                if ub.completed and not mine.completed:
                    mine.completed = True
                    mine.save(update_fields=["completed"])
                ub.delete()
                stats["marks_combined"] += 1

    def _delete_images(self, names):
        storage = Book._meta.get_field("image").storage
        for name in names:
            if Book.objects.filter(image=name).exists():
                continue  # another book still uses this file
            try:
                storage.delete(name)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    could not delete image {name}: {e}"))
