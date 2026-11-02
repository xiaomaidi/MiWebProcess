from django.db import models


class ComponentMeta(models.Model):
    """组件元数据：内置（来自 shared/component-registry.json）或自定义。"""

    TYPE_CHOICES = (
        ("basic", "basic"),
        ("layout", "layout"),
        ("form", "form"),
        ("chart", "chart"),
        ("business", "business"),
        ("data", "data"),
        ("feedback", "feedback"),
        ("nav", "nav"),
        ("media", "media"),
        ("advanced", "advanced"),
        ("custom", "custom"),
    )

    name = models.CharField("组件名", max_length=128, unique=True)
    label = models.CharField("显示名", max_length=128)
    type = models.CharField("类型", max_length=16, choices=TYPE_CHOICES, default="basic")
    category = models.CharField("分类", max_length=64, blank=True, default="basic")
    version = models.CharField("版本", max_length=32, default="1.0.0")
    props_schema = models.JSONField("属性 Schema", default=dict, blank=True)
    style_schema = models.JSONField("样式 Schema", default=dict, blank=True)
    default_props = models.JSONField("默认属性", default=dict, blank=True)
    events = models.JSONField("事件", default=list, blank=True)
    provides = models.JSONField("提供的状态/事件", default=list, blank=True)
    consumes = models.JSONField("依赖的状态/事件", default=list, blank=True)
    payload_schema = models.JSONField("事件 payload Schema", default=dict, blank=True)
    slots = models.JSONField("插槽", default=list, blank=True)
    accept_children = models.JSONField("可放置子组件", default=list, blank=True)
    source = models.CharField("实现来源", max_length=32, blank=True, default="element-plus")
    element = models.CharField("渲染元素", max_length=128, blank=True, default="")
    is_container = models.BooleanField("容器组件", default=False)
    is_form_field = models.BooleanField("表单字段", default=False)
    default_children = models.JSONField("默认子节点", default=list, blank=True)
    actions_supported = models.JSONField("支持动作", default=list, blank=True)
    icon = models.CharField("图标", max_length=64, blank=True, default="")
    is_builtin = models.BooleanField("内置组件", default=False)
    is_custom = models.BooleanField("自定义组件", default=False)
    is_enabled = models.BooleanField("启用", default=True)
    source_url = models.CharField("来源 URL", max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("type", "name")

    def __str__(self):
        return self.name


class ComponentVersion(models.Model):
    """组件版本历史（不可变快照）。"""

    component = models.ForeignKey(ComponentMeta, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=32)
    meta_snapshot = models.JSONField(default=dict)
    changelog = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(fields=["component", "version"], name="uniq_component_version"),
        )
