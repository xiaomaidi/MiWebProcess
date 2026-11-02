from django.conf import settings
from django.db import models


class AiProvider(models.Model):
    """OpenAI-compatible AI 供应商配置；API Key 加密存储，不返回给前端。"""

    TYPE_CHOICES = (
        ("deepseek", "DeepSeek"),
        ("openai", "OpenAI"),
        ("ollama", "Ollama"),
        ("custom", "OpenAI-compatible"),
    )

    name = models.CharField(max_length=120, unique=True)
    provider_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="deepseek")
    base_url = models.CharField(max_length=500)
    model = models.CharField(max_length=160, default="deepseek-chat")
    api_key = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    temperature = models.FloatField(default=0.4)
    timeout = models.IntegerField(default=90)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_ai_providers"
        ordering = ("-is_default", "id")

    def __str__(self):
        return f"{self.name}({self.provider_type}/{self.model})"


class AiConversation(models.Model):
    """AI 多轮会话：绑定应用与当前页面，保留完整消息与工具调用轨迹。"""

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="ai_conversations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    page_id = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_ai_conversations"
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["app", "-updated_at"])]

    def __str__(self):
        return f"{self.app_id}/{self.title or self.id}"


class AiMessage(models.Model):
    """会话消息：user / assistant / tool。"""

    ROLE_CHOICES = (
        ("user", "用户"),
        ("assistant", "助手"),
        ("tool", "工具"),
        ("system", "系统"),
    )

    conversation = models.ForeignKey(AiConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="user")
    content = models.TextField(blank=True, default="")
    tool_name = models.CharField(max_length=80, blank=True, default="")
    tool_args = models.JSONField(default=dict, blank=True)
    tool_result = models.JSONField(default=dict, blank=True)
    proposal = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=160, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_ai_messages"
        ordering = ("id",)
        indexes = [models.Index(fields=["conversation", "id"])]

    def __str__(self):
        return f"{self.conversation_id}/{self.role}"


class AiBuildJob(models.Model):
    """AI 全自动建站任务：记录蓝图、步骤进度、日志与产物。"""

    STATUS_CHOICES = (
        ("pending", "排队中"),
        ("running", "执行中"),
        ("success", "已完成"),
        ("failed", "失败"),
        ("cancelled", "已取消"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    app = models.ForeignKey("appcore.App", null=True, blank=True, on_delete=models.SET_NULL, related_name="ai_build_jobs")
    prompt = models.TextField()
    options = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    current_step = models.CharField(max_length=40, blank=True, default="")
    progress = models.IntegerField(default=0)
    steps = models.JSONField(default=list, blank=True)
    logs = models.TextField(blank=True, default="")
    blueprint = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    provider = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=160, blank=True, default="")
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wp_ai_build_jobs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"build#{self.id} {self.status}"


class AiUsageLog(models.Model):
    """AI 调用估算日志：记录操作、Provider、字符数和估算 token。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    app = models.ForeignKey("appcore.App", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=40)
    provider = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=160, blank=True, default="")
    prompt_chars = models.IntegerField(default=0)
    response_chars = models.IntegerField(default=0)
    estimated_tokens = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_ai_usage_logs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"], name="wp_ai_usage_created_idx"),
            models.Index(fields=["action"], name="wp_ai_usage_action_idx"),
        ]

class AgentTask(models.Model):
    """高级 Agent 任务：独立于聊天消息，可排队、暂停、审批、验证。"""

    STATUS_CHOICES = (
        ("pending", "待执行"),
        ("running", "执行中"),
        ("waiting_approval", "待审批"),
        ("applied", "已应用"),
        ("failed", "失败"),
        ("cancelled", "已取消"),
    )
    MODE_CHOICES = (
        ("page_edit", "页面修改"),
        ("page_build", "页面生成"),
        ("app_build", "应用搭建"),
    )
    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="agent_tasks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    page_id = models.IntegerField(null=True, blank=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="page_edit")
    goal = models.TextField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="pending")
    risk = models.CharField(max_length=20, default="medium")
    provider = models.CharField(max_length=80, blank=True, default="platform")
    model = models.CharField(max_length=160, blank=True, default="")
    context = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_agent_tasks"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["app", "-created_at"])]


class AgentEvent(models.Model):
    task = models.ForeignKey(AgentTask, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=60)
    message = models.CharField(max_length=500, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_agent_events"
        ordering = ("id",)


class AgentProposal(models.Model):
    STATUS_CHOICES = (
        ("pending", "待审批"),
        ("applied", "已应用"),
        ("rejected", "已拒绝"),
        ("rolled_back", "已回滚"),
        ("failed", "失败"),
    )
    task = models.ForeignKey(AgentTask, on_delete=models.CASCADE, related_name="proposals")
    conversation = models.ForeignKey(AiConversation, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    message = models.ForeignKey(AiMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=40, default="page_patch")
    target_type = models.CharField(max_length=40, blank=True, default="page")
    target_id = models.IntegerField(null=True, blank=True)
    base_version = models.IntegerField(null=True, blank=True)
    base_schema = models.JSONField(default=dict, blank=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    ops = models.JSONField(default=list, blank=True)
    schema = models.JSONField(default=dict, blank=True)
    diff = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="pending")
    risk = models.CharField(max_length=20, default="medium")
    verification = models.JSONField(default=dict, blank=True)
    undo = models.JSONField(default=dict, blank=True)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_agent_proposals"
        ordering = ("id",)


class AgentUsage(models.Model):
    task = models.ForeignKey(AgentTask, on_delete=models.CASCADE, related_name="usage")
    steps = models.IntegerField(default=0)
    prompt_chars = models.IntegerField(default=0)
    response_chars = models.IntegerField(default=0)
    estimated_tokens = models.IntegerField(default=0)
    duration_ms = models.IntegerField(default=0)
    cost = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_agent_usage"

class AgentEvalCase(models.Model):
    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="agent_eval_cases")
    name = models.CharField(max_length=200)
    goal = models.TextField()
    page_id = models.IntegerField(null=True, blank=True)
    expected = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_agent_eval_cases"
        ordering = ("-id",)


class AgentEvalRun(models.Model):
    case = models.ForeignKey(AgentEvalCase, on_delete=models.CASCADE, related_name="runs")
    task = models.ForeignKey(AgentTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="eval_runs")
    status = models.CharField(max_length=20, default="pending")
    score = models.IntegerField(default=0)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_agent_eval_runs"
        ordering = ("-id",)

