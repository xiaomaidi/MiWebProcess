from django.urls import path

from org import views

urlpatterns = [
    path("departments/", views.department_list_create, name="org-departments"),
    path("departments/<int:pk>/", views.department_detail, name="org-department-detail"),
    path("departments/<int:pk>/move/", views.department_move, name="org-department-move"),
    path("departments/<int:pk>/members/", views.department_members, name="org-department-members"),
    path("departments/<int:pk>/members/bulk/", views.department_bulk_members, name="org-department-members-bulk"),
    path("departments/<int:pk>/members/<int:user_id>/", views.department_member_detail, name="org-department-member-detail"),
    path("departments/<int:pk>/subtree/", views.department_subtree, name="org-department-subtree"),
    path("tree/", views.department_tree, name="org-tree"),
    path("me/", views.department_me, name="org-me"),
    path("users/", views.user_directory, name="org-users"),
]
