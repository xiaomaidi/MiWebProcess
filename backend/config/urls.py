from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    # 认证
    path("api/auth/", include("accounts.urls")),
    # 企业 SSO（OpenID Connect）：公开登录流程 /api/auth/sso/...
    path("api/auth/sso/", include("enterprise_sso.auth_urls")),
    # 企业 SSO：应用级 Provider 配置 /api/apps/{app_id}/sso/...
    # 必须在 appcore 的 /api/apps/ 之前，避免被通配的 <int:app_id>/ 规则截获。
    path("api/apps/<int:app_id>/sso/", include("enterprise_sso.urls")),
    # 应用 / 页面 / 资产
    path("api/apps/", include("appcore.urls")),
    path("api/open/", include("appcore.open_urls")),
    path("api/templates/", include("appcore.template_urls")),
    path("api/security/", include("core.security_urls")),
    path("api/enterprise/", include("core.enterprise_urls")),
    path("api/collab/", include("collab.urls")),
    path("api/market/", include("market.urls")),
    path("api/pages/", include("pages.urls")),
    path("", include("pages.block_urls")),
    path("api/assets/", include("pages.assets_urls")),
    # 组件注册表
    path("api/components/", include("components.urls")),
    # 数据源
    path("api/datasources/", include("datasources.urls")),
    # 数据模型 / 记录
    path("api/models/", include("datamodels.urls")),
    # 组织架构（部门树 / 部门成员 / 数据范围）
    path("api/org/", include("org.urls")),
    # 内容审核
    path("api/moderation/", include("moderation.urls")),
    # 搜索索引
    path("api/search/", include("search.urls")),
    # 实时通道（MQTT / WebSocket）
    path("api/realtime/", include("realtime.urls")),
    # 工作流
    path("api/workflows/", include("workflow.urls")),
    path("api/records/", include("datamodels.record_urls")),
    # 发布
    path("api/releases/", include("releases.urls")),
    # 审计日志
    path("api/audit/", include("audit.urls")),
    path("api/audit-logs/", include("audit.urls")),
    # 运行时（公开）
    path("api/runtime/", include("runtime.urls")),
    # AI 页面生成
    path("api/ai/", include("ai.urls")),
    # OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
