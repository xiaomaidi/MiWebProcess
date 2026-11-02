from django.urls import path

from core import security_views

urlpatterns = [
    path("settings/", security_views.security_settings, name="security-settings"),
    path("test-url/", security_views.security_test_url, name="security-test-url"),
]
