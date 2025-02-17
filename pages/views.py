from django.views.generic import TemplateView
from django.shortcuts import render, get_object_or_404, Http404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Category, UserBookCategory, BookCategory, Book, Library, UserBook, UserFavoriteLibrary, AwardYearLike, AwardLevel, Author, Illustrator
import uuid
from django.utils.timezone import now, timedelta
from django.core.mail import send_mail
from collections import defaultdict
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.db.models import Count, Sum
from django.contrib.auth.mixins import LoginRequiredMixin
import json
import requests
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from .forms import BookCategoryForm
from django.template.loader import render_to_string

import os
from bs4 import BeautifulSoup
from django.urls import path
import csv
from django.contrib import messages

from django.core.paginator import Paginator
from django.conf import settings


class HomePageView(TemplateView):
    template_name = "pages/home.html"


class AboutPageView(TemplateView):
    template_name = "pages/about.html"

@login_required
def profile_view(request):
    return render(request, "account/profile.html", {"user": request.user})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    books = BookCategory.objects.filter(category=category).select_related('book', 'award_level').order_by('-year')

    # Get the UserBook objects for the current user
    user_completed_books = set()
    if request.user.is_authenticated:
        user_completed_books = set(
            UserBook.objects.filter(
                user=request.user,
                completed=True
            ).values_list('book_id', flat=True)
        )

    books_by_year = defaultdict(list)
    for book_category in books:
        if book_category.id and book_category.book:
            books_by_year[book_category.year].append({
                'book_category': book_category,
                'completed': book_category.book.id in user_completed_books,
            })

    context = {
        'category': category,
        'books_by_year': dict(books_by_year),
    }
    return render(request, 'pages/category_detail.html', context)



