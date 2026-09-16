import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import load_sources
from crawler.fetch import fetch


def run_snapshot(src, urls, out_dir, fetcher=fetch, sleep=time.sleep, interval=1.0):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = src["key"]
    ext = src.get("fixture_ext", "html")
    written = []
    for index, url in enumerate(urls):
        if index:
            sleep(interval)
        result = fetcher(url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                         timeout=src.get("timeout", 15))
        suffix = "" if index == 0 else f"_{index + 1}"
        out = out_dir / f"{key}_list{suffix}.{ext}"
        if not result.ok:
            print(f"ok=False status={result.status} error={result.error}")
            continue
        out.write_text(result.text, encoding="utf-8")
        written.append(out)
        print(f"ok=True status={result.status} bytes={len(result.text)} -> {out}")
    return written


def main():
    usage = "用法: python -m tools.snapshot <source_key> [--url 覆盖地址]"
    if len(sys.argv) < 2:
        print(usage)
        raise SystemExit(1)
    key = sys.argv[1]
    override = None
    if "--url" in sys.argv:
        pos = sys.argv.index("--url")
        if pos + 1 >= len(sys.argv):
            print(usage)
            raise SystemExit(2)
        override = sys.argv[pos + 1]
    match = [s for s in load_sources() if s["key"] == key]
    if not match:
        print(f"未找到源: {key}")
        raise SystemExit(1)
    src = match[0]
    urls = [override] if override else (src.get("urls") or [src["url"]])
    out_dir = ROOT / "tests" / "fixtures"
    written = run_snapshot(src, urls, out_dir)
    if len(written) != len(urls):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
