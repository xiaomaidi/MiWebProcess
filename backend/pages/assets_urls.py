from django.urls import path

from pages import views

urlpatterns = [
    path("", views.asset_list_create, name="asset_list_create"),
    path("<int:pk>/", views.asset_detail, name="asset_detail"),
]
