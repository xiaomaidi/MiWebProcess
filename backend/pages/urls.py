from django.urls import path

from pages import views

urlpatterns = [
    path("<int:pk>/", views.page_detail, name="page_detail"),
    path("<int:pk>/schema/", views.page_schema, name="page_schema"),
    path("<int:pk>/publish/", views.page_publish, name="page_publish"),
    path("<int:pk>/versions/", views.page_versions, name="page_versions"),
    path("<int:pk>/versions/<int:version>/rollback/", views.page_version_rollback, name="page_version_rollback"),
    path("<int:pk>/preview/", views.page_preview, name="page_preview"),
]
