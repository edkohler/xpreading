# upload_utils.py
import csv
from django.core.cache import cache
from django.db import transaction
from django.utils.text import slugify

import unicodedata
import unidecode

# Import your models (adjust import path as needed)
from .models import (Author, AwardLevel, AwardYearLike, Book, BookCategory,
                     Category, Illustrator, Library, UserBook,
                     UserBookCategory, UserFavoriteLibrary)

def truncate_to_nearest_space(text, max_length=50):
    """Truncate text to the nearest space not exceeding max_length characters."""
    if len(text) <= max_length:
        return text

    # Find the last space before the max_length limit
    last_space_pos = text[:max_length+1].rfind(' ')

    # If no space found, just truncate at max_length
    if last_space_pos == -1:
        return text[:max_length]

    return text[:last_space_pos]


def normalize_text_advanced(text):
    """
    Advanced text normalization for better Unicode matching
    """
    if not text:
        return ""

    # Strip whitespace
    text = text.strip()

    # Normalize Unicode (NFD = decomposed form)
    text = unicodedata.normalize('NFD', text)

    # Remove diacritical marks (accents, etc.)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')

    # Convert to lowercase
    text = text.lower()

    return text

def normalize_text_transliterate(text):
    """
    Alternative normalization using transliteration to ASCII
    """
    if not text:
        return ""

    # Strip and convert to ASCII equivalents
    text = text.strip()
    text = unidecode.unidecode(text).lower()

    return text

def find_author_flexible(first_name, last_name):
    """
    Flexible author search using multiple normalization strategies
    """
    # Original values
    first_original = first_name.strip()
    last_original = last_name.strip()

    # Multiple normalization approaches
    first_normalized = normalize_text_advanced(first_original)
    last_normalized = normalize_text_advanced(last_original)

    first_transliterated = normalize_text_transliterate(first_original)
    last_transliterated = normalize_text_transliterate(last_original)

    # Try to find existing author using multiple strategies
    author = None

    # Strategy 1: Exact case-insensitive match
    try:
        author = Author.objects.get(
            first_name__iexact=first_original,
            last_name__iexact=last_original
        )
        return author, first_original, last_original
    except (Author.DoesNotExist, Author.MultipleObjectsReturned):
        pass

    # Strategy 2: Unicode normalized match
    try:
        # Search for authors where normalized names match
        candidates = Author.objects.all()
        for candidate in candidates:
            candidate_first_norm = normalize_text_advanced(candidate.first_name)
            candidate_last_norm = normalize_text_advanced(candidate.last_name)

            if (candidate_first_norm == first_normalized and
                candidate_last_norm == last_normalized):
                return candidate, first_original, last_original
    except:
        pass

    # Strategy 3: Transliterated ASCII match
    try:
        candidates = Author.objects.all()
        for candidate in candidates:
            candidate_first_trans = normalize_text_transliterate(candidate.first_name)
            candidate_last_trans = normalize_text_transliterate(candidate.last_name)

            if (candidate_first_trans == first_transliterated and
                candidate_last_trans == last_transliterated):
                return candidate, first_original, last_original
    except:
        pass

    # If no match found, return None to create new author
    return None, first_original, last_original


def find_illustrator_flexible(first_name, last_name):
    """
    Flexible illustrator search (same logic as author search)
    """
    # Original values
    first_original = first_name.strip()
    last_original = last_name.strip()

    # Multiple normalization approaches
    first_normalized = normalize_text_advanced(first_original)
    last_normalized = normalize_text_advanced(last_original)

    first_transliterated = normalize_text_transliterate(first_original)
    last_transliterated = normalize_text_transliterate(last_original)

    # Try to find existing illustrator using multiple strategies
    illustrator = None

    # Strategy 1: Exact case-insensitive match
    try:
        illustrator = Illustrator.objects.get(
            first_name__iexact=first_original,
            last_name__iexact=last_original
        )
        return illustrator, first_original, last_original
    except (Illustrator.DoesNotExist, Illustrator.MultipleObjectsReturned):
        pass

    # Strategy 2: Unicode normalized match
    try:
        candidates = Illustrator.objects.all()
        for candidate in candidates:
            candidate_first_norm = normalize_text_advanced(candidate.first_name)
            candidate_last_norm = normalize_text_advanced(candidate.last_name)

            if (candidate_first_norm == first_normalized and
                candidate_last_norm == last_normalized):
                return candidate, first_original, last_original
    except:
        pass

    # Strategy 3: Transliterated ASCII match
    try:
        candidates = Illustrator.objects.all()
        for candidate in candidates:
            candidate_first_trans = normalize_text_transliterate(candidate.first_name)
            candidate_last_trans = normalize_text_transliterate(candidate.last_name)

            if (candidate_first_trans == first_transliterated and
                candidate_last_trans == last_transliterated):
                return candidate, first_original, last_original
    except:
        pass

    return None, first_original, last_original


