from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "is_staff", "is_platform_admin", "is_active")
    list_filter = ("is_staff", "is_platform_admin", "is_active")
    fieldsets = DjangoUserAdmin.fieldsets + (("平台", {"fields": ("is_platform_admin",)}),)
