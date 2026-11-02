from django.contrib import admin

from org.models import Department, DepartmentMember


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "parent", "level", "leader", "is_active")
    search_fields = ("name", "code")


@admin.register(DepartmentMember)
class DepartmentMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "department", "user", "role", "title")
    list_filter = ("role",)
