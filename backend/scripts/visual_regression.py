"""截图视觉回归：Edge headless 截图并与基线比较。

用法：
  python scripts/visual_regression.py --url http://127.0.0.1:5173/... --baseline scripts/baseline.png
  python scripts/visual_regression.py ... --update
"""
import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/microsoft-edge",
    "/usr/bin/chromium",
]


def edge_path() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("找不到 Edge/Chromium，可通过 EDGE_PATH 环境变量指定")


def capture(url: str, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    exe = __import__("os").environ.get("EDGE_PATH") or edge_path()
    subprocess.run(
        [
            exe,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--virtual-time-budget=5000",
            f"--window-size=1440,900",
            f"--screenshot={output}",
            url,
        ],
        check=True,
        timeout=60,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not output.exists():
        raise SystemExit(f"截图未生成: {output}")


def diff_score(a: Path, b: Path) -> float:
    left = Image.open(a).convert("RGB")
    right = Image.open(b).convert("RGB")
    if left.size != right.size:
        right = right.resize(left.size)
    diff = ImageChops.difference(left, right)
    stat = ImageStat.Stat(diff)
    return sum(stat.mean) / max(1, len(stat.mean))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--baseline", default="scripts/baseline.png")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--threshold", type=float, default=3.0)
    args = parser.parse_args()
    baseline = Path(args.baseline)
    current = baseline.with_name("current.png")
    capture(args.url, current)
    if args.update or not baseline.exists():
        baseline.parent.mkdir(parents=True, exist_ok=True)
        current.replace(baseline)
        print(f"baseline updated: {baseline}")
        return 0
    score = diff_score(baseline, current)
    print(f"visual diff: {score:.2f} (threshold {args.threshold})")
    return 0 if score <= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