@login_required
def mark_book_read(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    UserBook.objects.get_or_create(user=request.user, book=book, defaults={'completed': True})

    # Also mark the UserBookCategory as completed if it exists
    book_categories = BookCategory.objects.filter(book=book)
    for book_category in book_categories:
        UserBookCategory.objects.get_or_create(
            user=request.user,
            book_category=book_category,
            defaults={'completed': True}
        )

    html = render_to_string(
        'pages/partials/book_read_button.html',
        {'book': book, 'completed': True, 'user': request.user},
        request=request,
    )
    return HttpResponse(html)

@login_required
def mark_book_unread(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    UserBook.objects.filter(user=request.user, book=book).delete()

    # Also mark the UserBookCategory as not completed
    book_categories = BookCategory.objects.filter(book=book)
    UserBookCategory.objects.filter(
        user=request.user,
        book_category__in=book_categories
    ).update(completed=False)

    html = render_to_string(
        'pages/partials/book_read_button.html',
        {'book': book, 'completed': False, 'user': request.user},
        request=request,
    )
    return HttpResponse(html)


def category_list_sorted_by_year(request):
    # Fetch all categories with their associated BookCategory objects
    categories = (
        Category.objects.all()
        .prefetch_related(
            'bookcategory_set__book',
            'bookcategory_set__award_level'
        )
    )

    # Organize categories by year in descending order
    sorted_categories = {}
    for category in categories:
        book_categories = category.bookcategory_set.all().order_by('-year')
        sorted_categories[category] = book_categories

    context = {'sorted_categories': sorted_categories}
    return render(request, 'pages/homepage.html', context)


def book_detail(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug)
    categories = BookCategory.objects.filter(book=book).select_related('category', 'award_level')
    user_book_categories = UserBookCategory.objects.filter(user=request.user, book_category__in=categories).values_list('book_category_id', flat=True) if request.user.is_authenticated else []
    libraries = Library.objects.all()

    # Precompute completed status for the first category
    first_category = categories[0] if categories else None
    first_category_completed = first_category.id in user_book_categories if first_category else False

    favorite_libraries = []
    other_libraries = []

    if request.user.is_authenticated:
        favorite_library_ids = UserFavoriteLibrary.objects.filter(
            user=request.user
        ).values_list('library_id', flat=True)

        favorite_libraries = Library.objects.filter(id__in=favorite_library_ids)
        other_libraries = Library.objects.exclude(id__in=favorite_library_ids)

        # Retrieve the UserBook for this user and book, if it exists
        user_book = UserBook.objects.filter(user=request.user, book=book).first()
    else:
        other_libraries = Library.objects.all()
        user_book = None

    context = {
        'book': book,
        'categories': categories,
        'user_book_categories': user_book_categories,
        'first_category': first_category,
        'first_category_completed': first_category_completed,
        'libraries': libraries,
        'favorite_libraries': favorite_libraries,
        'user_book': user_book,
    }
    return render(request, 'pages/book_detail.html', context)


@login_required
def toggle_read_status(request, book_category_id):
    book_category = get_object_or_404(BookCategory, id=book_category_id)
    data = json.loads(request.body)
    completed = data.get('completed', False)

    # Update or create both UserBook and UserBookCategory
    user_book, _ = UserBook.objects.get_or_create(
        user=request.user,
        book=book_category.book,
        defaults={'completed': completed}
    )
    user_book.completed = completed
    user_book.save()

    user_book_category, _ = UserBookCategory.objects.get_or_create(
        user=request.user,
        book_category=book_category,
        defaults={'completed': completed}
    )
    user_book_category.completed = completed
    user_book_category.save()

    return JsonResponse({'completed': completed})

@login_required
def toggle_read_status_htmx(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    user_book, created = UserBook.objects.get_or_create(user=request.user, book=book)
    user_book.completed = not user_book.completed
    user_book.save()

    context = {
        'book': book,
        'completed': user_book.completed,
    }
    print("Rendering response with completed =", context['completed'])

    return render(request, 'pages/partials/book_read_button.html', context)



class BooksByCategoryView(LoginRequiredMixin, TemplateView):
    template_name = "pages/user_books_by_category.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Get completed books directly from UserBook
        user_completed_books = set(
            UserBook.objects.filter(
                user=user,
                completed=True
            ).values_list('book_id', flat=True)
        )
        # Filter categories based on AwardYearLike for the user
        liked_awards = AwardYearLike.objects.filter(user=user)
        categories = Category.objects.filter(
            id__in=liked_awards.values_list('category_id', flat=True)
        ).order_by('name')

        books_by_category = {}
        for category in categories:
            books_by_year = {}

            # Filter BookCategory to only include years liked by the user
            liked_years = liked_awards.filter(category=category).values_list('year', flat=True)
            book_categories = BookCategory.objects.filter(
                category=category,
                year__in=liked_years
            ).select_related('book', 'book__author', 'award_level').order_by('-year', 'book__title')

            # Group by year
            for book_category in book_categories:
                year = book_category.year
                if year not in books_by_year:
                    books_by_year[year] = {
                        'total_books': 0,
                        'read_books': 0,
                        'book_list': []
                    }

                books_by_year[year]['total_books'] += 1
                if book_category.book.id in user_completed_books:
                    books_by_year[year]['read_books'] += 1
                books_by_year[year]['book_list'].append(book_category)

            if books_by_year:
                books_by_category[category] = books_by_year

        context['books_by_category'] = books_by_category
        context['user_completed_books'] = user_completed_books
        return context



def library_list(request):
    user = request.user if request.user.is_authenticated else None

    favorite_library_ids = (
        UserFavoriteLibrary.objects.filter(user=user).values_list('library_id', flat=True)
        if user else []
    )
    favorite_libraries = Library.objects.filter(id__in=favorite_library_ids)
    non_favorite_libraries = Library.objects.exclude(id__in=favorite_library_ids)

    context = {
        'favorite_libraries': favorite_libraries,
        'non_favorite_libraries': non_favorite_libraries,
    }
    return render(request, 'pages/library_list.html', context)

@login_required
def add_favorite_library(request, library_id):
    library = get_object_or_404(Library, id=library_id)
    UserFavoriteLibrary.objects.get_or_create(user=request.user, library=library)
    html = render_to_string(
        'pages/partials/button_library_favorite.html',
        {'library': library, 'is_favorite': True, 'user': request.user},
        request=request,
    )
    return HttpResponse(html)


@login_required
def remove_favorite_library(request, library_id):
    library = get_object_or_404(Library, id=library_id)
    UserFavoriteLibrary.objects.filter(user=request.user, library=library).delete()
    html = render_to_string(
        'pages/partials/button_library_favorite.html',
        {'library': library, 'is_favorite': False, 'user': request.user},
        request=request,
    )
    return HttpResponse(html)



@login_required
def toggle_favorite_library(request, library_id):
    if request.method == "POST":
        user = request.user
        library = get_object_or_404(Library, id=library_id)
        favorite, created = UserFavoriteLibrary.objects.get_or_create(user=user, library=library)

        if not created:
            favorite.delete()

        # Render the button template and pass the library and favorite status
        button_html = render_to_string(
            'pages/partials/button_library_favorite.html',
            {'library': library, 'is_favorite': created, 'csrf_token': request.COOKIES.get('csrftoken')},
            request=request
        )
        return HttpResponse(button_html)  # Return the updated button HTML

    return JsonResponse({'error': 'Invalid request'}, status=400)


def terms_and_conditions(request):
    return render(request, 'pages/terms_and_conditions.html')

def privacy_policy(request):
    return render(request, 'pages/privacy_policy.html')


def award_year_list(request):
    # Retrieve distinct category-year combinations
    award_years = (
        BookCategory.objects.values(
            'category',
            'category__name',
            'category__slug',
            'category__id',
            'year'
        )
        .distinct()
        .order_by('category__name', '-year')  # Sort by category name first, then by year descending
    )

    liked_award_set = set()
    if request.user.is_authenticated:
        liked_awards = AwardYearLike.objects.filter(user=request.user).values_list('category_id', 'year')
        liked_award_set = {(like[0], like[1]) for like in liked_awards}

    # Group awards by category name, also store the category slug
    grouped_awards = defaultdict(list)
    category_slugs = {}  # Dictionary to store category slugs

    for award in award_years:
        award['liked'] = (award['category__id'], award['year']) in liked_award_set
        grouped_awards[award['category__name']].append(award)
        category_slugs[award['category__name']] = award['category__slug']  # Store slug for each category

    context = {
        'grouped_awards': dict(grouped_awards),  # Convert defaultdict to a normal dictionary
        'category_slugs': category_slugs,  # Pass slugs to template
    }
    return render(request, 'pages/award_year_list.html', context)


@login_required
def add_award_like(request, category_id, year):
    # Change this line to get the Category instead of BookCategory
    category = get_object_or_404(Category, id=category_id)
    # Create the like
    AwardYearLike.objects.get_or_create(user=request.user, category=category, year=year)
    # Render the updated button
    html = render_to_string(
        'pages/partials/award_like_button.html',
        {'award': {'category': category.id, 'year': year, 'liked': True}, 'is_liked': True, 'user': request.user},
        request=request,
    )
    return HttpResponse(html)


@login_required
def remove_award_like(request, category_id, year):
    category = get_object_or_404(Category, id=category_id)
    # Ensure the record is deleted from the database
    AwardYearLike.objects.filter(user=request.user, category=category, year=year).delete()
    # Render the updated button
    html = render_to_string(
        'pages/partials/award_like_button.html',
        {'award': {'category': category.id, 'year': year, 'liked': False}, 'is_liked': False, 'user': request.user},
        request=request,
    )
    return HttpResponse(html)


@login_required
def toggle_award_year_like(request, category_id, year):
    if request.method == "POST":
        user = request.user
        like, created = AwardYearLike.objects.get_or_create(
            user=user,
            category_id=category_id,
            year=year
        )

        if not created:
            # If it wasn't created, it existed, so delete it
            like.delete()
            is_liked = False
        else:
            is_liked = True

        # Render just the button template
        button_html = render_to_string(
            'pages/partials/award_like_button.html',
            {
                'award': {
                    'category': category_id,
                    'year': year
                },
                'is_liked': is_liked,
                'csrf_token': request.COOKIES.get('csrftoken')
            },
            request=request
        )
        return HttpResponse(button_html)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def my_award_lists(request):
    liked_awards = AwardYearLike.objects.filter(user=request.user)
    liked_award_data = []

    for like in liked_awards:
        books = BookCategory.objects.filter(category=like.category, year=like.year)
        user_books = UserBookCategory.objects.filter(user=request.user, book_category__in=books)

        completed_books = user_books.filter(completed=True).select_related('book_category__book')
        not_completed_books = books.exclude(id__in=completed_books.values_list('book_category', flat=True))

        liked_award_data.append({
            'category': like.category,
            'year': like.year,
            'completed_books': completed_books,
            'not_completed_books': not_completed_books,
        })

    context = {'liked_awards': liked_award_data}
    return render(request, 'pages/my_award_lists.html', context)


@login_required
def my_to_read_list(request):
    liked_awards = AwardYearLike.objects.filter(user=request.user)
    print("Liked awards:", liked_awards)
    to_read_books = []

    # Fetch IDs of books marked as completed for the user
    user_completed_books = UserBook.objects.filter(user=request.user, completed=True).values_list('book_id', flat=True)

    user = request.user
    favorite_library_ids = UserFavoriteLibrary.objects.filter(user=user).values_list('library_id', flat=True)
    favorite_libraries = Library.objects.filter(id__in=favorite_library_ids)
    non_favorite_libraries = Library.objects.exclude(id__in=favorite_library_ids)



    # Debugging
    print("Completed book IDs:", list(user_completed_books))

    for like in liked_awards:
        # Get all BookCategory entries for the liked category and year
        books = BookCategory.objects.filter(category=like.category, year=like.year)

        # Exclude completed books
        unread_books = books.exclude(book_id__in=user_completed_books)
        to_read_books.extend(unread_books)
        to_read_books

    to_read_books = sorted(to_read_books, key=lambda book: book.book.author.last_name.lower() if book.book.author else "")

    context = {'to_read_books': to_read_books,
               'favorite_libraries': favorite_libraries,
        'non_favorite_libraries': non_favorite_libraries,}
    return render(request, 'pages/my_to_read_list.html', context)


def get_unique_books_per_branch(request, library_id):
    # Get the list of book bibliocommons IDs from the query string
    book_ids = request.GET.get("books", "").split(",")
    base_url = f"https://gateway.bibliocommons.com/v2/libraries/{library_id}/bibs/"
    url_suffix = "/availability?locale=en-US"

    # Initialize branch data
    branch_unique_books = defaultdict(set)
    book_additional_data = {}

    # Process each query
    for book_id in book_ids:
        url = f"{base_url}{book_id}{url_suffix}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            # Iterate over bibItems to filter and collect data
            for item_id, item_data in data.get("entities", {}).get("bibItems", {}).items():
                availability = item_data.get("availability", {})
                if availability.get("statusType") == "AVAILABLE":
                    branch_name = item_data.get("branchName", "Unknown")
                    branch_unique_books[branch_name].add(book_id)

                    # Store additional data for the book
                    book_additional_data[book_id] = {
                        "collection": item_data.get("collection", "Unknown Collection"),
                        "callNumber": item_data.get("callNumber", "Unknown Call Number"),
                    }

        except Exception as e:
            print(f"Error fetching data from {url}: {e}")

    # Fetch book details from the database
    books = {
        book.bibliocommons_id: {
            "title": book.title,
            "author_first_name": book.author.first_name,
            "author_last_name": book.author.last_name,
            "slug": book.slug,
            "image": book.image if book.image else None,
        }
        for book in Book.objects.filter(bibliocommons_id__in=book_ids)
    }

    # Convert branch data to a sorted list
    results = sorted(
        [
            {
                "branchName": branch,
                "uniqueBooksCount": len(book_set),
                "bookDetails": sorted(
                    [
                        {
                            "bibliocommons_id": bibliocommons_id,
                            "title": books.get(bibliocommons_id, {}).get("title", "Unknown Title"),
                            "author_first_name": books.get(bibliocommons_id, {}).get("author_first_name", ""),
                            "author_last_name": books.get(bibliocommons_id, {}).get("author_last_name", ""),
                            "slug": books.get(bibliocommons_id, {}).get("slug", "#"),
                            "image": books.get(bibliocommons_id, {}).get("image", ""),
                            "collection": book_additional_data.get(bibliocommons_id, {}).get("collection", ""),
                            "callNumber": book_additional_data.get(bibliocommons_id, {}).get("callNumber", ""),
                        }
                        for bibliocommons_id in book_set
                    ],
                    key=lambda x: x["author_last_name"]  # Sort by author's last name
                )
            }
            for branch, book_set in branch_unique_books.items()
        ],
        key=lambda x: x["uniqueBooksCount"],
        reverse=True
    )

    return render(request, "pages/library_locations.html", {"library_data": results})

@staff_member_required
def incomplete_books_view(request):
    books = Book.objects.filter(
        Q(asin__isnull=True) | Q(asin='') |
        Q(bibliocommons_id__isnull=True) | Q(bibliocommons_id='') |
        Q(page_count__isnull=True)
    )

    return render(request, 'pages/incomplete_books.html', {'books': books})

@staff_member_required
def update_book_field(request, pk, field_name):
    if request.method == "POST":
        book = get_object_or_404(Book, pk=pk)
        new_value = request.POST.get('value')
        if hasattr(book, field_name):
            setattr(book, field_name, new_value)
            book.save()
            return JsonResponse({"success": True, "value": new_value})
    return JsonResponse({"success": False}, status=400)


@staff_member_required
def update_book_field(request, pk, field_name):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "GET" and hasattr(book, field_name):
        return render(request, 'pages/partials/edit_field.html', {
            'book': book,
            'field_name': field_name,
            'current_value': getattr(book, field_name),
        })
    elif request.method == "POST" and hasattr(book, field_name):
        new_value = request.POST.get('value')
        setattr(book, field_name, new_value)
        book.save()
        return JsonResponse({"success": True, "value": new_value})
    return JsonResponse({"success": False}, status=400)


@user_passes_test(lambda u: u.is_superuser)
def books_without_images(request):
    books = Book.objects.filter(Q(image__isnull=True) | Q(image=""))
    return render(request, "pages/books_without_images.html", {"books": books})

@user_passes_test(lambda u: u.is_superuser)
def upload_book_image(request, pk):
    if request.method == "POST" and request.FILES.get("image"):
        book = get_object_or_404(Book, pk=pk)
        book.image = request.FILES["image"]
        book.save()
        return JsonResponse({
            "message": "Image uploaded successfully",
            "image_url": book.image.url,
        })
    return JsonResponse({"error": "Invalid request"}, status=400)




# Helper function to download and save images
def download_image(url, book):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        # Generate a unique filename
        ext = os.path.splitext(url.split("?")[0])[1]  # Extract extension from URL
        filename = f"{uuid.uuid4()}{ext}"
        filepath = f"book_images/{filename}"

        # Save the image to the media directory
        full_path = os.path.join("media", filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)

        # Update the book's image field
        book.image = filepath
        book.save()

# View to scrape and update images
def scrape_book_images(request):
    books = Book.objects.filter(image__exact='', bibliocommons_id__isnull=False)
    print(books)
    results = []

    for book in books:
        url = f"https://hclib.bibliocommons.com/v2/record/{book.bibliocommons_id}"
        print(url)
        response = requests.get(url)
        print(response)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            img_tag = soup.find('div', class_='cp-bib-jacket').find('img')
            print(img_tag)
            if img_tag:
                img_url = img_tag.get('src')
                download_image(img_url, book)
                results.append({
                    'title': book.title,
                    'image_url': img_url,
                    'status': 'Updated'
                })
            else:
                results.append({
                    'title': book.title,
                    'status': 'Image not found'
                })
        else:
            results.append({
                'title': book.title,
                'status': f'Failed to fetch page (Status code: {response.status_code})'
            })

    return JsonResponse({'results': results})

# Template for triggering the scrape process
def scrape_view(request):
    return render(request, 'pages/scrape_books.html')


@login_required
def xp_report(request):
    user = request.user
    NEAR_COMPLETION_THRESHOLD = 0.3  # 30%
    # Count the number of completed books
    completed_books_count = UserBook.objects.filter(user=user, completed=True).count()
    # Sum the page counts of completed books
    completed_books_pages = (
        UserBook.objects.filter(user=user, completed=True)
        .select_related('book')
        .aggregate(total_pages=Sum('book__page_count'))['total_pages']
    ) or 0
    # Get the user's liked award years
    liked_award_years = set(AwardYearLike.objects.filter(user=user).values_list('category_id', 'year'))
    # Initialize lists for different completion states
    completed_lists = []  # New list for completed awards
    near_complete_lists = []
    discoverable_lists = []  # For lists user hasn't liked yet
    # Get all award categories and years with their book counts
    award_list_data = (
        BookCategory.objects.values('category', 'year')
        .annotate(total_books=Count('book'))
    )
    # Get user's completed books
    user_completed_books = set(UserBook.objects.filter(
        user=user,
        completed=True
    ).values_list('book_id', flat=True))
    # Get category information including slugs
    categories_info = {
        cat['id']: {'name': cat['name'], 'slug': cat['slug']}
        for cat in Category.objects.values('id', 'name', 'slug')
    }
    # For each award list
    for award_list in award_list_data:
        category_id = award_list['category']
        year = award_list['year']
        total_books = award_list['total_books']
        # Get all books in this category/year
        books_in_list = set(BookCategory.objects.filter(
            category_id=category_id,
            year=year
        ).values_list('book_id', flat=True))
        # Check completion status
        completed_books_in_list = books_in_list & user_completed_books
        completion_ratio = len(completed_books_in_list) / total_books
        # Skip if completion ratio is too low
        if completion_ratio < NEAR_COMPLETION_THRESHOLD:
            continue
        # Prepare list data
        list_data = {
            'category': categories_info[category_id]['name'],
            'category_slug': categories_info[category_id]['slug'],
            'year': year,
            'completed_count': len(completed_books_in_list),
            'total_books': total_books,
            'completion_percentage': round(completion_ratio * 100, 1)
        }
        # Add to appropriate list based on whether it's liked and completion status
        if (category_id, year) in liked_award_years:
            if completion_ratio == 1.0:
                completed_lists.append(list_data)
            else:
                near_complete_lists.append(list_data)
        else:
            discoverable_lists.append(list_data)
    # Sort all lists by completion percentage (highest first)
    completed_lists.sort(key=lambda x: x['year'], reverse=True)  # Sort completed by year
    near_complete_lists.sort(key=lambda x: x['completion_percentage'], reverse=True)
    discoverable_lists.sort(key=lambda x: x['completion_percentage'], reverse=True)
    # Calculate total points
    points_from_pages = completed_books_pages
    points_from_books = completed_books_count * 100
    points_from_awards = len(completed_lists) * 500  # Updated to use length of completed_lists
    total_points = points_from_pages + points_from_books + points_from_awards
    context = {
        'completed_books_count': completed_books_count,
        'completed_books_pages': completed_books_pages,
        'completed_lists': completed_lists,  # Add completed lists to context
        'near_complete_lists': near_complete_lists,
        'discoverable_lists': discoverable_lists,
        'points_from_pages': points_from_pages,
        'points_from_books': points_from_books,
        'points_from_awards': points_from_awards,
        'total_points': total_points,
    }
    return render(request, 'pages/user_report.html', context)


def upload_book_categories(request):
    if request.method == "POST" and request.FILES.get("csv_file"):
        csv_file = request.FILES["csv_file"]
        try:
            decoded_file = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded_file, delimiter="\t")
            for row in reader:
                # Get or create author
                author = None
                if row["first_name"].strip() and row["last_name"].strip():
                    author, _ = Author.objects.get_or_create(
                        first_name=row["first_name"].strip(),
                        last_name=row["last_name"].strip(),
                    )

                # Get or create illustrator
                illustrator = None
                if row["illustrator_first_name"].strip() and row["illustrator_last_name"].strip():
                    illustrator, _ = Illustrator.objects.get_or_create(
                        first_name=row["illustrator_first_name"].strip(),
                        last_name=row["illustrator_last_name"].strip(),
                    )

                # Handle existing or new book
                try:
                    book = Book.objects.get(title=row["title"].strip())
                    # Update book's author/illustrator if not already set
                    if author and not book.author:
                        book.author = author
                    if illustrator and not book.illustrator:
                        book.illustrator = illustrator
                    book.save()
                except Book.DoesNotExist:
                    book = Book.objects.create(
                        title=row["title"].strip(),
                        author=author,
                        illustrator=illustrator
                    )
                except Book.MultipleObjectsReturned:
                    messages.error(
                        request,
                        f"Multiple books found with title '{row['title']}'. Please resolve duplicates.",
                    )
                    continue

                # Rest of the function remains the same...
                try:
                    category = Category.objects.get(id=row["category"])
                except Category.DoesNotExist:
                    messages.error(
                        request,
                        f"Category with ID {row['category']} does not exist. Please check your data.",
                    )
                    continue

                try:
                    award_level = AwardLevel.objects.get(id=row["level"])
                except AwardLevel.DoesNotExist:
                    messages.error(
                        request,
                        f"Award level with ID {row['level']} does not exist. Please check your data.",
                    )
                    continue

                BookCategory.objects.update_or_create(
                    book=book,
                    category=category,
                    year=row["year"],
                    defaults={"award_level": award_level},
                )

            messages.success(request, "Book categories uploaded successfully!")
            return redirect("upload_book_categories")
        except Exception as e:
            messages.error(request, f"Error processing file: {e}")
    return render(request, "pages/upload_book_categories.html")


def search_view(request):
    query = request.GET.get('q', '')

    if not query:
        return render(request, 'pages/search/search_results.html', {
            'query': query,
            'authors': [],
            'books': [],
            'illustrators': [],
        })

    authors = Author.objects.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    ).distinct()

    illustrators = Illustrator.objects.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    ).distinct()

    books = Book.objects.filter(
        Q(title__icontains=query) |
        Q(author__first_name__icontains=query) |
        Q(author__last_name__icontains=query) |
        Q(illustrator__first_name__icontains=query) |
        Q(illustrator__last_name__icontains=query) |
        Q(isbn__icontains=query)
    ).distinct()

    # Paginate books
    page_number = int(request.GET.get('page', 1))
    books_paginator = Paginator(books, 10)
    books_page = books_paginator.get_page(page_number)

    if request.headers.get('HX-Request'):
        return render(request, 'pages/search/partials/book_results.html', {
            'books': books_page,
            'query': query,
        })

    return render(request, 'pages/search/search_results.html', {
        'query': query,
        'authors': authors,
        'illustrators': illustrators,
        'books': books_page,
        'total_books': books.count(),
    })

