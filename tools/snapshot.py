import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import load_sources
from crawler.fetch import fetch


def main():
    if len(sys.argv) < 2:
        print("用法: python -m tools.snapshot <source_key> [--url 覆盖地址]")
        raise SystemExit(1)
    key = sys.argv[1]
    override = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else None
    match = [s for s in load_sources() if s["key"] == key]
    if not match:
        print(f"未找到源: {key}")
        raise SystemExit(1)
    src = match[0]
    urls = [override] if override else (src.get("urls") or [src["url"]])
    out_dir = ROOT / "tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = src.get("fixture_ext", "html")
    for index, url in enumerate(urls):
        result = fetch(url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                       timeout=src.get("timeout", 15))
        suffix = "" if index == 0 else f"_{index + 1}"
        out = out_dir / f"{key}_list{suffix}.{ext}"
        out.write_text(result.text, encoding="utf-8")
        print(f"ok={result.ok} status={result.status} bytes={len(result.text)} -> {out}")
        if not result.ok:
            print(f"error: {result.error}")


if __name__ == "__main__":
    main()
