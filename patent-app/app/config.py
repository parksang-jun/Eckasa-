"""환경설정 로딩. .env 파일의 값을 읽어 타입이 있는 settings 객체로 제공한다."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 (이 파일 기준 한 단계 위)
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"

# 필요한 디렉토리는 임포트 시점에 만들어 둔다.
for _d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = ""
    analysis_model: str = "claude-sonnet-4-6"

    # KIPRIS (한국특허정보원)
    kipris_api_key: str = ""
    kipris_base_url: str = "http://plus.kipris.or.kr/openapi/rest/patUtiliModInfoSearchSevice"
    kipris_rows_per_keyword: int = 5

    # 분석 입력 제한 (모델 토큰 보호용 문자 수)
    max_paper_chars: int = 40_000

    # --- 파생 값 ---
    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def kipris_configured(self) -> bool:
        return bool(self.kipris_api_key.strip())


settings = Settings()
