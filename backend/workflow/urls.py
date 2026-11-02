from django.urls import path

from workflow import views

urlpatterns = [
    path("definitions/", views.definition_list_create, name="workflow-definitions"),
    path("definitions/<int:pk>/", views.definition_detail, name="workflow-definition"),
    path("definitions/<int:pk>/publish/", views.definition_publish, name="workflow-publish"),
    path("definitions/<int:pk>/start/", views.definition_start, name="workflow-start"),
    path("definitions/<int:pk>/instance/", views.definition_instance, name="workflow-definition-instance"),
    path("instances/", views.instance_list, name="workflow-instances"),
    path("instances/<int:pk>/", views.instance_detail, name="workflow-instance"),
    path("instances/<int:pk>/action/", views.instance_action, name="workflow-instance-action"),
    path("instances/<int:pk>/withdraw/", views.instance_withdraw, name="workflow-instance-withdraw"),
    path("tasks/", views.task_list, name="workflow-tasks"),
    path("tasks/<int:pk>/action/", views.task_action, name="workflow-task-action"),
    path("tasks/<int:pk>/transfer/", views.task_transfer, name="workflow-task-transfer"),
    path("tasks/<int:pk>/add-sign/", views.task_add_sign, name="workflow-task-add-sign"),
    path("tasks/<int:pk>/remind/", views.task_remind, name="workflow-task-remind"),
]
