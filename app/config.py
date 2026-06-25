"""환경설정 로딩. .env 파일의 값을 읽어 타입이 있는 settings 객체로 제공한다."""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 사내망/보안 프록시(SSL 가로채기, 자체서명 루트 인증서) 환경에서도 https 요청이
# 되도록, OS(윈도우) 인증서 저장소를 파이썬 SSL 에 주입한다. 모든 모듈이 config 를
# 임포트하므로 여기서 한 번만 호출하면 httpx 등 전체에 적용된다.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - 없으면 기본 certifi 로 진행
    pass

# 프로젝트 루트 (이 파일 기준 한 단계 위)
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
ASSETS_DIR = ROOT_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
IMAGES_DIR = DATA_DIR / "images"
SCENE_INPUT_DIR = DATA_DIR / "scene_input"  # 사용자가 올린 무료 장면 이미지

# 필요한 디렉토리는 임포트 시점에 만들어 둔다.
for _d in (DATA_DIR, OUTPUT_DIR, MUSIC_DIR, IMAGES_DIR, SCENE_INPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 사이트 / 크롤링
    eckasa_base_url: str = "https://eckasa.com"
    eckasa_category_nos: str = "45"

    # ffmpeg
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    # Anthropic
    anthropic_api_key: str = ""
    copy_model: str = "claude-haiku-4-5"
    copy_tone: str = "trendy"

    # fal.ai
    fal_key: str = ""
    fal_video_model: str = "fal-ai/kling-video/v1/standard/image-to-video"
    ai_clip_seconds: int = 5
    ai_clip_count: int = 1
    safe_mode: bool = True

    # 장면 광고(모델+배경 합성)
    fal_image_model: str = "fal-ai/nano-banana/edit"  # 가방 형태 유지 이미지편집(유료)
    default_background: str = "europe_street"
    default_model: str = "western_female"
    scene_count: int = 2          # 한 광고에 만들 장면(컷) 수 = 이미지/영상 클립 수
    include_closing_shot: bool = True  # 마지막에 실제 제품 스튜디오 컷 + 가격/CTA

    # 무료 경로: Google AI Studio(Gemini) — 결제 없이 무료 키, 하루 ~500장
    gemini_api_key: str = ""
    gemini_image_model: str = "gemini-2.5-flash-image"  # 일명 nano-banana
    # 장면 이미지 백엔드 선택: auto(무료 gemini 우선) | gemini | fal
    image_provider: str = "auto"
    # 모션 방식: true 면 Kling 등 실제 AI 영상(비용↑), false 면 ffmpeg 줌/패닝(저비용)
    use_ai_video: bool = False

    # 말하는 시네마틱 영상 (Veo 3.1) — 모델이 한국어로 가방 설명 + 립싱크 + 시네마틱 모션
    veo_model: str = "fal-ai/veo3.1/fast/image-to-video"  # Fast=저비용 테스트용
    veo_duration: str = "8s"        # 4s | 6s | 8s
    veo_resolution: str = "720p"    # 720p | 1080p | 4k (테스트는 720p)
    default_dialogue: str = (
        "이 가방 너무 예쁘죠? 방수도 완벽하고 데일리로 들고 다니기 딱이에요!"
    )
    # 영상 최대 길이(초). Veo 는 한 번에 8초라 그 이상은 8초 클립을 이어붙인다.
    max_video_seconds: int = 30
    veo_clip_seconds: int = 8  # 클립 1개 길이(이어붙이기 단위)
    # 기본 프롬프트(스튜디오 프롬프트 입력칸 초기값)
    default_scene_prompt: str = (
        "유럽 파리의 감성적인 거리에서 서양 여성 모델이 이 가방을 어깨에 메고 걷는 "
        "고급스러운 패션 화보. 황금빛 햇살, 시네마틱한 분위기."
    )

    # 영상 스펙
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30
    slide_seconds: float = 2.5

    # 스토리지
    storage_provider: str = "r2"  # r2 | s3 | local
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = "eckasa-reels"
    s3_region: str = "auto"
    s3_public_base_url: str = ""
    local_public_base_url: str = ""

    # Instagram
    ig_user_id: str = ""
    ig_access_token: str = ""
    ig_graph_version: str = "v21.0"

    # 스케줄러
    schedule_cron: str = "0 10 * * *"
    schedule_enabled: bool = False

    # 브랜드
    brand_name: str = "ECKASA"
    default_hashtags: str = "#엑카사 #ECKASA #가방"

    # 접속 보안(로그인) — 공개 링크로 노출할 때 나만 접속하도록 비밀번호 잠금.
    # app_password 가 비어 있으면 잠금 해제(로컬 전용). 공개 링크 쓸 땐 반드시 설정.
    app_username: str = "eckasa"
    app_password: str = ""

    # --- 파생 값 ---
    @property
    def category_list(self) -> List[int]:
        out: List[int] = []
        for part in self.eckasa_category_nos.split(","):
            part = part.strip()
            if part.isdigit():
                out.append(int(part))
        return out

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "eckasa.db"

    @property
    def ai_video_enabled(self) -> bool:
        """이미지→영상(Kling, 유료)은 fal.ai 필요."""
        return bool(self.fal_key.strip())

    @property
    def scene_image_provider(self) -> str:
        """장면 이미지(가방+모델+배경) 생성 백엔드를 고른다."""
        if self.image_provider == "gemini":
            return "gemini" if self.gemini_api_key.strip() else "none"
        if self.image_provider == "fal":
            return "fal" if self.fal_key.strip() else "none"
        # auto: 무료 Gemini 우선, 없으면 유료 fal
        if self.gemini_api_key.strip():
            return "gemini"
        if self.fal_key.strip():
            return "fal"
        return "none"

    @property
    def scene_image_enabled(self) -> bool:
        """장면 광고 가능 여부(무료 Gemini 또는 유료 fal 중 하나라도 설정되면 True)."""
        return self.scene_image_provider != "none"

    @property
    def instagram_configured(self) -> bool:
        return bool(self.ig_user_id.strip() and self.ig_access_token.strip())


settings = Settings()
