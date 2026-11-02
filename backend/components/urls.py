from django.urls import path

from components import views

urlpatterns = [
    path("", views.component_list, name="component_list"),
    path("custom/", views.component_custom_create, name="component_custom"),
    path("import/", views.component_import, name="component_import"),
    path("compile/", views.component_compile, name="component_compile"),
    path("ai-draft/", views.component_ai_draft, name="component_ai_draft"),
    path("registry/", views.component_registry, name="component_registry"),
    path("<int:pk>/", views.component_detail, name="component_detail"),
    path("<int:pk>/enable/", views.component_enable, name="component_enable"),
    path("<int:pk>/disable/", views.component_disable, name="component_disable"),
    path("<int:pk>/versions/", views.component_versions_by_id, name="component_versions"),
    path("<int:pk>/versions/<str:version>/source/", views.component_version_source, name="component_version_source"),
    path("<int:pk>/versions/<str:version>/rollback/", views.component_rollback, name="component_version_rollback"),
    path("<int:pk>/upgrade/", views.component_upgrade, name="component_upgrade"),
    path("<str:name>/versions/", views.component_versions, name="component_versions_by_name"),
]
