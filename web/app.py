import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from crawler import store
from crawler.config import load_settings
from web import notify, queries

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent

NEWS_TYPES = {"新矿山": ["新矿"], "市场": ["价格", "市场"], "技术": ["技术"], "企业": ["企业"], "安全": ["安全"]}
CROSS_BOARD_TYPES = {"新矿山"}

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def require_local(request: Request):
    host = request.client.host if request.client else ""
    if host not in LOCAL_HOSTS:
        raise HTTPException(status_code=404, detail="Not Found")


def _fmt_num(value) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return f"{int(num):,}"
    return f"{num:,.2f}".rstrip("0").rstrip(".")


def _fmt_pct(value) -> str:
    if value is None:
        return ""
    return f"{float(value):+.2f}%"


def _fmt_time(value) -> str:
    text = (value or "").strip()
    return text[11:16] if len(text) >= 16 else (text or "—")


def _change_pct(row) -> float | None:
    if row.get("change_pct") is not None:
        return float(row["change_pct"])
    change = row.get("change")
    value = row.get("value")
    if change is not None and value is not None and (value - change) > 0:
        return round(change / (value - change) * 100, 2)
    return None


def _decorate_price(row: dict) -> dict:
    row = dict(row)
    row["pct"] = _change_pct(row)
    row["source_label"] = row.get("source_name") or row.get("source_key") or ""
    return row


