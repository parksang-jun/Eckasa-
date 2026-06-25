"""최종 MP4 를 '공개적으로 접근 가능한 URL' 로 올린다.

Instagram Graph API 는 영상을 직접 업로드하는 게 아니라 video_url(공개 URL)을
던져주면 인스타 서버가 그 URL 에서 영상을 가져간다. 따라서 결과물을 공개 위치에
호스팅해야 한다.

지원:
- r2 / s3 : Cloudflare R2 또는 AWS S3 (S3 호환). 업로드 후 공개 도메인 URL 반환
- local   : 개발용. 로컬 output 폴더를 cloudflared/ngrok 터널로 공개했다고 가정하고
            LOCAL_PUBLIC_BASE_URL + 파일명 으로 URL 을 만든다
"""
from __future__ import annotations

from pathlib import Path

from .config import settings


def _content_type(path: Path) -> str:
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }.get(path.suffix.lower(), "application/octet-stream")


def upload_public(file_path: str, key: str | None = None) -> str:
    """파일을 올리고 공개 URL 을 반환한다."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    key = key or path.name
    provider = settings.storage_provider.lower()

    if provider in ("r2", "s3"):
        return _upload_s3(path, key)
    if provider == "local":
        return _local_url(path)
    raise ValueError(f"알 수 없는 STORAGE_PROVIDER: {provider}")


def _upload_s3(path: Path, key: str) -> str:
    if not (settings.s3_access_key_id and settings.s3_secret_access_key
            and settings.s3_bucket):
        raise RuntimeError(
            "S3/R2 자격증명이 비어 있습니다(.env 의 S3_* 값 확인)."
        )
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region or "auto",
        config=Config(signature_version="s3v4"),
    )
    client.upload_file(
        str(path), settings.s3_bucket, key,
        ExtraArgs={"ContentType": _content_type(path)},
    )

    base = settings.s3_public_base_url.rstrip("/")
    if base:
        return f"{base}/{key}"
    # 공개 베이스가 없으면 presigned URL(1시간) 로라도 반환
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=3600,
    )


def _local_url(path: Path) -> str:
    base = settings.local_public_base_url.rstrip("/")
    if not base:
        raise RuntimeError(
            "STORAGE_PROVIDER=local 인데 LOCAL_PUBLIC_BASE_URL 이 비어 있습니다. "
            "cloudflared/ngrok 로 output 폴더를 공개하고 그 URL 을 넣으세요."
        )
    return f"{base}/{path.name}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python -m app.uploader <파일경로>")
        raise SystemExit(1)
    print(upload_public(sys.argv[1]))
