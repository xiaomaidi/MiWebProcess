from django.urls import path

from runtime import views
from appcore import auth_views

urlpatterns = [
    path("", views.runtime_root, name="runtime-root"),
    path("<str:app_code>/", views.runtime_root, name="runtime-app"),
    path("<str:app_code>", views.runtime_root, name="runtime-app-noslash"),
    path("<str:app_code>/sitemap.xml", views.runtime_sitemap, name="runtime-sitemap"),
    path("<str:app_code>/auth-config/", auth_views.runtime_auth_config, name="runtime-auth-config"),
    path("<str:app_code>/auth/login/", auth_views.runtime_auth_login, name="runtime-auth-login"),
    path("<str:app_code>/auth/register/", auth_views.runtime_auth_register, name="runtime-auth-register"),
    path("<str:app_code>/content/<int:model_id>/", views.runtime_content_list, name="runtime-content-list"),
    path("<str:app_code>/content/<int:model_id>/report/", views.runtime_content_report, name="runtime-content-report"),
    path("<str:app_code>/content/<int:model_id>/submit/", views.runtime_content_submit, name="runtime-content-submit"),
    path("<str:app_code>/content/<int:model_id>/challenge/", views.runtime_form_challenge, name="runtime-form-challenge"),
    path("<str:app_code>/content/<int:model_id>/<int:pk>/update/", views.runtime_content_update, name="runtime-content-update"),
    path("<str:app_code>/content/<int:model_id>/<int:pk>/revoke-token/", views.runtime_content_revoke_token, name="runtime-content-revoke-token"),
    path("<str:app_code>/content/<int:model_id>/<int:pk>/delete/", views.runtime_content_delete, name="runtime-content-delete"),
    path("<str:app_code>/content/<int:master_id>/join/<int:child_id>/", views.runtime_content_join, name="runtime-content-join"),
    path("<str:app_code>/content/<int:model_id>/<int:pk>/", views.runtime_content_detail, name="runtime-content-detail"),
    path("<str:app_code>/search/", views.runtime_search, name="runtime-search"),
    path("<str:app_code>/search/suggest/", views.runtime_suggest, name="runtime-suggest"),
    path("<str:app_code>/ssr/rebuild/", views.runtime_ssr_rebuild, name="runtime-ssr-rebuild"),
    path("<str:app_code>/prerender/<path:page_path>/", views.runtime_prerender, name="runtime-prerender"),
    path("<str:app_code>/<path:page_path>/", views.runtime_page, name="runtime-page"),
    path("<str:app_code>/<path:page_path>", views.runtime_page, name="runtime-page-noslash"),
]
