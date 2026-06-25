"""ffmpeg 기반 9:16 릴스 영상 합성기 (하이브리드 핵심).

입력:
- images    : 제품 이미지 경로 목록
- subtitles : 화면에 순서대로 얹을 짧은 자막
- ai_clip   : (선택) fal.ai 로 만든 AI 인트로 클립 mp4 경로
- price     : (선택) 마지막에 표시할 가격

처리:
1) 각 제품 이미지를 1080x1920 캔버스(블러 배경 + 원본 비율 유지 전경)로 만들고
   천천히 줌(Ken-Burns) + 자막을 얹어 세그먼트 mp4 생성
2) AI 클립이 있으면 같은 규격으로 정규화해 맨 앞 인트로로 사용
3) 모든 세그먼트를 concat 으로 이어붙이고 BGM(없으면 무음)을 믹스
4) 릴스 규격(H.264, yuv420p, +faststart)으로 최종 출력

ffmpeg / ffprobe 바이너리가 시스템에 설치돼 있어야 한다.
"""
from __future__ import annotations

import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .config import MUSIC_DIR, OUTPUT_DIR, settings

# 한글 지원 폰트 (env FONT_PATH 로 덮어쓸 수 있음)
_FONT_CANDIDATES = [
    os.environ.get("FONT_PATH", ""),
    r"C:\Windows\Fonts\malgun.ttf",      # 맑은 고딕 (Windows 기본)
    r"C:\Windows\Fonts\malgunbd.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _font_path() -> str:
    for c in _FONT_CANDIDATES:
        if c and Path(c).exists():
            return c
    return ""  # 폰트를 못 찾으면 drawtext 를 생략한다


def _esc_path(p: str) -> str:
    """ffmpeg 필터 인자용 경로 이스케이프 (Windows 드라이브 콜론/역슬래시 처리)."""
    return p.replace("\\", "/").replace(":", "\\:")


def _run(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg 실패:\n명령: " + " ".join(cmd) + "\n" + proc.stderr[-2000:]
        )


def extract_last_frame(video_path: str, out_image: str) -> Optional[str]:
    """영상의 마지막 프레임을 이미지로 저장(다음 클립의 시작 프레임용)."""
    try:
        _run([
            settings.ffmpeg_path, "-y", "-sseof", "-0.2", "-i", video_path,
            "-update", "1", "-frames:v", "1", out_image,
        ])
        return out_image if Path(out_image).exists() else None
    except RuntimeError:
        return None


def concat_videos(clips: List[str], out_path: str,
                  max_seconds: Optional[float] = None) -> str:
    """여러 영상 클립(음성 포함)을 이어붙인다. max_seconds 지정 시 그 길이로 자른다.

    클립마다 코덱/해상도가 미세하게 다를 수 있어 재인코딩으로 안전하게 합친다.
    음성(말소리)은 그대로 유지하고, 릴스용 +faststart 를 적용한다.
    """
    clips = [c for c in clips if c and Path(c).exists()]
    if not clips:
        raise ValueError("이어붙일 클립이 없습니다.")
    if len(clips) == 1 and not max_seconds:
        return clips[0]

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        listfile = tmpdir / "list.txt"
        listfile.write_text(
            "".join(f"file '{Path(c).as_posix()}'\n" for c in clips),
            encoding="utf-8",
        )
        cmd = [
            settings.ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile),
        ]
        if max_seconds:
            cmd += ["-t", f"{max_seconds:.2f}"]
        cmd += [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-movflags", "+faststart", out_path,
        ]
        _run(cmd)
    return out_path


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [settings.ffprobe_path, "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _drawtext(text: str, tmpdir: Path, font: str,
              fontsize: int = 60, y_expr: str = "h-th-300") -> str:
    """자막 drawtext 필터 문자열. 텍스트는 임시 파일로 빼서 이스케이프 문제를 피한다."""
    if not text or not font:
        return ""
    tf = tmpdir / f"sub_{abs(hash(text)) % 10_000_000}.txt"
    tf.write_text(text, encoding="utf-8")
    return (
        f"drawtext=fontfile='{_esc_path(font)}':textfile='{_esc_path(str(tf))}':"
        f"fontcolor=white:fontsize={fontsize}:line_spacing=10:"
        f"box=1:boxcolor=black@0.45:boxborderw=22:"
        f"x=(w-text_w)/2:y={y_expr}"
    )


