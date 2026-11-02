from django.contrib import admin

from search.models import SearchDocument


@admin.register(SearchDocument)
class SearchDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "app", "model_name", "record_id", "title", "is_public", "is_published", "updated_at")
    list_filter = ("is_public", "is_published", "app")
    search_fields = ("title", "summary", "body")
