from django.conf import settings
from django.db import models


class App(models.Model):
    """应用（业务站点）：页面/组件/数据源/数据模型的容器。"""

    STATUS_CHOICES = (
        ("draft", "草稿"),
        ("published", "已发布"),
        ("archived", "已归档"),
    )

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_apps")
    # 归属部门：开启 department_visible 后，部门（含子部门）成员获得只读访问
    department = models.ForeignKey(
        "org.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="apps"
    )
    department_visible = models.BooleanField(default=False)
    # 应用级设计 Token（颜色/间距/字体/圆角/阴影/断点），页面可继承
    design_tokens = models.JSONField(default=dict, blank=True)
    design_tokens_history = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_apps"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name}({self.code})"


class AppAuthConfig(models.Model):
    """应用级登录/注册配置：平台统一账号，应用决定品牌与准入策略。"""

    MODE_CHOICES = (
        ("platform", "平台账号"),
        ("public", "公开访问"),
        ("closed", "关闭登录"),
    )

    app = models.OneToOneField(App, on_delete=models.CASCADE, related_name="auth_config")
    enabled = models.BooleanField(default=True)
    require_login = models.BooleanField(default=False)
    allow_register = models.BooleanField(default=False)
    auto_join = models.BooleanField(default=True)
    default_role = models.CharField(max_length=20, default="viewer", choices=(("viewer", "只读"), ("editor", "编辑")))
    invite_required = models.BooleanField(default=False)
    invite_code = models.CharField(max_length=80, blank=True, default="")
    login_title = models.CharField(max_length=160, blank=True, default="")
    login_subtitle = models.CharField(max_length=240, blank=True, default="")
    logo_url = models.CharField(max_length=500, blank=True, default="")
    theme_color = models.CharField(max_length=20, blank=True, default="#2563eb")
    redirect_path = models.CharField(max_length=200, blank=True, default="")
    allowed_domains = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_app_auth_configs"

    def __str__(self):
        return f"{self.app_id}/auth"


class AppModule(models.Model):
    """应用模块开关：平台内核一次开发，应用按需启用。"""

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="modules")
    key = models.CharField(max_length=60)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)
    sort = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_app_modules"
        unique_together = (("app", "key"),)
        ordering = ("sort", "id")

    def __str__(self):
        return f"{self.app_id}/{self.key}"


class AppMember(models.Model):
    """应用成员：owner / editor / viewer。"""

    ROLE_CHOICES = (
        ("owner", "所有者"),
        ("editor", "编辑"),
        ("viewer", "只读"),
    )

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="app_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="viewer")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_app_members"
        unique_together = (("app", "user"),)

    def __str__(self):
        return f"{self.user} @ {self.app} ({self.role})"


class NotificationTemplate(models.Model):
    """应用级通知模板：站内信/邮件/Webhook 文案与变量。"""

    CHANNEL_CHOICES = (("inapp", "站内信"), ("email", "邮件"), ("webhook", "Webhook"))
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="notification_templates")
    key = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="inapp")
    subject = models.CharField(max_length=240, blank=True, default="")
    content = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True)
    variables = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_notification_templates"
        unique_together = (("app", "key"),)

    def __str__(self):
        return f"{self.app_id}/{self.key}"


class NotificationLog(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="notification_logs")
    template = models.ForeignKey(NotificationTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    channel = models.CharField(max_length=20, default="inapp")
    recipient = models.CharField(max_length=240, blank=True, default="")
    subject = models.CharField(max_length=240, blank=True, default="")
    content = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, default="sent")
    read_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_notification_logs"
        ordering = ("-created_at",)


class ApiToken(models.Model):
    """应用级 API Token：只保存哈希，明文只在创建时返回一次。"""

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=24, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_api_tokens"
        ordering = ("-created_at",)


class WebhookEndpoint(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="webhooks")
    name = models.CharField(max_length=160)
    url = models.CharField(max_length=500)
    secret = models.CharField(max_length=120, blank=True, default="")
    events = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    last_status = models.CharField(max_length=40, blank=True, default="")
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_webhook_endpoints"
        ordering = ("-created_at",)


class WebhookDelivery(models.Model):
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=80)
    payload = models.JSONField(default=dict, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    response = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_webhook_deliveries"
        ordering = ("-created_at",)


class ScheduledJob(models.Model):
    """应用级定时任务配置；实际调度由平台 cron/Celery 执行。"""

    HANDLER_CHOICES = (
        ("noop", "空任务"),
        ("webhook.test", "Webhook 测试"),
        ("notification.test", "通知测试"),
    )
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="scheduled_jobs")
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=80)
    handler = models.CharField(max_length=80, choices=HANDLER_CHOICES, default="noop")
    cron = models.CharField(max_length=80, default="0 2 * * *")
    payload = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=40, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_scheduled_jobs"
        unique_together = (("app", "code"),)
        ordering = ("-created_at",)


class AppTemplate(models.Model):
    """服务端模板库：可发布、共享、版本化的模板。"""

    VISIBILITY_CHOICES = (
        ("private", "私有"),
        ("shared", "共享"),
        ("market", "模板市场"),
    )
    STATUS_CHOICES = (("draft", "草稿"), ("published", "已发布"))

    name = models.CharField(max_length=200)
    key = models.SlugField(max_length=80, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")
    icon = models.CharField(max_length=20, blank=True, default="◇")
    accent = models.CharField(max_length=20, blank=True, default="#409eff")
    tags = models.JSONField(default=list, blank=True)
    bundle = models.JSONField(default=dict, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="app_templates")
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="private")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    current_version = models.IntegerField(default=1)
    downloads = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_app_templates"
        ordering = ("-updated_at",)

    def save(self, *args, **kwargs):
        if not self.key:
            from django.utils.text import slugify
            import uuid

            base = slugify(self.name) or "template"
            self.key = f"{base}-{uuid.uuid4().hex[:6]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AppTemplateVersion(models.Model):
    template = models.ForeignKey(AppTemplate, on_delete=models.CASCADE, related_name="versions")
    version = models.IntegerField()
    bundle = models.JSONField(default=dict, blank=True)
    changelog = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_app_template_versions"
        ordering = ("-version",)
        unique_together = (("template", "version"),)


class AppTemplateAccess(models.Model):
    template = models.ForeignKey(AppTemplate, on_delete=models.CASCADE, related_name="accesses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="template_accesses")
    role = models.CharField(max_length=20, default="viewer")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_app_template_accesses"
        unique_together = (("template", "user"),)

