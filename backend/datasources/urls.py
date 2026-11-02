from django.urls import path

from datasources import views

urlpatterns = [
    path("", views.datasource_list_create, name="datasource_list"),
    path("<int:pk>/", views.datasource_detail, name="datasource_detail"),
    path("<int:pk>/test/", views.datasource_test, name="datasource_test"),
    path("<int:pk>/schema/", views.datasource_schema, name="datasource_schema"),
    path("<int:pk>/run-sql/", views.datasource_run_sql, name="datasource_run_sql"),
    path("<int:pk>/query/", views.datasource_query, name="datasource_query"),
]
