from django.views.generic import TemplateView
from django.shortcuts import render, get_object_or_404, Http404
from django.contrib.auth.decorators import login_required
from .models import Category, UserBookCategory, BookCategory, SharedList, Book, Library
import uuid
from django.utils.timezone import now, timedelta
from django.core.mail import send_mail
from collections import defaultdict
from django.http import JsonResponse
from django.views.decorators.http import require_POST

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
    user_book_categories = UserBookCategory.objects.filter(user=request.user, book_category__in=books).values_list('book_category_id', flat=True) if request.user.is_authenticated else []

    books_by_year = defaultdict(list)
    for book_category in books:
        # Ensure book_category has a valid ID and book
        if book_category.id and book_category.book:
            books_by_year[book_category.year].append({
                'book_category': book_category,
                'completed': book_category.id in user_book_categories,
            })

    context = {
        'category': category,
        'books_by_year': dict(books_by_year),
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
    return render(request, 'pages/categories_sorted_by_year.html', context)


def book_detail(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug)
    categories = BookCategory.objects.filter(book=book).select_related('category', 'award_level')
    user_book_categories = UserBookCategory.objects.filter(user=request.user, book_category__in=categories).values_list('book_category_id', flat=True) if request.user.is_authenticated else []
    libraries = Library.objects.all()

    # Precompute completed status for the first category
    first_category = categories[0] if categories else None
    first_category_completed = first_category.id in user_book_categories if first_category else False

    context = {
        'book': book,
        'categories': categories,
        'user_book_categories': user_book_categories,
        'first_category': first_category,
        'first_category_completed': first_category_completed,
        'libraries': libraries,
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
def toggle_read_status_htmx(request, book_category_id):
    book_category = get_object_or_404(BookCategory, id=book_category_id)
    user_book, created = UserBookCategory.objects.get_or_create(
        user=request.user,
        book_category=book_category
    )

    # Toggle the completed status
    user_book.completed = not user_book.completed
    user_book.save()

    # Render the checkbox state
    return render(request, 'pages/partials/book_read_checkbox.html', {
        'book_category': book_category,
        'completed': user_book.completed,
    })
