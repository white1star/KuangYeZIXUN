import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from crawler import store
from crawler.config import load_settings
from web import queries

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent


def create_app(db_path=None) -> FastAPI:
    settings = load_settings()
    db_file = Path(db_path) if db_path else settings.db_path
    app = FastAPI(title="矿业资讯站")
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
    templates = Jinja2Templates(directory=str(WEB / "templates"))

    def get_conn():
        conn = store.connect(db_file)
        store.init_db(conn)
        return conn

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        conn = get_conn()
        try:
            ctx = {
                "stats": queries.today_stats(conn),
                "runs": queries.last_runs(conn),
                "articles": queries.latest_articles(conn, limit=40),
                "prices": queries.price_latest(conn, limit=18),
                "policies": queries.latest_policies(conn, limit=6),
            }
        finally:
            conn.close()
        return templates.TemplateResponse(request, "index.html", ctx)

    @app.get("/prices", response_class=HTMLResponse)
    def prices_page(request: Request):
        conn = get_conn()
        try:
            ctx = {"commodities": queries.distinct_commodities(conn),
                   "prices": queries.price_latest(conn, limit=80)}
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

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request, q: str = "", mineral: str = "",
                    board: str = "", source: str = ""):
        conn = get_conn()
        try:
            results = queries.search_articles(conn, q=q, mineral=mineral or None,
                                              board=board or None, source=source or None,
                                              limit=100)
            ctx = {"results": results, "q": q, "mineral": mineral, "board": board,
                   "source": source, "commodities": queries.distinct_commodities(conn),
                   "sources": queries.source_health(conn)}
        finally:
            conn.close()
        return templates.TemplateResponse(request, "search.html", ctx)

    @app.get("/sources", response_class=HTMLResponse)
    def sources_page(request: Request):
        conn = get_conn()
        try:
            health = queries.source_health(conn)
        finally:
            conn.close()
        logs = sorted(settings.logs_dir.glob("crawler_*.log"), reverse=True)[:7]
        return templates.TemplateResponse(request, "sources.html", {
            "health": health, "logs": [p.name for p in logs]})

    @app.post("/admin/run_crawl")
    def run_crawl():
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
    def download_log(name: str):
        path = settings.logs_dir / name
        if not path.exists() or path.parent != settings.logs_dir or not name.startswith("crawler_"):
            return JSONResponse({"ok": False, "message": "日志文件不存在"}, status_code=404)
        return FileResponse(path, filename=name)

    @app.get("/admin/backup/now")
    def backup_now():
        from scripts.backup import run_backup
        path = run_backup(db_file, settings.data_dir / "backup")
        return {"ok": True, "path": str(path)}

    return app


if __name__ == "__main__":
    import uvicorn
    _settings = load_settings()
    (_settings.data_dir / "web.pid").write_text(str(os.getpid()), encoding="utf-8")
    uvicorn.run(create_app(), host="0.0.0.0", port=_settings.port)
