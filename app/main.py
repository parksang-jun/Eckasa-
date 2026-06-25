"""FastAPI 웹 대시보드.

페이지/기능:
- GET  /                 대시보드(제품 그리드 + 스케줄 상태)
- POST /crawl            제품 크롤링(백그라운드)
- POST /generate/{pid}   영상만 생성(게시 안 함, 백그라운드)
- POST /publish/{pid}    영상 생성 + 인스타 게시(백그라운드)
- GET  /jobs             작업 진행/이력 (부분 렌더)
- GET  /posts            게시 이력
- POST /schedule/start   자동 게시 시작
- POST /schedule/stop    자동 게시 중지
- 정적: /output(영상), /productimg(제품 이미지)
"""
from __future__ import annotations

import threading
from pathlib import Path

import base64
import secrets
import time
from typing import List

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import IMAGES_DIR, OUTPUT_DIR, SCENE_INPUT_DIR, settings
from . import cancel, db, pipeline, presets, scene, scheduler

# 진행 중으로 간주하는 상태(취소 버튼 노출 대상)
ACTIVE_STATUSES = {"pending", "copy", "clip", "compose", "upload", "publish"}

app = FastAPI(title="ECKASA 릴스 광고 자동화")

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

STATIC_DIR = Path(__file__).parent / "static"

app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/productimg", StaticFiles(directory=str(IMAGES_DIR)), name="productimg")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 로그인 없이 접근 허용(앱 아이콘/매니페스트/서비스워커 — 민감정보 아님)
AUTH_EXEMPT_PREFIXES = ("/static/",)
AUTH_EXEMPT_PATHS = {"/health", "/sw.js", "/favicon.ico"}

