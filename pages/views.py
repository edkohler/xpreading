from django.views.generic import TemplateView
from django.shortcuts import render, get_object_or_404, Http404
from django.contrib.auth.decorators import login_required
from .models import Category, UserBookCategory, BookCategory, SharedList, Book, Library, UserBook, UserFavoriteLibrary
import uuid
from django.utils.timezone import now, timedelta
from django.core.mail import send_mail
from collections import defaultdict
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Count
from django.contrib.auth.mixins import LoginRequiredMixin
import json

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
            ).order_by('year', 'book__title')

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
