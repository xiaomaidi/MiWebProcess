"""搜索索引：数据记录 → 可检索文档。

不引入 Elasticsearch/Whoosh：用一张 ``SearchDocument`` 表保存标题/摘要/正文，
配合 SQL 子串过滤 + Python 打分排序，既能在 SQLite 开发环境工作，也能在
PostgreSQL 上通过 ``icontains`` 走索引；后续替换为 PG 全文索引或 ES 时，
只需替换 ``search.services.search_documents``。
"""
from django.db import models


class SearchDocument(models.Model):
    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="search_documents")
    model = models.ForeignKey("datamodels.DataModel", on_delete=models.CASCADE, related_name="search_documents")
    record_id = models.IntegerField()
    title = models.CharField(max_length=300, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    url_path = models.CharField(max_length=300, blank=True, default="")
    model_name = models.CharField(max_length=100, blank=True, default="")
    record_status = models.CharField(max_length=40, blank=True, default="")
    is_public = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    score_base = models.FloatField(default=0)
    content_hash = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_search_documents"
        unique_together = (("app", "model", "record_id"),)
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["app", "is_public", "is_published"]),
            models.Index(fields=["model", "record_id"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self):
        return f"{self.app_id}/{self.model_name}#{self.record_id}"
