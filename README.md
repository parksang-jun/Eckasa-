# ECKASA 가방 → AI 릴스 광고 자동 제작·게시

Eckasa(엑카사, `eckasa.com`)의 가방 제품을 자동으로 가져와 **세로형(9:16) AI 릴스 광고 영상**을
만들고 **인스타그램에 자동 게시**하는 프로그램입니다. 웹 대시보드로 제품을 고르고, 영상 미리보기,
즉시 게시, 정기 자동 게시(스케줄)를 관리합니다.

```
크롤링 → 광고 카피(Claude) → AI 클립(fal.ai) + 제품 이미지 → ffmpeg 합성(자막+음악)
       → 공개 URL 업로드(R2/S3) → Instagram Graph API 게시   ← 웹 대시보드 + 스케줄러
```

---

## 1. 빠르게 시작하기

### (1) 사전 설치
- **Python 3.11 이상**
- **ffmpeg / ffprobe** (영상 합성에 필수)
  - Windows: <https://www.gyan.dev/ffmpeg/builds/> 에서 받아 압축 해제 후, `bin` 폴더를 PATH 에
    추가하거나 `.env` 의 `FFMPEG_PATH`/`FFPROBE_PATH` 에 전체 경로를 지정.
  - 설치 확인: `ffmpeg -version`

