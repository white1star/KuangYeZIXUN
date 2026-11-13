"""选矿热榜静态页构建。"""
import json
import shutil
from pathlib import Path

import jinja2

from site_build.hot import data

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _write(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path.stat().st_size


def _json_text(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build(conn, out_dir, articles: list, prices: dict, build_time: str) -> dict:
    out = Path(out_dir)
    payload = data.build_payload(conn, articles, prices, build_time)
    payload["cache_bust"] = build_time.replace(" ", "").replace(":", "")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True, trim_blocks=True, lstrip_blocks=True,
    )
    html = env.get_template("hot.html").render(**payload)
    grid_html = env.get_template("grid.html").render(**payload)

    sizes = {"index.html": _write(out / "index.html", grid_html),
             "classic.html": _write(out / "classic.html", html)}
    for name in ("hot.css", "hot.js", "grid.css", "grid.js"):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC_DIR / name, target)
        sizes[name] = target.stat().st_size
    sizes["hot.json"] = _write(out / "hot.json", _json_text(payload))
    return {
        "sizes": sizes,
        "counts": {
            "top10": len(payload["top10"]),
            "wechat": len(payload["wechat"]),
            "baidu_news": len(payload["baidu_news"]),
            "social": len(payload["social"]),
            "bilibili": len(payload["bilibili"]),
            "industry": len(payload["industry"]),
            "prices": len(payload["prices"]),
        },
    }
