from django.urls import path

from .views import HomePageView, AboutPageView, BooksByCategoryView
from . import views

urlpatterns = [
    path('', views.category_list_sorted_by_year, name='home'),
    path("about/", AboutPageView.as_view(), name="about"),
    path('terms-and-conditions/', views.terms_and_conditions, name='terms_and_conditions'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('categories/<slug:slug>/', views.category_detail, name='category_detail'),
    path('books/mark_read/<int:book_id>/', views.mark_book_read, name='mark_book_read'),
    path('books/mark_unread/<int:book_id>/', views.mark_book_unread, name='mark_book_unread'),
    path('book/<slug:book_slug>/', views.book_detail, name='book_detail'),
    path('toggle-read-status/<int:book_category_id>/', views.toggle_read_status, name='toggle_read_status'),
    path('my-books/', BooksByCategoryView.as_view(), name='my_books'),
    path('toggle_read_status_htmx/<int:book_id>/', views.toggle_read_status_htmx, name='toggle_read_status_htmx'),
    path('libraries/', views.library_list, name='library_list'),
    path('libraries/toggle-favorite/<int:library_id>/', views.toggle_favorite_library, name='toggle_favorite'),
    path('libraries/add_favorite/<int:library_id>/', views.add_favorite_library, name='add_favorite_library'),
    path('libraries/remove_favorite/<int:library_id>/', views.remove_favorite_library, name='remove_favorite_library'),
    path('book_lists/', views.award_year_list, name='award_year_list'),
    path('award-like/<int:category_id>/<int:year>/', views.add_award_like, name='add_award_like'),
    path('award-unlike/<int:category_id>/<int:year>/', views.remove_award_like, name='remove_award_like'),
    path('toggle-award-year-like/<int:category_id>/<int:year>/', views.toggle_award_year_like, name='toggle_award_year_like'),
    path('my-award-lists/', views.my_award_lists, name='my_award_lists'),
    path('my-to-read-list/', views.my_to_read_list, name='my_to_read_list'),
    path('get_unique_books_per_branch/<str:library_id>/', views.get_unique_books_per_branch, name='get_unique_books_per_branch'),
    path('data/incomplete-books/', views.incomplete_books_view, name='incomplete_books'),
    path('data/update-book-field/<int:pk>/<str:field_name>/', views.update_book_field, name='update_book_field'),
    path("data/books_without_images/", views.books_without_images, name="books_without_images"),
    path("data/<int:pk>/upload-image/", views.upload_book_image, name="upload_book_image"),
    path('xp_report/', views.xp_report, name='xp_report'),
    path("data/upload_book_categories/", views.upload_book_categories, name="upload_book_categories"),

    path('scrape-books/', views.scrape_view, name='scrape_books_view'),
    path('scrape-books/run/', views.scrape_book_images, name='scrape_books_run'),

    path('author/<int:author_id>/', views.author_detail, name='author_detail'),
    path('illustrator/<int:illustrator_id>/', views.illustrator_detail, name='illustrator_detail'),

    path('search/', views.search_view, name='search'),
    path('search/autocomplete/', views.search_autocomplete, name='search_autocomplete'),

]
