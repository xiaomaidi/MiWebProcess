from django.urls import path

from appcore import service_views

urlpatterns = [
    path("<str:app_code>/models/<int:model_id>/records/", service_views.open_records, name="open-records"),
    path("<str:app_code>/models/<int:model_id>/records/<int:pk>/", service_views.open_record_detail, name="open-record-detail"),
]
