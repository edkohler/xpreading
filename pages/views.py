from django.views.generic import TemplateView
from django.shortcuts import render, get_object_or_404, Http404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Category, UserBookCategory, BookCategory, SharedList, Book, Library, UserBook, UserFavoriteLibrary, AwardYearLike
import uuid
from django.utils.timezone import now, timedelta
from django.core.mail import send_mail
from collections import defaultdict
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Count
from django.contrib.auth.mixins import LoginRequiredMixin
import json
import requests
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q


class HomePageView(TemplateView):
    template_name = "pages/home.html"


class AboutPageView(TemplateView):
    template_name = "pages/about.html"




def books_by_category(request, category_name):
    category = Category.objects.get(name=category_name)
    books = BookCategory.objects.filter(category=category).select_related('book', 'award_level')
    return render(request, 'pages/books_by_category.html', {'category': category, 'books': books})




@login_required
def manage_book_list(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    book_categories = BookCategory.objects.filter(category=category).select_related('book', 'award_level').order_by('-year')
    user_book_categories = {ubc.book_category_id: ubc for ubc in UserBookCategory.objects.filter(user=request.user)}

    context = {
        'category': category,
        'book_categories': book_categories,
        'user_book_categories': user_book_categories,
    }
    return render(request, 'pages/manage_book_list.html', context)


@login_required
def share_book_list(request):
    if request.method == "POST":
        recipient_email = request.POST.get('email')
        expires_in = int(request.POST.get('expires_in', 7))  # Default to 7 days
        token = uuid.uuid4().hex
        expires_at = now() + timedelta(days=expires_in)

        shared_list = SharedList.objects.create(
            owner=request.user,
            recipient_email=recipient_email,
            token=token,
            expires_at=expires_at
        )

        # Send email with the sharing link
        share_link = request.build_absolute_uri(f"/shared-list/{token}/")
        send_mail(
            subject="Your Shared Book List",
            message=f"View the shared book list here: {share_link}",
            from_email="kohler@haystackinaneedle.com",
            recipient_list=[recipient_email],
        )

        return render(request, 'pages/share_success.html', {'recipient_email': recipient_email})
    return render(request, 'pages/share_book_list.html')




def view_shared_list(request, token):
    shared_list = get_object_or_404(SharedList, token=token)

    if shared_list.expires_at and shared_list.expires_at < now():
        raise Http404("This shared list has expired.")

    user_book_categories = UserBookCategory.objects.filter(user=shared_list.owner)
    context = {
        'shared_list': shared_list,
        'user_book_categories': user_book_categories,
    }
    return render(request, 'pages/view_shared_list.html', context)


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    books = BookCategory.objects.filter(category=category).select_related('book', 'award_level').order_by('-year')
    user_book_categories = (
        UserBookCategory.objects.filter(user=request.user, book_category__in=books)
        .values_list('book_category_id', flat=True)
        if request.user.is_authenticated else []
    )

    from collections import defaultdict
    books_by_year = defaultdict(list)
    for book_category in books:
        if book_category.id and book_category.book:
            books_by_year[book_category.year].append({
                'book_category': book_category,
                'completed': book_category.id in user_book_categories,
            })

    # Debug the structure of books_by_year
    print("Books by Year:", books_by_year)

    context = {
        'category': category,
        'books_by_year': dict(books_by_year),  # Convert to a regular dictionary for easier template handling
    }
    return render(request, 'pages/category_detail.html', context)






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
    else:
        other_libraries = Library.objects.all()

    context = {
        'book': book,
        'categories': categories,
        'user_book_categories': user_book_categories,
        'first_category': first_category,
        'first_category_completed': first_category_completed,
        'libraries': libraries,
        'favorite_libraries': favorite_libraries,
    }
    return render(request, 'pages/book_detail.html', context)




@login_required
@require_POST
def toggle_read_status(request, book_category_id):
    book_category = get_object_or_404(BookCategory, id=book_category_id)
    data = json.loads(request.body)  # Parse JSON payload
    completed = data.get('completed', False)  # Get 'completed' status from the request

    # Get or create the UserBookCategory object
    user_book, created = UserBookCategory.objects.get_or_create(
        user=request.user,
        book_category=book_category
    )

    # Update the completed status
    user_book.completed = completed
    user_book.save()

    return JsonResponse({'completed': user_book.completed})


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

    return render(request, 'pages/partials/book_read_checkbox.html', context)


class BooksByCategoryView(LoginRequiredMixin, TemplateView):
    template_name = "pages/user_books_by_category.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # All books marked as completed by the user
        user_completed_books = UserBook.objects.filter(user=user, completed=True).values_list('book_id', flat=True)

        # All categories
        categories = Category.objects.order_by('name')

        books_by_category = {}
        for category in categories:
            books_by_year = {}

            # All BookCategory records for this category
            book_categories = BookCategory.objects.filter(category=category).select_related(
                'book', 'book__author', 'award_level'
            ).order_by('-year', 'book__title')

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


@login_required
def library_list(request):
    user = request.user
    favorite_library_ids = UserFavoriteLibrary.objects.filter(user=user).values_list('library_id', flat=True)
    favorite_libraries = Library.objects.filter(id__in=favorite_library_ids)
    non_favorite_libraries = Library.objects.exclude(id__in=favorite_library_ids)

    context = {
        'favorite_libraries': favorite_libraries,
        'non_favorite_libraries': non_favorite_libraries,
    }
    return render(request, 'pages/library_list.html', context)


@login_required
def toggle_favorite_library(request, library_id):
    if request.method == "POST":
        user = request.user
        library = get_object_or_404(Library, id=library_id)
        favorite, created = UserFavoriteLibrary.objects.get_or_create(user=user, library=library)
        if not created:
            favorite.delete()
            return JsonResponse({'status': 'removed'})
        return JsonResponse({'status': 'added'})
    return JsonResponse({'error': 'Invalid request'}, status=400)


def terms_and_conditions(request):
    return render(request, 'pages/terms_and_conditions.html')


@login_required
def award_year_list(request):
    # Fetch all unique category-year pairs from BookCategory
    award_years = (
        BookCategory.objects.values('category', 'category__name','category__slug', 'year')
        .distinct()
        .order_by('category__name', '-year')
    )

    # Fetch user's liked award years
    liked_awards = AwardYearLike.objects.filter(user=request.user).values_list('category', 'year')
    liked_award_set = {(like[0], like[1]) for like in liked_awards}

    # Add a 'liked' flag to each award year
    for award in award_years:
        award['liked'] = (award['category'], award['year']) in liked_award_set

    context = {
        'award_years': award_years,
    }
    return render(request, 'pages/award_year_list.html', context)


@login_required
def toggle_award_year_like(request, category_id, year):
    category = Category.objects.get(id=category_id)
    like, created = AwardYearLike.objects.get_or_create(user=request.user, category=category, year=year)
    if not created:
        like.delete()
    return redirect('award_year_list')


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

    # Process each query
    for book_id in book_ids:
        url = f"{base_url}{book_id}{url_suffix}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            # Iterate over bibItems to filter and count unique books by branch
            for item_id, item_data in data.get("entities", {}).get("bibItems", {}).items():
                availability = item_data.get("availability", {})
                if availability.get("statusType") == "AVAILABLE":
                    branch_name = item_data.get("branchName", "Unknown")
                    branch_unique_books[branch_name].add(book_id)

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
    Q(page_count__isnull=True) | Q(page_count='')
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
