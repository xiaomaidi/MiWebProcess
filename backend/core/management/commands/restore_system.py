import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.management.commands.backup_system import _pg_bin


class Command(BaseCommand):
    help = "从 backup_system 生成的 zip 恢复数据库和 media（危险操作）"

    def add_arguments(self, parser):
        parser.add_argument("backup")
        parser.add_argument("--yes", action="store_true", help="确认执行恢复")

    def handle(self, *args, **options):
        path = Path(options["backup"])
        if not path.exists():
            raise CommandError(f"备份不存在: {path}")
        if not options["yes"]:
            self.stdout.write(self.style.WARNING("dry-run：加上 --yes 才会恢复"))
            with zipfile.ZipFile(path) as zf:
                self.stdout.write("\n".join(zf.namelist()[:40]))
            return
        db = settings.DATABASES["default"]
        tmp = Path(tempfile.mkdtemp(prefix="wp-restore-"))
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(tmp)
            if "sqlite" in db.get("ENGINE", ""):
                target = Path(db["NAME"])
                shutil.copy2(tmp / "db.sqlite3", target)
            else:
                dump = tmp / "db.dump"
                if not dump.exists():
                    raise CommandError("备份中没有 db.dump")
                cmd = [
                    _pg_bin("pg_restore"), "-h", str(db.get("HOST") or "127.0.0.1"),
                    "-p", str(db.get("PORT") or "5432"), "-U", str(db.get("USER") or "postgres"),
                    "--clean", "--if-exists", "-d", str(db.get("NAME")), str(dump),
                ]
                env = dict(os.environ, PGPASSWORD=str(db.get("PASSWORD") or ""))
                subprocess.run(cmd, check=True, env=env)
            media = Path(settings.MEDIA_ROOT)
            if (tmp / "media").exists():
                media.mkdir(parents=True, exist_ok=True)
                for source in (tmp / "media").rglob("*"):
                    if source.is_file():
                        target = media / source.relative_to(tmp / "media")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
            self.stdout.write(self.style.SUCCESS("restore complete"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