def search_autocomplete(request):
    query = request.GET.get('q', '')
    if len(query) < 2:
        return render(request, 'pages/search/partials/autocomplete_results.html', {'results': []})

    authors = Author.objects.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    )[:5]

    illustrators = Illustrator.objects.filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    )[:5]

    books = Book.objects.filter(
        Q(title__icontains=query)
    )[:5]

    results = {
        'authors': authors,
        'illustrators': illustrators,
        'books': books,
        'query': query
    }

    return render(request, 'pages/search/partials/autocomplete_results.html', results)


def author_detail(request, author_id):
    author = get_object_or_404(Author, id=author_id)

    # Get all books by this author
    books = author.books.all().order_by('title')

    # Paginate the books
    paginator = Paginator(books, 12)  # Show 12 books per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    if request.headers.get('HX-Request'):
        return render(request, 'pages/authors/partials/book_list.html', {
            'books': page_obj,
            'author': author
        })

    return render(request, 'pages/authors/author_detail.html', {
        'author': author,
        'books': page_obj,
        'total_books': books.count(),
    })


def illustrator_detail(request, illustrator_id):
    illustrator = get_object_or_404(Illustrator, id=illustrator_id)

    # Get all books by this author
    books = illustrator.books.all().order_by('title')

    # Paginate the books
    paginator = Paginator(books, 12)  # Show 12 books per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    if request.headers.get('HX-Request'):
        return render(request, 'pages/authors/partials/book_list.html', {
            'books': page_obj,
            'illustrator': illustrator
        })

    return render(request, 'pages/authors/author_detail.html', {
        'illustrator': illustrator,
        'books': page_obj,
        'total_books': books.count(),
    })


