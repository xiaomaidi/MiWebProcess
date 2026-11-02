import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _pg_bin(name: str) -> str:
    configured = os.environ.get(f"PG_{name.upper()}_BIN") or os.environ.get("PG_BIN")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which(name)
    if found:
        return found
    for candidate in (
        rf"C:\Program Files\PostgreSQL\17\bin\{name}.exe",
        rf"C:\Program Files\PostgreSQL\16\bin\{name}.exe",
        f"/usr/bin/{name}",
    ):
        if Path(candidate).exists():
            return candidate
    raise CommandError(f"找不到 {name}，请设置 PG_BIN 或 PG_{name.upper()}_BIN")


class Command(BaseCommand):
    help = "备份数据库和 media 到 zip"

    def add_arguments(self, parser):
        parser.add_argument("--output", default="")
        parser.add_argument("--no-media", action="store_true")

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        root = Path(settings.BASE_DIR)
        output = Path(options["output"] or root / "backups" / f"webprocess-{stamp}.zip")
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="wp-backup-"))
        try:
            if "sqlite" in engine:
                source = Path(db["NAME"])
                if source.exists():
                    shutil.copy2(source, tmp / "db.sqlite3")
                db_file = "db.sqlite3"
            else:
                db_file = "db.dump"
                cmd = [
                    _pg_bin("pg_dump"), "-h", str(db.get("HOST") or "127.0.0.1"),
                    "-p", str(db.get("PORT") or "5432"), "-U", str(db.get("USER") or "postgres"),
                    "-Fc", "-f", str(tmp / db_file), str(db.get("NAME")),
                ]
                env = dict(os.environ, PGPASSWORD=str(db.get("PASSWORD") or ""))
                subprocess.run(cmd, check=True, env=env)
            manifest = {
                "created_at": datetime.now().isoformat(),
                "database": db.get("NAME"),
                "engine": engine,
                "with_media": not options["no_media"],
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            media = Path(settings.MEDIA_ROOT)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(tmp / db_file, db_file)
                zf.write(tmp / "manifest.json", "manifest.json")
                if not options["no_media"] and media.exists():
                    for path in media.rglob("*"):
                        if path.is_file():
                            zf.write(path, f"media/{path.relative_to(media)}")
            self.stdout.write(self.style.SUCCESS(f"backup: {output}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