def validate_upload_file(csv_file):
    """Validate the upload file before processing"""
    try:
        decoded_file = csv_file.read().decode("utf-8-sig").splitlines()
        reader = csv.DictReader(decoded_file, delimiter="\t")

        required_fields = ['title', 'first_name', 'last_name', 'year', 'category', 'level']
        optional_fields = ['illustrator_first_name', 'illustrator_last_name']

        errors = []
        total_rows = 0

        # Check headers
        if not reader.fieldnames:
            return {'is_valid': False, 'errors': ['File appears to be empty or invalid format']}

        missing_headers = [field for field in required_fields if field not in reader.fieldnames]
        if missing_headers:
            errors.append(f"Missing required columns: {', '.join(missing_headers)}")

        # Validate data rows
        for row_num, row in enumerate(reader, 1):
            total_rows += 1
            row_errors = []

            # Check required fields
            for field in required_fields:
                if not row.get(field, '').strip():
                    row_errors.append(f"Row {row_num}: Missing required field '{field}'")

            # Validate year is numeric
            try:
                year_val = int(row.get('year', '').strip())
                if year_val < 1800 or year_val > 2030:
                    row_errors.append(f"Row {row_num}: Invalid year '{year_val}' (must be between 1800-2030)")
            except (ValueError, TypeError):
                row_errors.append(f"Row {row_num}: Year must be a valid number")

            # Validate category and level exist
            try:
                category_id = int(row.get('category', '').strip())
                if not Category.objects.filter(id=category_id).exists():
                    row_errors.append(f"Row {row_num}: Category ID {category_id} does not exist")
            except (ValueError, TypeError):
                row_errors.append(f"Row {row_num}: Category must be a valid number")

            try:
                level_id = int(row.get('level', '').strip())
                if not AwardLevel.objects.filter(id=level_id).exists():
                    row_errors.append(f"Row {row_num}: Award Level ID {level_id} does not exist")
            except (ValueError, TypeError):
                row_errors.append(f"Row {row_num}: Level must be a valid number")

            # Check illustrator fields consistency
            illustrator_first = row.get('illustrator_first_name', '').strip()
            illustrator_last = row.get('illustrator_last_name', '').strip()
            if bool(illustrator_first) != bool(illustrator_last):
                row_errors.append(f"Row {row_num}: Both illustrator first and last name must be provided together or both left empty")

            if row_errors:
                errors.extend(row_errors)

            # Limit error reporting for very large files
            if len(errors) > 50:
                errors.append(f"... and more errors found. Showing first 50 errors only.")
                break

        if total_rows == 0:
            errors.append("File contains no data rows")

        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'total_rows': total_rows
        }

    except Exception as e:
        return {
            'is_valid': False,
            'errors': [f"Error reading file: {str(e)}"],
            'total_rows': 0
        }


def cache_existing_books():
    """Cache existing books to reduce database queries"""
    cache_key = 'existing_books'
    cached_data = cache.get(cache_key)
    if cached_data is None:
        books = Book.objects.select_related('author', 'illustrator').all()
        cached_data = {}
        for book in books:
            # Create multiple lookup keys for flexible matching
            title_normalized = normalize_text_advanced(book.title)
            cached_data[book.title.lower()] = book
            cached_data[title_normalized] = book
        cache.set(cache_key, cached_data, 3600)  # Cache for 1 hour
    return cached_data


def cache_existing_authors():
    """Cache existing authors to reduce database queries"""
    cache_key = 'existing_authors'
    cached_data = cache.get(cache_key)
    if cached_data is None:
        authors = Author.objects.all()
        cached_data = {}
        for author in authors:
            key = f"{author.first_name.lower()}|{author.last_name.lower()}"
            cached_data[key] = author
        cache.set(cache_key, cached_data, 3600)
    return cached_data


def cache_existing_illustrators():
    """Cache existing illustrators to reduce database queries"""
    cache_key = 'existing_illustrators'
    cached_data = cache.get(cache_key)
    if cached_data is None:
        illustrators = Illustrator.objects.all()
        cached_data = {}
        for illustrator in illustrators:
            key = f"{illustrator.first_name.lower()}|{illustrator.last_name.lower()}"
            cached_data[key] = illustrator
        cache.set(cache_key, cached_data, 3600)
    return cached_data


def find_author_in_cache(first_name, last_name, cache_data):
    """Find author using cached data"""
    key = f"{first_name.lower()}|{last_name.lower()}"
    return cache_data.get(key)


def find_illustrator_in_cache(first_name, last_name, cache_data):
    """Find illustrator using cached data"""
    key = f"{first_name.lower()}|{last_name.lower()}"
    return cache_data.get(key)


def find_book_in_cache(title, cache_data):
    """Find book using cached data"""
    # Try exact match first
    book = cache_data.get(title.lower())
    if book:
        return book

    # Try normalized match
    title_normalized = normalize_text_advanced(title)
    return cache_data.get(title_normalized)


