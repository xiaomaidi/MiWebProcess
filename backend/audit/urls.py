from django.urls import path

from audit import views

urlpatterns = [
    path("", views.audit_list, name="audit-list"),
    path("logs/", views.audit_list, name="audit-logs"),
]