### (2) 의존성 설치
```powershell
cd "C:\Users\USER\Downloads\ECKASA 광고 만들기"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### (3) 환경설정
```powershell
copy .env.example .env
```
그런 다음 `.env` 를 열어 값을 채웁니다. (아래 **2. 외부 연동 준비** 참고)
처음엔 키 없이도 **크롤링 + 영상 생성(슬라이드쇼)** 까지 동작합니다.

### (4) 실행
```powershell
python run.py
```
브라우저에서 <http://127.0.0.1:8000> 접속 → **제품 새로 크롤링** → 제품 카드의 **영상 생성**.

---

## 2. 외부 연동 준비 (단계별)

> 코드 외에 직접 발급해야 하는 키/계정입니다. 일부는 승인에 시간이 걸립니다.

### A. 광고 카피 (선택, 권장) — Anthropic
- <https://console.anthropic.com> 에서 API 키 발급 → `.env` 의 `ANTHROPIC_API_KEY`.
- 미설정 시 규칙 기반 기본 카피로 동작합니다.

### B. 장면 광고 (모델 + 이국적 배경) — ⭐핵심 기능

#### ✅ 무료로 만들기 (권장) — Google AI Studio (Gemini)
- <https://aistudio.google.com/apikey> 에서 **무료 API 키** 발급 (**신용카드·결제 등록 불필요**).
- `.env` 의 `GEMINI_API_KEY=` 에 입력. 끝!
- 하루 약 **500장 무료**로 가방+모델+이국적 배경 사진 생성.
- 영상화는 유료라, 무료 모드에서는 AI 장면 사진에 **ffmpeg 줌/패닝 모션**을 입혀 릴스로 만듭니다.
- 즉, **무료 키 1개로 모델·배경 릴스 광고가 나옵니다.**

#### (선택) 유료 업그레이드 — fal.ai
- <https://fal.ai> 키 → `.env` 의 `FAL_KEY`.
- `fal-ai/nano-banana/edit`(이미지 ≈ $0.039) + Kling(이미지→**실제 움직이는 영상**, 초당 과금).
- `IMAGE_PROVIDER` 로 `auto`(무료 Gemini 우선)/`gemini`/`fal` 선택. 컷 수는 `SCENE_COUNT`.

> 키가 하나도 없으면 장면 광고는 비활성이고, 무료 **이미지 슬라이드쇼**만 가능합니다.

### C. 공개 영상 호스팅 (게시하려면 필수) — Cloudflare R2 권장
인스타그램은 영상을 **공개 URL** 에서 가져갑니다. 그래서 결과 영상을 공개 위치에 올려야 합니다.
1. Cloudflare 대시보드 → R2 → 버킷 생성(예: `eckasa-reels`).
2. **Public access** 를 켜고 연결된 공개 도메인 확보(또는 커스텀 도메인).
3. R2 API 토큰(Access Key / Secret) 발급.
4. `.env`:
   ```
   STORAGE_PROVIDER=r2
   S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
   S3_ACCESS_KEY_ID=...
   S3_SECRET_ACCESS_KEY=...
   S3_BUCKET=eckasa-reels
   S3_PUBLIC_BASE_URL=https://<공개도메인>
   ```
- (대안) AWS S3 도 동일하게 `STORAGE_PROVIDER=s3` 로 사용 가능.
- (개발용) `STORAGE_PROVIDER=local` + `cloudflared tunnel` 로 `output` 폴더를 임시 공개하고
  `LOCAL_PUBLIC_BASE_URL` 에 그 주소를 넣어도 됩니다.

### D. 인스타그램 자동 게시 (필수) — Meta Graph API
1. **인스타그램을 '비즈니스' 계정**으로 전환하고 **페이스북 페이지에 연결**.
   (크리에이터 계정은 콘텐츠 게시 API 불가)
2. <https://developers.facebook.com> 에서 앱 생성.
3. 제품: **Instagram** 추가. 권한: `instagram_business_basic`,
   `instagram_business_content_publish`.
   - 실제 운영(다른 계정/공개)에는 **App Review 승인**이 필요합니다.
   - 승인 전에도 **본인(개발자/테스터) 계정**으로는 게시 테스트가 가능합니다 → 이걸로 먼저 완성.
4. **장수명 액세스 토큰(long-lived token)** 발급. (만료 전 갱신 필요)
5. 본인의 **IG User ID** 확인.
6. `.env`:
   ```
   IG_USER_ID=...
   IG_ACCESS_TOKEN=...
   ```

### E. 배경음악
- `assets/music/` 폴더에 **저작권 문제 없는** 음원(.mp3 등)을 넣으세요.
- 인스타 음악 라이브러리는 API 로 못 쓰므로 영상에 직접 입힙니다(자동).

---

## 3. 대시보드 사용법

- **제품 새로 크롤링**: `.env` 의 `ECKASA_CATEGORY_NOS` 카테고리에서 제품·이미지 수집.
- 제품 카드 **🎬 장면 광고 만들기**: **장면 광고 스튜디오**로 이동(아래 3-1).
- 제품 카드 **기본 슬라이드 / 슬라이드+게시**: 무료 슬라이드쇼 광고(미리보기/게시).
- **작업 현황**: 각 작업의 단계/오류/미리보기.
- **게시 이력**: 게시된 릴스의 permalink.
- **자동 게시 스케줄**: `SCHEDULE_CRON` 주기로 제품을 **순환**하며 장면 광고 자동 게시(시작/중지).

### 3-0. 말하는 시네마틱 영상 (Veo 3.1) 🎬 — 핵심

실제 가방을 든 모델이 **움직이며 한국어로 가방을 설명하는 영화 같은 영상**(립싱크·사운드 포함).
스튜디오 페이지 상단 보라색 **"🎬 말하는 시네마틱 영상"** 카드:
1. **장면 묘사**(배경·모델·분위기) + **대사**(모델이 말할 한국어) 입력.
2. **길이**(4/6/8초)·**화질**(720p/1080p) 선택 → **말하는 영상 생성**.
3. 처리: nano-banana로 가방 보존 장면 생성 → Veo 3.1이 그 장면을 시작 프레임으로
   말하는 시네마틱 영상 생성(`fal-ai/veo3.1/fast/image-to-video`, `generate_audio=true`).
- 비용: 음성 포함 약 **$0.4/초** (8초 ≈ $3). FAL_KEY 필요.
- 더 길게: 여러 8초 클립을 만들어 이어붙이면 15초+ 광고 가능.

### 3-1. 장면 광고 스튜디오 (모델 + 이국적 배경) ⭐

저비용 옵션(사진+모션, 말소리 없음). **광고 1개 = 가방 1개** — 대표 이미지 1장만 씁니다.

1. 제품의 **🎬 장면 광고 만들기** 클릭 → 스튜디오 페이지.
2. **배경 선택**: 유럽 거리(파리/토스카나) · 산토리니 · 발리 해변 · 모로코 마켓.
3. **모델 선택**: 서양 여성 · 한국/아시아 여성 · 남성/유니섹스 · 모델 없이 배경만.
4. **미리 생성**(게시 X) 또는 **생성 + 인스타 게시**.
5. 처리 흐름: 카피 생성 → `nano-banana`로 가방을 유지한 채 모델·배경 합성(여러 컷)
   → 각 컷을 Kling으로 영상화 → 마지막에 실제 제품 컷 + 가격 → 9:16 릴스 합성.
6. 결과는 같은 페이지 **최근 작업**에서 새로고침해 확인.

> 배경/모델 프리셋은 `app/presets.py` 에서 추가·수정할 수 있습니다.

#### 🆓 완전 무료로 만들기 (결제 없이, 반자동)

API 이미지 자동생성은 결제가 필요하지만, **브라우저 무료 도구로 만든 장면 이미지를 올리면**
프로그램이 릴스로 합성합니다. 스튜디오 페이지 하단 **"🆓 완전 무료로 만들기"** 섹션:

1. 배경·모델을 고르고 **프롬프트 갱신** → 컷별 **복붙용 프롬프트**가 표시됨.
2. **제품 이미지 다운로드** 링크로 가방 사진 저장.
3. <https://aistudio.google.com> (무료) 에서 모델을 **Nano Banana / Gemini 2.5 Flash Image**로
   두고, 가방 사진 업로드 + 프롬프트 붙여넣기 → 컷마다 이미지 생성·다운로드.
4. 만든 이미지들을 **업로드** → 줌/패닝 모션 + 자막 + 음악 + 실제 제품 컷으로 릴스 완성(0원).

> 직접 찍은 연출 사진이나 다른 무료 이미지 도구 결과물을 올려도 됩니다.

---

## 3-2. 나만 쓰는 공개 링크 (비공개 앱)

내 PC의 앱을 인터넷 링크로 열되, **로그인한 나만** 접속하게 합니다.

1. **로그인 설정**: `.env` 의 `APP_USERNAME`/`APP_PASSWORD` 를 원하는 값으로. (비어 있으면 잠금 해제)
2. **실행**: `공유앱_실행.bat` 더블클릭 → 서버 + 공개 링크(터널)가 함께 켜집니다.
3. 검은 'cloudflared' 창에 뜨는 **`https://....trycloudflare.com`** 이 내 앱 링크입니다.
   접속하면 아이디/비밀번호를 묻고, 맞으면 스튜디오가 열립니다.

