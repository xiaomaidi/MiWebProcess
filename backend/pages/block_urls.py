from django.urls import path

from pages import block_views

# 注意：本模块的路径带 /api 前缀，需在 config/urls.py 中 include 到根路径，
# 且必须放在 `path("api/runtime/", include("runtime.urls"))` 之前，
# 否则 /api/runtime/{app}/blocks/{code}/ 会被 runtime 的 `<path:page_path>` 兜底路由截获。
urlpatterns = [
    path("api/apps/<int:app_id>/blocks/", block_views.app_block_list_create, name="app_block_list"),
    path("api/blocks/<int:pk>/", block_views.block_detail, name="block_detail"),
    path("api/runtime/<str:app_code>/blocks/<str:code>/", block_views.runtime_block, name="runtime_block"),
]
