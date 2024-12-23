from django.urls import path

from .views import HomePageView, AboutPageView, BooksByCategoryView
from . import views

urlpatterns = [
    #path("", HomePageView.as_view(), name="home"),
    path('', views.category_list_sorted_by_year, name='category_list_sorted_by_year'),

    path("about/", AboutPageView.as_view(), name="about"),
    path('manage-list/<int:category_id>/', views.manage_book_list, name='manage_book_list'),
    path('share-list/', views.share_book_list, name='share_book_list'),
    path('shared-list/<str:token>/', views.view_shared_list, name='view_shared_list'),
    path('books/<str:category_name>/', views.books_by_category, name='books_by_category'),
    path('categories/<slug:slug>/', views.category_detail, name='category_detail'),
    path('book/<slug:book_slug>/', views.book_detail, name='book_detail'),
    path('toggle-read-status/<int:book_category_id>/', views.toggle_read_status, name='toggle_read_status'),
    path('my-books/', BooksByCategoryView.as_view(), name='my_books'),
    path('toggle-read-status-htmx/<int:book_id>/', views.toggle_read_status_htmx, name='toggle_read_status_htmx'),
    path('libraries/', views.library_list, name='library_list'),
    path('libraries/toggle-favorite/<int:library_id>/', views.toggle_favorite_library, name='toggle_favorite'),
]
