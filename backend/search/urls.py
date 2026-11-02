from django.urls import path

from search import views

urlpatterns = [
    path("", views.search, name="search-query"),
    path("stats/", views.search_stats, name="search-stats"),
    path("suggest/", views.search_suggest, name="search-suggest"),
    path("rebuild/", views.search_rebuild, name="search-rebuild"),
]
