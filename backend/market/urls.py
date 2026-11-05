from django.urls import path

from . import views

urlpatterns = [
    path("items/", views.market_items, name="market-items"),
    path("items/<int:pk>/", views.market_item_detail, name="market-item-detail"),
    path("items/<int:pk>/install/", views.market_install, name="market-install"),
    path("categories/", views.market_categories, name="market-categories"),
]
