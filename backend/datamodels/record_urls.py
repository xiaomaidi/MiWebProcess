from django.urls import path

from datamodels import views

urlpatterns = [
    path("<int:model>/", views.record_list_create, name="record_list"),
    path("<int:model>/batch/", views.record_batch_delete, name="record_batch"),
    path("<int:model>/<int:pk>/", views.record_detail, name="record_detail"),
]
