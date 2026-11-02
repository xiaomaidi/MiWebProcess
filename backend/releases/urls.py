from django.urls import path

from releases import views

urlpatterns = [
    path("", views.release_root, name="release-root"),
    path("<int:pk>/", views.release_detail, name="release_detail"),
    path("<int:pk>/activate/", views.release_activate, name="release_activate"),
    path("<int:pk>/rollback/", views.release_rollback, name="release_rollback"),
    path("<int:pk>/traffic/", views.release_traffic, name="release_traffic"),
    path("<int:pk>/tasks/", views.release_task_list, name="release_tasks"),
    path("tasks/<int:task_id>/", views.release_task_detail, name="release_task_detail"),
    path("active/<str:app_code>/", views.active_release, name="release_active"),
]
