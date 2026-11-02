from django.urls import path

from moderation import views

urlpatterns = [
    path("reviews/", views.review_list, name="moderation-reviews"),
    path("reviews/batch/", views.review_batch, name="moderation-reviews-batch"),
    path("reviews/<int:pk>/", views.review_detail, name="moderation-review-detail"),
    path("reviews/<int:pk>/approve/", views.review_approve, name="moderation-review-approve"),
    path("reviews/<int:pk>/reject/", views.review_reject, name="moderation-review-reject"),
    path("reviews/<int:pk>/withdraw/", views.review_withdraw, name="moderation-review-withdraw"),
    path("submit/", views.review_submit, name="moderation-submit"),
    path("summary/", views.review_summary, name="moderation-summary"),
    path("policies/", views.review_policies, name="moderation-policies"),
]
