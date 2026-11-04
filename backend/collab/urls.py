from django.urls import path

from . import views

urlpatterns = [
    path("pages/<int:page_id>/comments/", views.page_comments, name="page-comments"),
    path("comments/<int:pk>/", views.comment_detail, name="comment-detail"),
]