_SERVICE_WORKER = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {});
""".strip()


@app.get("/sw.js")
def service_worker():
    return Response(content=_SERVICE_WORKER, media_type="application/javascript")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """app_password 가 설정돼 있으면 모든 요청에 로그인(HTTP Basic)을 요구한다.
    비공개 공유 링크에서 '나만 접속'을 보장한다. (미설정 시 잠금 해제 — 로컬 전용)"""
    path = request.url.path
    if (not settings.app_password
            or path in AUTH_EXEMPT_PATHS
            or path.startswith(AUTH_EXEMPT_PREFIXES)):
        return await call_next(request)
    header = request.headers.get("Authorization", "")
    ok = False
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            ok = (secrets.compare_digest(user, settings.app_username)
                  and secrets.compare_digest(pw, settings.app_password))
        except Exception:  # noqa: BLE001
            ok = False
    if not ok:
        return Response(status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="ECKASA Studio"'})
    return await call_next(request)


def _run_bg(fn, *args, **kwargs) -> None:
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def _rel_image(path: str) -> str:
    """data/images/<pid>/00.jpg -> /productimg/<pid>/00.jpg"""
    try:
        rel = Path(path).resolve().relative_to(IMAGES_DIR.resolve())
        return "/productimg/" + str(rel).replace("\\", "/")
    except ValueError:
        return path


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    scheduler.init_from_settings()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    products = db.list_products()
    for p in products:
        p["thumb"] = _rel_image(p["images"][0]) if p["images"] else None
    return templates.TemplateResponse("index.html", {
        "request": request,
        "products": products,
        "settings": settings,
        "schedule_running": scheduler.is_running(),
        "schedule_cron": db.get_setting("schedule_cron") or settings.schedule_cron,
        "ig_ready": settings.instagram_configured,
        "ai_ready": settings.ai_video_enabled,
        "posts_24h": db.count_posts_last_24h(),
    })


@app.post("/crawl")
def crawl():
    from . import crawler
    _run_bg(crawler.crawl)
    return RedirectResponse("/", status_code=303)


@app.post("/generate/{pid}")
def generate(pid: int):
    _run_bg(pipeline.run_job, pid, publish=False)
    return RedirectResponse("/jobs", status_code=303)


@app.post("/publish/{pid}")
def publish(pid: int):
    _run_bg(pipeline.run_job, pid, publish=True)
    return RedirectResponse("/jobs", status_code=303)


@app.get("/studio/{pid}", response_class=HTMLResponse)
def studio(request: Request, pid: int, bg: str = "", model: str = ""):
    product = db.get_product(pid)
    if not product:
        return RedirectResponse("/", status_code=303)
    sel_bg = bg or settings.default_background
    sel_model = model or settings.default_model
    product["thumb"] = _rel_image(product["images"][0]) if product["images"] else None
    # 이 제품의 최근 작업
    recent = [j for j in db.list_jobs(limit=50) if j["product_id"] == pid][:5]
    for j in recent:
        j["active"] = j["status"] in ACTIVE_STATUSES
        if j.get("video_path"):
            try:
                rel = Path(j["video_path"]).resolve().relative_to(OUTPUT_DIR.resolve())
                j["video_url"] = "/output/" + str(rel).replace("\\", "/")
            except ValueError:
                j["video_url"] = None
    return templates.TemplateResponse("studio.html", {
        "request": request,
        "product": product,
        "backgrounds": presets.background_choices(),
        "models": presets.model_choices(),
        "default_background": sel_bg,
        "default_model": sel_model,
        "scene_count": settings.scene_count,
        "scene_ready": settings.scene_image_enabled,
        "image_provider": settings.scene_image_provider,
        "ai_video_ready": settings.ai_video_enabled,
        "ig_ready": settings.instagram_configured,
        "recent": recent,
        # 완전 무료(반자동)용: 선택한 배경/모델 기준 복붙 프롬프트
        "free_prompts": scene.scene_prompts(sel_bg, sel_model),
        "default_scene_prompt": settings.default_scene_prompt,
        "use_ai_video": settings.use_ai_video,
        # 말하는 시네마틱 영상(Veo)
        "talk_ready": settings.ai_video_enabled,  # fal.ai 키 필요
        "default_dialogue": settings.default_dialogue,
        "veo_resolution": settings.veo_resolution,
        "veo_duration": settings.veo_duration,
        "default_features": settings.default_features,
    })


@app.post("/scene_upload/{pid}")
async def scene_upload(pid: int,
                       files: List[UploadFile] = File(...),
                       publish: str = Form("0")):
    """완전 무료 경로: 사용자가 만든 장면 이미지를 업로드 → 릴스 합성(백그라운드)."""
    dest_dir = SCENE_INPUT_DIR / str(pid) / str(int(time.time()))
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    for i, f in enumerate(files):
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        out = dest_dir / f"{i:02d}{ext}"
        out.write_bytes(await f.read())
        saved.append(str(out))
    if saved:
        _run_bg(pipeline.run_manual_scene_job, pid, saved, publish == "1")
    return RedirectResponse(f"/studio/{pid}", status_code=303)


@app.post("/scene/{pid}")
def scene_make(pid: int,
               background: str = Form(...),
               model: str = Form(...),
               publish: str = Form("0")):
    do_publish = publish == "1"
    _run_bg(pipeline.run_scene_job, pid,
            background_key=background, model_key=model, publish=do_publish)
    return RedirectResponse(f"/studio/{pid}", status_code=303)


@app.post("/scene_prompt/{pid}")
def scene_prompt(pid: int,
                 prompt: str = Form(""),
                 publish: str = Form("0")):
    """가방 이미지 + 프롬프트 1개 → 자동 릴스 (메인 경로)."""
    _run_bg(pipeline.run_prompt_job, pid, prompt, publish == "1")
    return RedirectResponse(f"/studio/{pid}", status_code=303)


@app.post("/hybrid/{pid}")
def hybrid_make(pid: int,
                scene: str = Form(""),
                subtitles: str = Form(""),
                ai_mode: str = Form("image"),
                dialogue: str = Form(""),
                resolution: str = Form("720p"),
                publish: str = Form("0")):
    """브랜드 정확 하이브리드(실제 제품 메인 + AI 분위기) → 백그라운드 실행."""
    _run_bg(pipeline.run_hybrid_job, pid, scene, subtitles, ai_mode, dialogue,
            resolution, publish == "1")
    return RedirectResponse(f"/studio/{pid}", status_code=303)


@app.post("/talk/{pid}")
def talk_make(pid: int,
              scene: str = Form(""),
              dialogue: str = Form(""),
              length: int = Form(8),
              resolution: str = Form("720p"),
              publish: str = Form("0")):
    """말하는 시네마틱 영상(Veo) 생성 → 백그라운드 실행. length=최종 길이(초, 최대 30)."""
    _run_bg(pipeline.run_talking_job, pid, scene, dialogue,
            publish=(publish == "1"), target_seconds=length, resolution=resolution)
    return RedirectResponse(f"/studio/{pid}", status_code=303)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, redirect: str = Form("/jobs")):
    """진행 중인 작업에 취소를 요청한다(현재 단계가 끝나면 중단)."""
    job = db.get_job(job_id)
    if job and job["status"] in ACTIVE_STATUSES:
        cancel.request_cancel(job_id)
        db.update_job(job_id, stage_msg="취소 요청됨 — 현재 단계 종료 후 중단됩니다")
    return RedirectResponse(redirect or "/jobs", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request):
    rows = db.list_jobs(limit=50)
    for j in rows:
        j["active"] = j["status"] in ACTIVE_STATUSES
        if j.get("video_path"):
            try:
                rel = Path(j["video_path"]).resolve().relative_to(OUTPUT_DIR.resolve())
                j["video_url"] = "/output/" + str(rel).replace("\\", "/")
            except ValueError:
                j["video_url"] = None
    return templates.TemplateResponse("jobs.html", {
        "request": request, "jobs": rows,
    })


@app.get("/posts", response_class=HTMLResponse)
def posts(request: Request):
    return templates.TemplateResponse("posts.html", {
        "request": request, "posts": db.list_posts(limit=100),
    })


@app.post("/schedule/start")
def schedule_start():
    scheduler.start()
    return RedirectResponse("/", status_code=303)


@app.post("/schedule/stop")
def schedule_stop():
    scheduler.stop()
    return RedirectResponse("/", status_code=303)


@app.get("/api/jobs")
def api_jobs():
    return JSONResponse(db.list_jobs(limit=50))


@app.get("/health")
def health():
    return {
        "ok": True,
        "instagram_configured": settings.instagram_configured,
        "ai_video_enabled": settings.ai_video_enabled,
        "products": len(db.list_products()),
    }
