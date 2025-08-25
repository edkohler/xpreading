import json
import re
import requests
import time
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from pages.models import Book  # Replace with your actual app name


class AmazonBookMatcher:
    """Class to handle Amazon book searching and matching logic"""

    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.asindataapi.com/request"

    def search_book(self, title, author_name):
        """Search for a book on Amazon and return results"""
        params = {
            "api_key": self.api_key,
            "type": "search",
            "amazon_domain": "amazon.com",
            "search_term": f"{title} {author_name}",
            "exclude_sponsored": "true",
            "max_page": "1",
            "output": "json",
            "include_html": "false",
            "category_id": "283155",  # Books category
            "page": "1",
        }

        try:
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error searching for '{title}' by {author_name}: {e}")
            return None

    def find_exact_match(self, search_results, target_title, target_author):
        """Find exact matches for title and author in search results"""
        if not search_results or 'search_results' not in search_results:
            return None

        # Normalize strings for comparison
        target_title_normalized = self._normalize_title(target_title)
        target_author_normalized = self._normalize_name(target_author)

        for result in search_results['search_results']:
            result_title_normalized = self._normalize_title(result.get('title', ''))

            # Check for title match
            if target_title_normalized in result_title_normalized or result_title_normalized in target_title_normalized:
                # Look for paperback or hardcover versions
                paperback_asin = self._find_format_asin(result, 'paperback')
                hardcover_asin = self._find_format_asin(result, 'hardcover')

                if paperback_asin or hardcover_asin:
                    return {
                        'asin': paperback_asin or hardcover_asin,  # Prefer paperback
                        'title': result.get('title'),
                        'image_url': result.get('image'),
                        'rating': result.get('rating'),
                        'format': 'paperback' if paperback_asin else 'hardcover'
                    }

        return None

    def _normalize_title(self, title):
        """Normalize title for comparison"""
        return re.sub(r'[^\w\s]', '', title.lower()).strip()

    def _normalize_name(self, name):
        """Normalize author name for comparison"""
        return re.sub(r'[^\w\s]', '', str(name).lower()).strip()

    def _find_format_asin(self, result, format_type):
        """Find ASIN for specific format (paperback/hardcover)"""
        # Check main result
        if format_type.lower() in result.get('price', {}).get('name', '').lower():
            return result.get('asin')

        # Check other formats
        for fmt in result.get('other_formats', []):
            if format_type.lower() in fmt.get('title', '').lower():
                return fmt.get('asin')

        # Check prices array
        for price in result.get('prices', []):
            if format_type.lower() in price.get('name', '').lower():
                return price.get('asin')

        return None

    def get_product_details(self, asin):
        """Get detailed product information for a specific ASIN"""
        params = {
            'api_key': self.api_key,
            'amazon_domain': 'amazon.com',
            'asin': asin,
            'type': 'product'
        }

        try:
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error getting product details for ASIN {asin}: {e}")
            return None


class BookDataEnricher:
    """Class to handle updating book records with Amazon data"""

    def __init__(self, amazon_matcher):
        self.amazon_matcher = amazon_matcher

    def enrich_book(self, book):
        """Enrich a single book with Amazon data"""
        print(f"Processing: '{book.title}' by {book.author}")

        # Search for the book on Amazon
        search_results = self.amazon_matcher.search_book(book.title, str(book.author))
        if not search_results:
            print(f"  No search results found")
            return False

        # Find exact match
        match = self.amazon_matcher.find_exact_match(
            search_results, book.title, str(book.author)
        )

        if not match:
            print(f"  No exact match found")
            return False

        print(f"  Found match: ASIN {match['asin']}")
        updated_fields = []

        # Update ASIN if missing
        if not book.asin and match['asin']:
            book.asin = match['asin']
            updated_fields.append('ASIN')

        # Download and save image if missing
        if not book.image and match.get('image_url'):
            if self._download_image(book, match['image_url']):
                updated_fields.append('image')

        # Get page count if missing
        if not book.page_count and book.asin:
            page_count = self._get_page_count(book.asin)
            if page_count:
                book.page_count = page_count
                updated_fields.append('page_count')

        if updated_fields:
            book.save()
            print(f"  Updated: {', '.join(updated_fields)}")
            return True
        else:
            print(f"  No fields updated")
            return False

    def _download_image(self, book, image_url):
        """Download and save book cover image"""
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()

            image_name = f"{book.pk}_cover.jpg"
            book.image.save(
                image_name,
                ContentFile(response.content),
                save=False  # Don't save the model yet
            )
            print(f"    Downloaded image")
            return True
        except Exception as e:
            print(f"    Failed to download image: {e}")
            return False

    def _get_page_count(self, asin):
        """Get page count for a book using its ASIN"""
        product_data = self.amazon_matcher.get_product_details(asin)
        if not product_data:
            return None

        return self._extract_page_count(product_data, asin)

    def _extract_page_count(self, amazon_product_json, asin):
        """Extract the page count from Amazon product data"""
        try:
            # Convert to dictionary if input is a string
            if isinstance(amazon_product_json, str):
                data = json.loads(amazon_product_json)
            else:
                data = amazon_product_json

            # Access the specifications_flat field
            specs_flat = data.get('product', {}).get('specifications_flat', '')

            # Use regex to find the page count
            match = re.search(r'(\d+)\s+pages', specs_flat)
            if match:
                page_count = int(match.group(1))
                print(f"    Found page count: {page_count}")
                return page_count

            # Fallback: look in the specifications list
            specifications = data.get('product', {}).get('specifications', [])
            for spec in specifications:
                if 'Hardcover' in spec.get('name', '') or 'Paperback' in spec.get('name', ''):
                    match = re.search(r'(\d+)\s+pages', spec.get('value', ''))
                    if match:
                        page_count = int(match.group(1))
                        print(f"    Found page count: {page_count}")
                        return page_count

            print(f"    No page count found")
            return None

        except Exception as e:
            print(f"    Error extracting page count: {e}")
            return None
