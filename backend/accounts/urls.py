from django.urls import path

from accounts import views

urlpatterns = [
    path("register/", views.register, name="auth_register"),
    path("login/", views.login, name="auth_login"),
    path("token/", views.token, name="auth_token"),
    path("token/refresh/", views.refresh, name="auth_token_refresh"),
    path("refresh/", views.refresh, name="auth_refresh"),
    path("me/", views.me, name="auth_me"),
    path("user/", views.me, name="auth_user"),
    path("users/", views.users_list_create, name="auth_users"),
    path("users/batch/", views.users_batch, name="auth_users_batch"),
    path("login-logs/", views.login_logs, name="auth_login_logs"),
    path("users/<int:pk>/", views.user_detail, name="auth_user_detail"),
    path("users/<int:pk>/access/", views.user_access, name="auth_user_access"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="auth_user_reset_password"),
]
