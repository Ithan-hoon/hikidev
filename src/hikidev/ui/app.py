"""FastAPI 앱. 라우트는 전부 템플릿을 돌려주고, HTMX 가 조각(/partial/*)을 주기적으로 다시 가져온다.

인증: .env 의 HIKIDEV_UI_PASSWORD 가 있으면 로그인 쿠키 필수. 없으면 127.0.0.1 에만 바인드한다 (serve 가 강제).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hikidev import __version__
from hikidev.config import Config, load_config
from hikidev.home import HikidevHome

from . import data, settings

log = logging.getLogger("hikidev.ui")
HERE = Path(__file__).parent
COOKIE = "hikidev_ui"

NAV = (
    ("room", "/", "방 안"),
    ("journal", "/journal", "일기"),
    ("projects", "/projects", "프로젝트"),
    ("ideas", "/ideas", "아이디어"),
    ("inbox", "/inbox", "받은 편지·승인"),
    ("heartbeat", "/heartbeat", "심장박동"),
    ("settings", "/settings", "설정"),
)


class Auth:
    def __init__(self, password: str | None):
        self.password = password or ""
        # 재시작해도 로그인이 유지되게 비밀번호에서 유도. 비밀번호를 바꾸면 전부 로그아웃.
        seed = self.password or secrets.token_hex(16)
        self.secret = hashlib.sha256(("hikidev-ui:" + seed).encode()).digest()
        self.token = hmac.new(self.secret, b"session", "sha256").hexdigest()

    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def check(self, password: str) -> bool:
        return hmac.compare_digest(password.encode(), self.password.encode())

    def valid(self, cookie: str | None) -> bool:
        return not self.enabled or (bool(cookie) and hmac.compare_digest(cookie.encode(), self.token.encode()))


def create_app(home: HikidevHome, *, password: str | None = None, config: Config | None = None) -> FastAPI:
    app = FastAPI(title="hikidev ui", version=__version__, docs_url=None, redoc_url=None)
    auth = Auth(password)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals.update(nav=NAV, version=__version__, fmt_k=data.fmt_k, fmt_duration=data.fmt_duration)
    templates.env.filters["hm"] = data.hm
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.state.home = home
    app.state.auth = auth

    def cfg() -> Config:
        # yaml 은 UI 에서도 바꾸니 요청마다 다시 읽는다 (작은 파일)
        return config or load_config(home.config_yaml)

    def page(request: Request, template: str, tab: str, /, **ctx: Any) -> HTMLResponse:
        ctx.update(request=request, tab=tab, auth_enabled=auth.enabled)
        return templates.TemplateResponse(request, template, ctx)

    # ── 인증 ─────────────────────────────────────────────────
    @app.middleware("http")
    async def require_login(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/static") or path == "/login" or path == "/healthz":
            return await call_next(request)
        if not auth.valid(request.cookies.get(COOKIE)):
            if request.headers.get("HX-Request"):
                r = Response(status_code=401)
                r.headers["HX-Redirect"] = "/login"
                return r
            return RedirectResponse(f"/login?next={path}", status_code=303)
        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/", error: str = "") -> HTMLResponse:
        if not auth.enabled:
            return RedirectResponse("/", status_code=303)  # type: ignore[return-value]
        return page(request, "login.html", "login", next=next, error=error, name=cfg().name)

    @app.post("/login")
    def login(request: Request, password: str = Form(""), next: str = Form("/")) -> Response:
        if not auth.check(password):
            return RedirectResponse(f"/login?next={next}&error=1", status_code=303)
        r = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
        r.set_cookie(COOKIE, auth.token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return r

    @app.post("/logout")
    def logout() -> Response:
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie(COOKIE)
        return r

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"ok": "1"}

    # ── 방 안 (A) ────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def room(request: Request) -> HTMLResponse:
        return page(request, "room.html", "room", o=data.overview(home, cfg()))

    @app.get("/partial/room-aside", response_class=HTMLResponse)
    def room_aside(request: Request) -> HTMLResponse:
        return page(request, "partials/room_aside.html", "room", o=data.overview(home, cfg()))

    @app.get("/partial/room-header", response_class=HTMLResponse)
    def room_header(request: Request) -> HTMLResponse:
        return page(request, "partials/room_header.html", "room", o=data.overview(home, cfg()))

    # ── 일기 ─────────────────────────────────────────────────
    @app.get("/journal", response_class=HTMLResponse)
    def journal(request: Request, day: str = "") -> HTMLResponse:
        all_ = data.journals(home)
        cur = next((j for j in all_ if j.day == day), all_[0] if all_ else None)
        return page(request, "journal.html", "journal", journals=all_, cur=cur, name=cfg().name)

    # ── 프로젝트 ─────────────────────────────────────────────
    @app.get("/projects", response_class=HTMLResponse)
    def projects(request: Request, name: str = "") -> HTMLResponse:
        c = cfg()
        ps = data.projects(home, data.datetime.now(data.tz_of(c)))
        cur = next((p for p in ps if p.name == name), ps[0] if ps else None)
        return page(request, "projects.html", "projects", projects=ps, cur=cur, name=c.name)

    # ── 아이디어 ─────────────────────────────────────────────
    @app.get("/ideas", response_class=HTMLResponse)
    def ideas(request: Request) -> HTMLResponse:
        return page(request, "ideas.html", "ideas", html=data.ideas_html(home), items=data.ideas(home), name=cfg().name)

    # ── 받은 편지 · 승인 ─────────────────────────────────────
    @app.get("/inbox", response_class=HTMLResponse)
    def inbox(request: Request) -> HTMLResponse:
        c = cfg()
        tz = data.tz_of(c)
        approvals = sorted(home.load_approvals(), key=lambda a: a.requested_at, reverse=True)
        return page(
            request,
            "inbox.html",
            "inbox",
            letters=data.letters(home),
            approvals=approvals,
            tz=tz,
            parse_iso=data.parse_iso,
            name=c.name,
        )

    # ── 심장박동 (B 관제실) ───────────────────────────────────
    def heartbeat_ctx(day: str) -> dict[str, Any]:
        c = cfg()
        tz = data.tz_of(c)
        o = data.overview(home, c)
        day = day or o.today
        records = data.read_log(home, day)
        return {
            "o": o,
            "cfg": c,
            "day": day,
            "days": data.log_days(home),
            "lines": data.stream_lines(records, tz),
            "stats": o.stats if day == o.today else data.day_stats(records, tz),
            "ideas": data.ideas(home),
            "mode_short": c.session.permission_mode.replace("Permissions", "").lower(),
        }

    @app.get("/heartbeat", response_class=HTMLResponse)
    def heartbeat(request: Request, day: str = "") -> HTMLResponse:
        return page(request, "heartbeat.html", "heartbeat", **heartbeat_ctx(day))

    @app.get("/partial/stream", response_class=HTMLResponse)
    def stream(request: Request, day: str = "") -> HTMLResponse:
        return page(request, "partials/stream.html", "heartbeat", **heartbeat_ctx(day))

    @app.get("/partial/console-top", response_class=HTMLResponse)
    def console_top(request: Request, day: str = "") -> HTMLResponse:
        return page(request, "partials/console_top.html", "heartbeat", **heartbeat_ctx(day))

    # ── 설정 ─────────────────────────────────────────────────
    def settings_ctx(**extra: Any) -> dict[str, Any]:
        c = cfg()
        return {
            "fields": settings.FIELDS,
            "values": settings.current_values(home.config_yaml),
            "self_text": home.self_md.read_text(encoding="utf-8") if home.self_md.exists() else "",
            "yaml_text": home.config_yaml.read_text(encoding="utf-8") if home.config_yaml.exists() else "",
            "name": c.name,
            **extra,
        }

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: str = "", error: str = "") -> HTMLResponse:
        return page(request, "settings.html", "settings", **settings_ctx(saved=saved, error=error))

    @app.post("/settings/yaml")
    async def settings_yaml(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        changed, errors = settings.save_yaml(home, form)
        if errors:
            return page(request, "settings.html", "settings", **settings_ctx(error=" / ".join(errors), form=form))
        msg = ("저장: " + ", ".join(changed)) if changed else "바뀐 값 없음"
        return RedirectResponse(f"/settings?saved={msg}", status_code=303)

    @app.post("/settings/self")
    async def settings_self(request: Request, text: str = Form("")) -> Response:
        changed = settings.save_self(home, text)
        msg = "self.md 저장 (변경 로그 .hikidev/ui-changes.jsonl)" if changed else "self.md 바뀐 내용 없음"
        return RedirectResponse(f"/settings?saved={msg}#self", status_code=303)

    return app


def serve(home: HikidevHome, *, host: str, port: int) -> None:
    import uvicorn

    password = os.environ.get("HIKIDEV_UI_PASSWORD") or None
    if not password and host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("HIKIDEV_UI_PASSWORD 가 없어서 127.0.0.1 에만 연다 (.env 에 넣으면 같은 와이파이에서 접속 가능)")
        print("HIKIDEV_UI_PASSWORD 없음 → 127.0.0.1 에만 바인드")
        host = "127.0.0.1"
    app = create_app(home, password=password)
    print(f"hikidev ui: http://{host}:{port}  (home: {home.root})")
    uvicorn.run(app, host=host, port=port, log_level="warning")
