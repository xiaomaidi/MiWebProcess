"""记录写入后的增量索引信号。"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from datamodels.models import DataRecord

logger = logging.getLogger("search")


@receiver(post_save, sender=DataRecord, dispatch_uid="wp_search_index_record")
def _on_record_saved(sender, instance: DataRecord, **kwargs):
    from search.services import index_record

    pk = instance.pk

    def _run():
        from datamodels.models import DataRecord as Record

        record = Record.objects.filter(pk=pk).select_related("model").first()
        if record is not None:
            index_record(record)

    try:
        transaction.on_commit(_run)
    except Exception:  # pragma: no cover - 索引失败不影响写入
        logger.exception("schedule search index failed")


@receiver(post_delete, sender=DataRecord, dispatch_uid="wp_search_remove_record")
def _on_record_deleted(sender, instance: DataRecord, **kwargs):
    from search.services import remove_record

    try:
        remove_record(instance)
    except Exception:  # pragma: no cover
        logger.exception("remove search index failed")