def create_app(db_path=None) -> FastAPI:
    settings = load_settings()
    db_file = Path(db_path) if db_path else settings.db_path
    app = FastAPI(title="矿业资讯站")
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
    templates = Jinja2Templates(directory=str(WEB / "templates"))
    templates.env.filters["num"] = _fmt_num
    templates.env.filters["pct"] = _fmt_pct
    templates.env.filters["hhmm"] = _fmt_time

    def get_conn():
        conn = store.connect(db_file)
        store.init_db(conn)
        return conn

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, q: str = ""):
        conn = get_conn()
        try:
            stats = queries.today_stats(conn)
            dots = queries.source_dots(conn)
            ok_count = sum(1 for d in dots if d["status"] == "ok")
            ctx = {
                "q": q.strip(),
                "results": queries.search_articles(conn, q=q, limit=60) if q.strip() else [],
                "stats": stats,
                "sources_ok": ok_count,
                "sources_total": len(dots),
                "last_fetch": queries.last_fetch_time(conn),
                "commodity_count": len(queries.distinct_commodities(conn)),
            }
        finally:
            conn.close()
        return templates.TemplateResponse(request, "index.html", ctx)

    @app.get("/news", response_class=HTMLResponse)
    def news_page(request: Request, mineral: str = "", type: str = ""):
        types = NEWS_TYPES.get(type)
        board = None if type in CROSS_BOARD_TYPES else "news"
        conn = get_conn()
        try:
            articles = queries.search_articles(conn, board=board,
                                               mineral=mineral or None, types=types, limit=120)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "news.html", {
            "articles": articles, "active_type": type if types else "",
            "types": list(NEWS_TYPES.keys())})

    @app.get("/prices", response_class=HTMLResponse)
    def prices_page(request: Request, commodity: str = "", price_type: str = "", days: int = 30):
        conn = get_conn()
        try:
            commodity_list = queries.distinct_commodities(conn)
            if commodity not in commodity_list:
                commodity = commodity_list[0] if commodity_list else ""
            if days not in (7, 30, 90):
                days = 30
            ctx = {"commodities": commodity_list,
                   "commodity": commodity,
                   "ptype": price_type,
                   "days": days,
                   "type_map": queries.commodity_types(conn),
                   "prices": [_decorate_price(r) for r in queries.price_latest(conn, limit=80)]}
        finally:
            conn.close()
        return templates.TemplateResponse(request, "prices.html", ctx)

    @app.get("/api/prices/{commodity}")
    def price_api(commodity: str, days: int = 30, price_type: str = ""):
        conn = get_conn()
        try:
            points = queries.price_series(conn, commodity, days=days,
                                          price_type=price_type or None)
        finally:
            conn.close()
        return {"commodity": commodity, "days": days, "points": points}

    @app.get("/policy", response_class=HTMLResponse)
    def policy_page(request: Request, region: str = "", source: str = ""):
        conn = get_conn()
        try:
            articles = queries.search_articles(conn, board="policy",
                                               source=source or None, limit=200)
            if region:
                articles = [a for a in articles if region in (a.get("regions") or [])]
            health = queries.source_health(conn)
            sources = [h for h in health if h["board"] == "policy"]
        finally:
            conn.close()
        return templates.TemplateResponse(request, "policy.html", {
            "articles": articles, "region": region, "source": source, "sources": sources})

    @app.get("/sources", response_class=HTMLResponse)
    def sources_page(request: Request, _=Depends(require_local)):
        conn = get_conn()
        try:
            health = queries.source_health(conn)
            ok_count = sum(1 for h in health if h["status"] == "ok")
            err_count = sum(1 for h in health if h["status"] == "error")
            feedback = queries.latest_feedback(conn)
        finally:
            conn.close()
        logs = sorted(settings.logs_dir.glob("crawler_*.log"), reverse=True)[:7]
        return templates.TemplateResponse(request, "sources.html", {
            "health": health, "logs": [p.name for p in logs],
            "ok_count": ok_count, "err_count": err_count, "feedback": feedback})

    @app.post("/feedback")
    async def submit_feedback(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        content = str(data.get("content") or "").strip()
        if not content:
            return JSONResponse({"ok": False, "message": "内容不能为空"}, status_code=400)
        if len(content) > 500:
            return JSONResponse({"ok": False, "message": "内容太长（最多500字）"}, status_code=400)
        contact = str(data.get("contact") or "").strip()[:100]
        page = str(data.get("page") or "").strip()[:300]
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO feedback(content,contact,page,created_at) VALUES(?,?,?,?)",
                (content, contact, page, store.now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
        try:
            notify_config = notify.load_notify_config()
        except Exception:
            notify_config = None
        if notify_config:
            threading.Thread(
                target=notify.send_feedback_email,
                kwargs={"content": content, "contact": contact, "page": page,
                        "config": notify_config},
                daemon=True,
            ).start()
        return {"ok": True}

    @app.post("/admin/run_crawl")
    def run_crawl(_=Depends(require_local)):
        lock = db_file.parent / "crawl.lock"
        if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
            return JSONResponse({"ok": False, "message": "已有抓取任务在运行"}, status_code=409)
        lock.write_text(str(os.getpid()), encoding="utf-8")
        try:
            subprocess.Popen([sys.executable, "-m", "crawler.main", "--once"], cwd=str(ROOT))
        except Exception as exc:
            lock.unlink(missing_ok=True)
            return JSONResponse({"ok": False, "message": f"启动失败: {exc}"}, status_code=500)
        return {"ok": True, "message": "已开始抓取，稍后刷新查看源健康"}

    @app.get("/admin/logs/{name}")
    def download_log(name: str, _=Depends(require_local)):
        path = settings.logs_dir / name
        if not path.exists() or path.parent != settings.logs_dir or not name.startswith("crawler_"):
            return JSONResponse({"ok": False, "message": "日志文件不存在"}, status_code=404)
        return FileResponse(path, filename=name)

    @app.get("/admin/backup/now")
    def backup_now(_=Depends(require_local)):
        from scripts.backup import run_backup
        path = run_backup(db_file, settings.data_dir / "backup")
        return {"ok": True, "path": str(path)}

    return app


if __name__ == "__main__":
    import uvicorn
    _settings = load_settings()
    (_settings.data_dir / "web.pid").write_text(str(os.getpid()), encoding="utf-8")
    uvicorn.run(create_app(), host="0.0.0.0", port=_settings.port)
