import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from crawler import store
from crawler.config import load_settings
from web import queries

WEB = Path(__file__).resolve().parent


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

    return app


if __name__ == "__main__":
    import uvicorn
    _settings = load_settings()
    (_settings.data_dir / "web.pid").write_text(str(os.getpid()), encoding="utf-8")
    uvicorn.run(create_app(), host="0.0.0.0", port=_settings.port)