주의:
- 내 PC가 켜져 있고 두 창(서버·터널)이 떠 있는 동안만 링크가 작동합니다.
- 무료 quick 터널은 **켤 때마다 주소가 바뀝니다.** 고정 주소가 필요하면 Cloudflare 계정 +
  named tunnel(또는 클라우드 배포)이 필요합니다.

## 4. 명령줄(터미널)로 단계별 실행/검증

```powershell
# 1) 크롤링 → DB 적재
python -m app.crawler

# 2) 영상 합성만 (AI/인스타 없이도 동작) — output/ 에 mp4 생성
python -m app.composer            # 첫 제품으로
python -m app.composer 100        # 특정 제품(product_no=100)

# 3) 카피 생성 테스트
python -m app.copywriter "스퀘어 보냉백"

# 4) AI 클립 테스트 (FAL_KEY 필요)
python -m app.ai_video data\images\100\00.jpg

# 5) 공개 업로드 테스트
python -m app.uploader output\reel_xxx.mp4

# 6) 인스타 게시 테스트 (공개 URL 필요)
python -m app.instagram https://<공개도메인>/reel_xxx.mp4 "테스트 캡션"
```

검증 포인트:
- 합성 결과가 **1080×1920 / 5~90초 / H.264 / +faststart** 인지 `ffprobe output\reel_xxx.mp4` 로 확인.
- 게시 후 반환된 **permalink** 로 실제 릴스 노출 확인.

---

## 5. 폴더 구조

```
app/
  config.py      설정(.env) 로딩
  db.py          SQLite (products/jobs/posts)
  crawler.py     Cafe24 크롤러
  copywriter.py  Claude 광고 카피
  ai_video.py    fal.ai 이미지→영상 클립
  composer.py    ffmpeg 9:16 합성 (자막/음악)
  uploader.py    공개 스토리지 업로드
  instagram.py   Graph API 릴스 게시
  pipeline.py    제품 1건 전체 파이프라인
  scheduler.py   정기 자동 게시
  main.py        FastAPI 대시보드
  templates/     대시보드 HTML
assets/music/    BGM (직접 추가)
data/            DB + 다운로드 이미지 (자동 생성)
output/          생성된 릴스 mp4 (자동 생성)
run.py           대시보드 실행
.env.example     환경설정 예시
```

---

## 6. 주의 / 한계

- **App Review**: 인스타 콘텐츠 게시 권한 승인 전에는 본인 테스트 계정만 게시 가능.
- **AI 영상 왜곡**: 가방 형태가 변형될 수 있어 기본값은 안전모드(슬라이드쇼 위주).
- **비용**: AI 영상은 초당 과금 / Anthropic 도 토큰 과금. 미설정 시 무료 경로로 동작.
- **크롤링 안정성**: Cafe24 마크업이 바뀌면 `app/crawler.py` 상단의 선택자 상수만 조정.
- **음악 저작권**: 라이선스가 명확한 음원만 사용.
- **게시 한도**: 인스타 24시간 100건. (가드 내장)
```
