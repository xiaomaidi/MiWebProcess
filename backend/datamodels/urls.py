from django.urls import path

from datamodels import views

urlpatterns = [
    path("", views.model_list_create, name="model_list"),
    path("<int:pk>/", views.model_detail, name="model_detail"),
    # /api/models/{id}/records/（API.md 嵌套路由）
    path("<int:model>/records/", views.record_list_create, name="record_list"),
    path("<int:model>/records/report/", views.record_report, name="record_report"),
    path("<int:model>/report/subscriptions/", views.report_subscription_list, name="report_subscription_list"),
    path("report-subscriptions/<int:pk>/", views.report_subscription_detail, name="report_subscription_detail"),
    path("report-subscriptions/<int:pk>/run/", views.report_subscription_run, name="report_subscription_run"),
    path("<int:model>/records/<int:pk>/publish/", views.record_publish, name="record_publish"),
    path("<int:model>/records/<int:pk>/revert/", views.record_revert, name="record_revert"),
    path("<int:model>/records/export/", views.record_export, name="record_export"),
    path("<int:model>/records/import/", views.record_import, name="record_import"),
    path("<int:model>/records/print/", views.record_print, name="record_print"),
    path("<int:model>/records/batch/", views.record_batch_delete, name="record_batch"),
    path("<int:model>/records/<int:pk>/", views.record_detail, name="record_detail"),
]