def lookup_book(request, pk):
    book = get_object_or_404(Book, pk=pk)

    # Get search parameters from the book
    title = book.title
    author = book.author

    params = {
        'api_key': settings.ASIN_DATA_API_KEY,
        'type': 'search',
        'amazon_domain': 'amazon.com',
        'search_term': f'{title} {author}',
        'exclude_sponsored': 'true',
        'max_page': '1',
        'output': 'json',
        'include_html': 'false',
        'category_id': '283155',
        'page': '1'
    }

    try:
        api_result = requests.get('https://api.asindataapi.com/request', params)
        data = api_result.json()

        # Extract relevant information from search results
        results = [{
            'title': item['title'],
            'asin': item['asin'],
            'image': item['image']
        } for item in data.get('search_results', [])]

        # Render the results partial template
        html = render_to_string('pages/partials/book_results.html', {
            'results': results,
            'book_id': pk
        })

        return JsonResponse({
            'html': html,
            'success': True
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

def update_book_from_api(request, pk):
    if request.method == "POST":
        book = get_object_or_404(Book, pk=pk)
        asin = request.POST.get('asin')
        image_url = request.POST.get('image')

        # Update ASIN
        if asin and not book.asin:
            book.asin = asin

        # Download and save image if missing
        if image_url and not book.image:
            try:
                response = requests.get(image_url)
                if response.status_code == 200:
                    from django.core.files.base import ContentFile
                    image_name = f"{book.pk}_cover.jpg"
                    book.image.save(image_name, ContentFile(response.content), save=True)
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})

        book.save()
        return JsonResponse({
            'success': True,
            'asin': book.asin,
            'image_url': book.image.url if book.image else None
        })

    return JsonResponse({'success': False}, status=400)