def process_batch(batch, books_cache, authors_cache, illustrators_cache, categories_cache, award_levels_cache):
    """Process a batch of rows efficiently"""
    success_count = 0
    error_count = 0

    try:
        with transaction.atomic():
            # Step 1: Create all unique authors first
            unique_authors = set()
            for row_num, row in batch:
                if row["first_name"].strip() and row["last_name"].strip():
                    first_name = row["first_name"].strip()
                    last_name = row["last_name"].strip()
                    author_key = f"{first_name.lower()}|{last_name.lower()}"

                    if (not find_author_in_cache(first_name, last_name, authors_cache) and
                        author_key not in unique_authors):
                        unique_authors.add(author_key)
                        # Create author immediately to get database ID
                        author, created = Author.objects.get_or_create(
                            first_name__iexact=first_name,
                            last_name__iexact=last_name,
                            defaults={'first_name': first_name, 'last_name': last_name}
                        )
                        # Add to cache
                        authors_cache[author_key] = author

            # Step 2: Create all unique illustrators
            unique_illustrators = set()
            for row_num, row in batch:
                if (row.get("illustrator_first_name", "").strip() and
                    row.get("illustrator_last_name", "").strip()):
                    first_name = row["illustrator_first_name"].strip()
                    last_name = row["illustrator_last_name"].strip()
                    illustrator_key = f"{first_name.lower()}|{last_name.lower()}"

                    if (not find_illustrator_in_cache(first_name, last_name, illustrators_cache) and
                        illustrator_key not in unique_illustrators):
                        unique_illustrators.add(illustrator_key)
                        # Create illustrator immediately to get database ID
                        illustrator, created = Illustrator.objects.get_or_create(
                            first_name__iexact=first_name,
                            last_name__iexact=last_name,
                            defaults={'first_name': first_name, 'last_name': last_name}
                        )
                        # Add to cache
                        illustrators_cache[illustrator_key] = illustrator

            # Step 3: Process each row for books and book categories
            processed_books = set()

            for row_num, row in batch:
                try:
                    # Get author
                    author = None
                    if row["first_name"].strip() and row["last_name"].strip():
                        first_name = row["first_name"].strip()
                        last_name = row["last_name"].strip()
                        author = find_author_in_cache(first_name, last_name, authors_cache)

                    # Get illustrator
                    illustrator = None
                    if (row.get("illustrator_first_name", "").strip() and
                        row.get("illustrator_last_name", "").strip()):
                        first_name = row["illustrator_first_name"].strip()
                        last_name = row["illustrator_last_name"].strip()
                        illustrator = find_illustrator_in_cache(first_name, last_name, illustrators_cache)

                    # Process Book
                    title_original = row["title"].strip()
                    book = find_book_in_cache(title_original, books_cache)

                    if book:
                        # Update existing book if needed
                        updated = False
                        if author and not book.author:
                            book.author = author
                            updated = True
                        if illustrator and not book.illustrator:
                            book.illustrator = illustrator
                            updated = True
                        if updated:
                            book.save()
                    else:
                        # Check if we already processed this book in this batch
                        book_key = title_original.lower()
                        if book_key not in processed_books:
                            # Create new book
                            title_normalized = normalize_text_advanced(title_original)
                            title_normalized = truncate_to_nearest_space(title_normalized, 50)
                            base_slug = slugify(title_normalized, allow_unicode=True)

                            # Handle slug uniqueness
                            slug = base_slug
                            counter = 1
                            while Book.objects.filter(slug=slug).exists():
                                slug = f"{base_slug}-{counter}"
                                counter += 1

                            # Create book with get_or_create to handle race conditions
                            book, created = Book.objects.get_or_create(
                                title=title_original,
                                defaults={
                                    'slug': slug,
                                    'author': author,
                                    'illustrator': illustrator,
                                }
                            )

                            # If book already existed but didn't have author/illustrator, update it
                            if not created:
                                updated = False
                                if author and not book.author:
                                    book.author = author
                                    updated = True
                                if illustrator and not book.illustrator:
                                    book.illustrator = illustrator
                                    updated = True
                                if updated:
                                    book.save()

                            # Add to cache
                            books_cache[title_original.lower()] = book
                            processed_books.add(book_key)

                    # Get category and award level
                    try:
                        category = categories_cache.get(int(row["category"]))
                        award_level = award_levels_cache.get(int(row["level"]))
                    except (ValueError, TypeError):
                        print(f"Invalid category or level in row {row_num}")
                        error_count += 1
                        continue

                    if not category or not award_level:
                        print(f"Category or award level not found for row {row_num}")
                        error_count += 1
                        continue

                    # Create or update BookCategory
                    try:
                        book_category, created = BookCategory.objects.update_or_create(
                            book=book,
                            category=category,
                            year=int(row["year"]),
                            defaults={"award_level": award_level},
                        )
                        success_count += 1
                    except Exception as e:
                        print(f"Error creating BookCategory for row {row_num}: {str(e)}")
                        error_count += 1

                except Exception as e:
                    print(f"Error processing row {row_num}: {str(e)}")
                    error_count += 1

    except Exception as e:
        print(f"Batch processing error: {str(e)}")
        import traceback
        traceback.print_exc()
        # If batch fails, count all as errors
        error_count = len(batch)
        success_count = 0

    return success_count, error_count
