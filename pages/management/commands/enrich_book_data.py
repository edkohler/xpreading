from django.core.management.base import BaseCommand
from django.db.models import Q
from pages.models import Book  # Replace with your actual app name
from pages.services import AmazonBookMatcher, BookDataEnricher  # Replace with your app name
from django.conf import settings
import time


class Command(BaseCommand):
    help = 'Enrich book data with information from Amazon'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of books to process (default: 50)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Delay between API calls in seconds (default: 1.0)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without making changes'
        )

    def handle(self, *args, **options):
        # Get API key from settings
        api_key = getattr(settings, 'ASINDATAAPI', None)
        if not api_key:
            self.stdout.write(
                self.style.ERROR('ASINDATAAPI setting is required')
            )
            return

        # Initialize services
        amazon_matcher = AmazonBookMatcher(api_key)
        enricher = BookDataEnricher(amazon_matcher)

        # Get books with missing fields
        books_query = Book.objects.filter(
            Q(asin__isnull=True) | Q(asin="") |
            Q(page_count__isnull=True) |
            Q(image__isnull=True) | Q(image="")
        ).select_related('author').order_by('-id')

        total_books = books_query.count()
        limit = options['limit']
        delay = options['delay']
        dry_run = options['dry_run']

        self.stdout.write(f"Found {total_books} books with missing data")
        self.stdout.write(f"Processing up to {limit} books...")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        processed = 0
        updated = 0

        for book in books_query[:limit]:
            processed += 1

            if dry_run:
                print(f"[{processed}/{limit}] Would process: '{book.title}' by {book.author}")
            else:
                print(f"[{processed}/{limit}] Processing: '{book.title}' by {book.author}")
                try:
                    if enricher.enrich_book(book):
                        updated += 1
                except Exception as e:
                    print(f"  Error processing book: {e}")

                # Rate limiting
                if delay > 0:
                    time.sleep(delay)

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Completed! Processed {processed} books, updated {updated}"
                )
            )
        else:
            self.stdout.write(f"Would process {processed} books")