def _make_image_segment(image: str, subtitle: Optional[str], dur: float,
                        tmpdir: Path, idx: int, font: str) -> Path:
    """제품 이미지 1장 → Ken-Burns + 자막 세그먼트 mp4."""
    w, h, fps = settings.video_width, settings.video_height, settings.video_fps
    frames = max(1, int(dur * fps))
    out = tmpdir / f"seg_{idx:02d}.mp4"

    # 블러 배경 + 비율 유지 전경 overlay + 미세 줌(zoompan)
    zoom = "min(zoom+0.0012,1.12)"
    filt = (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},boxblur=24:2,eq=brightness=-0.05[bg];"
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps}"
    )
    sub = _drawtext(subtitle or "", tmpdir, font)
    if sub:
        filt += "," + sub
    filt += ",format=yuv420p[v]"

    # 주의: -t 는 '출력' 옵션으로 둔다. 입력에 -loop 1 -t 를 같이 주면
    # zoompan 이 매 입력 프레임마다 d 프레임을 생성해 영상이 과도하게 길어진다.
    cmd = [
        settings.ffmpeg_path, "-y",
        "-loop", "1", "-i", image,
        "-filter_complex", filt, "-map", "[v]",
        "-t", f"{dur:.3f}",
        "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "20",
        str(out),
    ]
    _run(cmd)
    return out


def _normalize_clip(clip: str, subtitle: Optional[str], tmpdir: Path,
                    idx: int, font: str) -> Path:
    """AI 클립을 동일 규격(해상도/fps/코덱)으로 정규화. concat 호환을 위해 필수."""
    w, h, fps = settings.video_width, settings.video_height, settings.video_fps
    out = tmpdir / f"seg_{idx:02d}.mp4"
    filt = (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},fps={fps}"
    )
    sub = _drawtext(subtitle or "", tmpdir, font)
    if sub:
        filt += "," + sub
    filt += ",format=yuv420p[v]"
    cmd = [
        settings.ffmpeg_path, "-y", "-i", clip,
        "-filter_complex", filt, "-map", "[v]", "-an",
        "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "20",
        str(out),
    ]
    _run(cmd)
    return out


def _pick_music() -> Optional[str]:
    files = [p for p in MUSIC_DIR.glob("*")
             if p.suffix.lower() in (".mp3", ".m4a", ".aac", ".wav", ".ogg")]
    return str(random.choice(files)) if files else None


