from django.urls import path

from appcore import template_views

urlpatterns = [
    path("apply/", template_views.apply_template, name="template_apply"),
    path("import/", template_views.import_template, name="template_import"),
    path("library/", template_views.library_list_create, name="template_library"),
    path("library/<int:pk>/", template_views.library_detail, name="template_library_detail"),
    path("library/<int:pk>/publish/", template_views.library_publish, name="template_library_publish"),
    path("library/<int:pk>/access/", template_views.library_access, name="template_library_access"),
    path("library/<int:pk>/access/<int:user_id>/", template_views.library_access_detail, name="template_library_access_detail"),
    path("library/<int:pk>/apply/", template_views.library_apply, name="template_library_apply"),
    path("library/<int:pk>/versions/", template_views.library_versions, name="template_library_versions"),
    path("library/<int:pk>/versions/<int:version>/rollback/", template_views.library_rollback, name="template_library_rollback"),
    path("library/from-app/<int:app_id>/", template_views.library_from_app, name="template_library_from_app"),
    path("clone/", template_views.clone_app, name="template_clone"),
    path("export/<int:app_id>/", template_views.export_app_template, name="template_export"),
]
