"""Check each category's Wikipedia page for new award entries.

Daily usage (cheap - only changed pages are read):
    python manage.py sync_wikipedia_awards

Useful flags:
    --dry-run                 print what would be proposed, write nothing
    --page Newbery_Medal      only this page (repeatable)
    --category 235            only this category id (repeatable)
    --force                   re-read pages even if unchanged since last run
    --since-year 2020         look further back than the default
                              (default: newest year we have for the page, minus one)

New findings are saved as PendingAward rows; review them in the admin
(Pages > Pending awards) and use the "Approve" action.
"""

import os

from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from pages.models import PendingAward
from pages.wiki_sync.service import run_sync


class Command(BaseCommand):
    help = "Check Wikipedia award pages for new books and queue them for review"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--page", action="append", dest="pages")
        parser.add_argument("--category", action="append", type=int, dest="categories")
        parser.add_argument("--since-year", type=int)
        parser.add_argument(
            "--model", help="OpenAI model (default: WIKI_SYNC_MODEL or gpt-5-mini)"
        )
        parser.add_argument("--no-email", action="store_true")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing will be saved"))
        results = run_sync(
            force=opts["force"],
            dry_run=dry,
            only_pages=opts["pages"],
            category_ids=opts["categories"],
            since_year=opts["since_year"],
            model=opts["model"],
            stdout=self.stdout,
        )

        unchanged = [r for r in results if r.status == "unchanged"]
        processed = [r for r in results if r.status == "processed"]
        errors = [r for r in results if r.status == "error"]
        tokens = sum((r.usage or {}).get("total_tokens", 0) for r in processed)

        lines = []
        for r in processed:
            lines.append(
                f"{r.title}: {r.created} new, {r.already_listed} already listed"
                + (
                    f", {r.previously_reviewed} previously reviewed"
                    if r.previously_reviewed
                    else ""
                )
                + (f", {r.dropped} dropped" if r.dropped else "")
            )
        for r in errors:
            lines.append(f"ERROR {r.title}: {r.message}")
        summary = (
            f"Pages: {len(results)} checked, {len(unchanged)} unchanged, "
            f"{len(processed)} read, {len(errors)} errors. "
            f"New proposals: {sum(r.created for r in processed)}. Tokens: {tokens:,}."
        )
        for line in lines:
            self.stdout.write("  " + line)
        style = self.style.ERROR if errors else self.style.SUCCESS
        self.stdout.write(style(summary))

        if dry or opts["no_email"]:
            return
        new_total = sum(r.created for r in processed)
        recipient = os.getenv("WIKI_SYNC_NOTIFY_EMAIL")
        if recipient and (new_total or errors):
            pending = PendingAward.objects.filter(
                status=PendingAward.STATUS_PENDING
            ).count()
            site = os.getenv("SITEMAP_DOMAIN", "xpreading.com")
            body = "\n".join(
                [summary, ""]
                + lines
                + [
                    "",
                    f"{pending} proposals waiting for review:",
                    f"https://{site}/admin/pages/pendingaward/?status__exact=pending",
                ]
            )
            try:
                send_mail(
                    f"xpreading: {new_total} new award entries from Wikipedia",
                    body,
                    None,
                    [recipient],
                )
            except Exception as e:  # email is best-effort
                self.stdout.write(self.style.WARNING(f"Email not sent: {e}"))
