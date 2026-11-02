from django.core.management.base import BaseCommand
from django.utils import timezone

from ai.autobuild import start_job
from ai.models import AiBuildJob


class Command(BaseCommand):
    help = "恢复中断/排队的 AI 建站任务（服务重启后执行）"

    def add_arguments(self, parser):
        parser.add_argument("--include-running", action="store_true", help="把 running 任务重置为 pending 后重跑")
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        if options["include_running"]:
            stale = AiBuildJob.objects.filter(status="running")
            for job in stale:
                job.status = "pending"
                job.current_step = ""
                job.save(update_fields=["status", "current_step"])
            self.stdout.write(f"reset running: {stale.count()}")
        jobs = AiBuildJob.objects.filter(status="pending").order_by("id")[: options["limit"]]
        count = 0
        for job in jobs:
            start_job(job)
            count += 1
            self.stdout.write(f"resumed job #{job.id} {job.prompt[:50]}")
        self.stdout.write(self.style.SUCCESS(f"resumed {count} job(s) at {timezone.now().isoformat()}"))
