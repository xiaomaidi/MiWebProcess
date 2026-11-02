from django.urls import path

from appcore import auth_views, service_views, views
from datamodels import views as datamodels_views
from datasources import views as datasources_views
from pages import views as pages_views
from releases import views as releases_views

urlpatterns = [
    path("", views.app_list, name="app_list"),
    path("<int:app_id>/", views.app_detail, name="app_detail"),
    path("<int:app_id>/auth-config/", auth_views.app_auth_config, name="app_auth_config"),
    path("<int:app_id>/modules/", auth_views.app_modules, name="app_modules"),
    path("<int:app_id>/notification-templates/", service_views.notification_templates, name="app_notification_templates"),
    path("<int:app_id>/notification-templates/<int:pk>/", service_views.notification_template_detail, name="notification_template_detail"),
    path("<int:app_id>/notification-templates/<int:pk>/send/", service_views.notification_template_send, name="notification_template_send"),
    path("<int:app_id>/notification-logs/", service_views.notification_logs, name="app_notification_logs"),
    path("<int:app_id>/messages/", service_views.app_messages, name="app_messages"),
    path("<int:app_id>/messages/<int:pk>/read/", service_views.app_message_read, name="app_message_read"),
    path("<int:app_id>/api-tokens/", service_views.api_tokens, name="app_api_tokens"),
    path("<int:app_id>/api-tokens/<int:pk>/", service_views.api_token_detail, name="api_token_detail"),
    path("<int:app_id>/webhooks/", service_views.webhooks, name="app_webhooks"),
    path("<int:app_id>/webhooks/<int:pk>/", service_views.webhook_detail, name="webhook_detail"),
    path("<int:app_id>/webhooks/<int:pk>/test/", service_views.webhook_test, name="webhook_test"),
    path("<int:app_id>/webhooks/<int:pk>/deliveries/", service_views.webhook_deliveries, name="webhook_deliveries"),
    path("<int:app_id>/jobs/", service_views.scheduled_jobs, name="app_scheduled_jobs"),
    path("<int:app_id>/jobs/<int:pk>/", service_views.scheduled_job_detail, name="scheduled_job_detail"),
    path("<int:app_id>/jobs/<int:pk>/run/", service_views.scheduled_job_run, name="scheduled_job_run"),
    path("<int:app_id>/publish/", views.app_publish, name="app_publish"),
    path("<int:app_id>/archive/", views.app_archive, name="app_archive"),
    path("<int:app_id>/design-tokens/versions/", views.app_design_token_versions, name="app_design_token_versions"),
    path("<int:app_id>/pages/", pages_views.app_page_list_create, name="app_pages"),
    path("<int:app_id>/datasources/", datasources_views.app_datasource_root, name="app_datasources"),
    path("<int:app_id>/models/", datamodels_views.app_model_root, name="app_models"),
    path("<int:app_id>/releases/", releases_views.app_release_root, name="app_releases"),
    path("<int:app_id>/members/", views.member_list_create, name="app_members"),
    path("<int:app_id>/members/<int:user_id>/", views.member_update_delete, name="app_member_detail"),
]