def _finalize(segments: List[Path], out_path: str, tmpdir: Path) -> str:
    """동일 규격 세그먼트들을 concat 하고 BGM(또는 무음)을 입혀 최종 릴스로 출력."""
    fps = settings.video_fps

    concat_list = tmpdir / "list.txt"
    concat_list.write_text(
        "".join(f"file '{seg.as_posix()}'\n" for seg in segments),
        encoding="utf-8",
    )
    merged = tmpdir / "merged.mp4"
    _run([
        settings.ffmpeg_path, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(merged),
    ])

    total = probe_duration(str(merged))
    if total < 3:
        print(f"[warn] 영상이 너무 짧습니다({total:.1f}s). 장면/슬라이드 시간을 늘리세요.")

    music = _pick_music()
    if music:
        # 음악이 영상보다 짧아도 끊기지 않도록 반복(loop). -shortest 는 영상 길이에서 종료.
        audio_in = ["-stream_loop", "-1", "-i", music]
        audio_filter = (
            f"[1:a]afade=t=in:st=0:d=1,afade=t=out:st={max(0,total-1.2):.2f}:d=1.2,"
            f"aformat=sample_rates=48000:channel_layouts=stereo[a]"
        )
        amap = ["-map", "0:v:0", "-map", "[a]"]
        extra_filter = ["-filter_complex", audio_filter]
    else:
        audio_in = ["-f", "lavfi", "-t", f"{total:.2f}",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        amap = ["-map", "0:v:0", "-map", "1:a:0"]
        extra_filter = []

    cmd = [
        settings.ffmpeg_path, "-y",
        "-i", str(merged), *audio_in,
        *extra_filter, *amap,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-r", str(fps), "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        out_path,
    ]
    _run(cmd)
    return out_path


_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")


def compose_scene_reel(
    scene_media: List[str],
    subtitles: List[str],
    out_path: Optional[str] = None,
    closing_image: Optional[str] = None,
    price: Optional[str] = None,
) -> str:
    """장면 광고(모델+배경)로 릴스를 만든다. 광고 1개 = 가방 1개.

    scene_media   : 각 컷의 경로. 영상(mp4 등)이면 그대로, 이미지면 Ken-Burns 정지컷으로
                    처리한다(영상 생성 실패 시 합성 장면 이미지로 폴백 가능).
    closing_image : (선택) 마지막에 보여줄 실제 제품 스튜디오 컷 이미지
    """
    media = [m for m in scene_media if m and Path(m).exists()]
    if not media and not closing_image:
        raise ValueError("합성할 장면이 없습니다.")

    font = _font_path()
    out_path = out_path or str(
        OUTPUT_DIR / f"scene_{os.getpid()}_{random.randint(1000,9999)}.mp4")

    subs = list(subtitles) if subtitles else []
    closing_sub = price if price else "지금 만나보세요"

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        segments: List[Path] = []

        for i, m in enumerate(media):
            s = subs[i] if i < len(subs) else None
            if Path(m).suffix.lower() in _VIDEO_EXTS:
                segments.append(_normalize_clip(m, s, tmpdir, len(segments), font))
            else:  # 합성 장면 이미지 폴백
                segments.append(_make_image_segment(
                    m, s, settings.ai_clip_seconds, tmpdir, len(segments), font))

        # 마지막에 실제 제품 컷 + 가격/CTA (선택)
        if closing_image and Path(closing_image).exists():
            segments.append(_make_image_segment(
                closing_image, closing_sub, settings.slide_seconds,
                tmpdir, len(segments), font,
            ))

        if not segments:
            raise ValueError("생성된 세그먼트가 없습니다.")
        return _finalize(segments, out_path, tmpdir)


def compose_reel(
    images: List[str],
    subtitles: List[str],
    out_path: Optional[str] = None,
    ai_clip: Optional[str] = None,
    price: Optional[str] = None,
    max_images: int = 5,
) -> str:
    """릴스 영상을 합성하고 최종 파일 경로를 반환한다."""
    images = [im for im in images if im and Path(im).exists()][:max_images]
    if not images:
        raise ValueError("합성할 제품 이미지가 없습니다.")

    font = _font_path()
    fps = settings.video_fps
    out_path = out_path or str(OUTPUT_DIR / f"reel_{os.getpid()}_{random.randint(1000,9999)}.mp4")

    # 자막 분배: 인트로/슬라이드/가격 순으로 순환
    subs = list(subtitles) if subtitles else []
    if price:
        subs.append(price if price.endswith(("원", "₩")) or "원" in price else f"{price}")

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        segments: List[Path] = []
        sub_i = 0

        # 1) AI 클립 인트로 (있으면)
        if ai_clip and Path(ai_clip).exists():
            s = subs[sub_i] if sub_i < len(subs) else None
            sub_i += 1
            segments.append(_normalize_clip(ai_clip, s, tmpdir, len(segments), font))

        # 2) 제품 이미지 슬라이드들
        for image in images:
            s = subs[sub_i] if sub_i < len(subs) else None
            sub_i += 1
            seg = _make_image_segment(
                image, s, settings.slide_seconds, tmpdir, len(segments), font
            )
            segments.append(seg)

        # 3) concat + BGM → 최종 출력
        return _finalize(segments, out_path, tmpdir)


if __name__ == "__main__":
    import sys
    from . import db

    pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    db.init_db()
    products = db.list_products()
    if not products:
        print("DB에 제품이 없습니다. 먼저 'python -m app.crawler' 를 실행하세요.")
        raise SystemExit(1)
    product = db.get_product(pid) if pid else products[0]
    out = compose_reel(
        images=product["images"],
        subtitles=[product["name"], "데일리로 딱", "지금 만나보세요"],
        price=product.get("price"),
    )
    print("생성됨:", out)
