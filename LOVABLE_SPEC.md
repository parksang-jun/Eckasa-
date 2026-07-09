# ECKASA 광고 스튜디오 — Lovable 버전 설계서

현재 Python/ffmpeg 프로그램을 **Lovable(React + Tailwind + Supabase)** 로 재설계한 문서입니다.
목적: **PC를 꺼도 24시간 작동하는 고정 주소의 웹앱**.

---

## 왜 "이식"이 아니라 "재설계"인가

Lovable 은 Python 도 ffmpeg 도 실행할 수 없습니다. 따라서 영상 합성(자막·음악·이어붙이기·
Ken-Burns)은 **클라우드 영상 렌더링 API** 로 대체합니다.

| 기능 | 현재(로컬 Python) | Lovable 버전 |
|---|---|---|
| 제품 크롤링 | `crawler.py` (httpx+bs4) | Supabase **엣지 함수** (fetch + HTML 파싱) |
| 장면 이미지(가방 보존) | fal `nano-banana/edit` | 동일 (엣지 함수에서 호출) |
| 말하는 영상 | fal `veo3.1/fast/image-to-video` | 동일 (엣지 함수에서 호출) |
| **영상 합성** | **ffmpeg** | **Shotstack**(또는 Creatomate) REST API |
| 저장 | 로컬 `output/` | **Supabase Storage** (공개 버킷) |
| 로그인 | HTTP Basic | **Supabase Auth** (내 계정만) |
| 공개 링크 | cloudflared 터널 | Lovable 호스팅 (고정 주소, 24시간) |

> 장점: 항상 켜져 있고 주소가 안 바뀜. 아이폰에서 늘 같은 주소로 접속.
> 주의: 렌더링 1건당 소액 비용이 추가로 듭니다(영상 API).

---

## 아키텍처

```
[React UI]  →  [Supabase Edge Functions]  →  fal.ai (nano-banana / Veo)
     │                    │                →  Shotstack (영상 합성)
     │                    │                →  Instagram Graph API (게시)
     └── Supabase DB(products/jobs/posts) + Storage(완성 영상, 공개 URL)
```

### 핵심 광고 원칙 (반드시 유지)
1. **광고 1개 = 가방 1개** (색상 변형 섞지 않음).
2. **브랜드 정확 하이브리드** — 로고·사이즈가 정확해야 하므로 **실제 제품 사진이 메인**,
   AI는 분위기 인트로로만 짧게. (AI 영상은 작은 로고를 뭉갬)
3. 출력은 항상 **9:16 (1080×1920)**, 5~90초, H.264 + AAC.

---

## DB 스키마 (Supabase / Postgres)

```sql
products (
  id bigint primary key,        -- Cafe24 product_no
  name text not null,
  price text,
  url text,
  images jsonb not null,        -- 원본 공개 이미지 URL 배열 (다운로드 불필요)
  sold_out boolean default false,
  updated_at timestamptz default now()
);

jobs (
  id bigserial primary key,
  product_id bigint references products(id),
  mode text not null,           -- hybrid | talking
  status text default 'pending',-- pending|scene|video|render|publish|done|error|canceled
  stage_msg text, caption text, subtitles jsonb,
  video_url text, error text,
  created_at timestamptz default now()
);

posts (
  id bigserial primary key,
  job_id bigint references jobs(id),
  product_id bigint references products(id),
  ig_media_id text, permalink text,
  created_at timestamptz default now()
);
```
RLS: 로그인한 본인만 read/write.

---

## 엣지 함수 (Deno)

| 함수 | 하는 일 |
|---|---|
| `crawl-products` | `https://eckasa.com/product/list.html?cate_no=45` 목록 + 각 상세 페이지에서 `/web/product/big/...` 이미지 URL 수집 → `products` upsert. (라벨 `상품명:`/`판매가:` 제거) |
| `generate-scene` | fal `fal-ai/nano-banana/edit` 호출. `image_urls=[제품 이미지 URL]`, `prompt`(가방 형태·로고 유지 지시 포함), `aspect_ratio:"9:16"` → 장면 이미지 URL |
| `generate-video` | fal `fal-ai/veo3.1/fast/image-to-video`. `image_url`, `prompt`(한국어 대사 포함), `duration:"8s"`, `resolution:"720p"`, `aspect_ratio:"9:16"`, `generate_audio:true` → 말하는 영상 URL |
| `render-ad` | **Shotstack** 타임라인 JSON 생성 → 렌더 → 완성 mp4 URL → Supabase Storage 저장 |
| `publish-instagram` | Graph API 3단계: `POST /{ig-user-id}/media`(media_type=REELS, video_url) → `status_code=FINISHED` 폴링 → `POST /{ig-user-id}/media_publish` |

### `render-ad` 타임라인 구성 (브랜드 정확 하이브리드)
1. (선택) AI 인트로: 장면 이미지 또는 Veo 클립 — 짧게
2. **실제 제품 사진들** 각각 2.5~5초, Ken-Burns(zoom/pan) + **장점 자막** 오버레이
3. 마무리: 실제 제품 컷 + 가격/CTA
4. 배경음악 트랙 + 페이드

> Shotstack 은 `timeline.tracks[].clips[]` 에 `image`/`video`/`title` 애셋과
> `effect: "zoomIn"`, `transition`, `soundtrack` 을 지정하면 위 구성을 그대로 만듭니다.

---

## 필요한 시크릿 (Supabase Edge Function Secrets)

| 이름 | 용도 | 필수 |
|---|---|---|
| `FAL_KEY` | nano-banana(장면), Veo(말하는 영상) | ✅ |
| `SHOTSTACK_API_KEY` | 영상 합성 렌더링 | ✅ |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | 인스타 자동 게시 | 게시할 때 |
| `ANTHROPIC_API_KEY` 또는 `GEMINI_API_KEY` | 광고 카피 생성 | 선택 |

> ⚠️ 시크릿은 **엣지 함수 시크릿**에만 저장. 프론트엔드 코드/환경변수에 넣지 말 것.

---

## 화면 (페이지)

1. **제품 목록** — 크롤링 새로고침 버튼, 제품 카드(썸네일/이름/가격)
2. **스튜디오 `/studio/:id`**
   - 🏆 **브랜드 정확 광고(하이브리드)** — AI 인트로(없음/사진/말하는영상) · 장면 묘사 · **장점 자막(한 줄에 하나)** · 생성/생성+게시
   - 🎬 **말하는 시네마틱 영상** — 장면 묘사 · 대사 · 길이(8/16/24/30초) · 화질 · 생성/생성+게시
3. **작업 현황** — 단계 표시, 미리보기, **작업 취소** 버튼
4. **게시 이력** — permalink 링크
5. **설정** — 기본 프롬프트/자막/스케줄

---

## Lovable 에 붙여넣을 초기 프롬프트

아래 전체를 복사해 <https://lovable.dev> 새 프로젝트의 첫 메시지로 붙여넣으세요.

```
ECKASA(가방 브랜드)의 인스타그램 릴스 광고를 자동 제작하는 비공개 웹앱을 만들어줘.

[스택] React + Tailwind + shadcn/ui + Supabase (Auth, Postgres, Storage, Edge Functions)

[로그인] Supabase Auth 이메일 로그인. 로그인한 나만 모든 페이지 접근 가능(RLS 적용).

[DB 테이블]
- products(id bigint PK=Cafe24 product_no, name, price, url, images jsonb=이미지 URL 배열, sold_out bool, updated_at)
- jobs(id bigserial, product_id FK, mode text, status text, stage_msg, caption, subtitles jsonb, video_url, error, created_at)
- posts(id bigserial, job_id FK, product_id FK, ig_media_id, permalink, created_at)

[엣지 함수]
1) crawl-products: https://eckasa.com/product/list.html?cate_no=45 를 fetch 해서 제품 목록 파싱.
   상세 링크 패턴 /product/<name>/<id>/ 에서 id 추출. 상세 페이지에서 /web/product/ 이미지 URL 수집하고
   small|medium|tiny 를 big 으로 치환. 이름 앞의 "상품명:" 과 가격 앞의 "판매가:" 라벨 제거. products 에 upsert.
2) generate-scene: fal.ai 의 fal-ai/nano-banana/edit 호출.
   body: { prompt, image_urls: [제품 이미지 URL], aspect_ratio: "9:16", num_images: 1 }
   prompt 끝에 반드시: "Keep the bag's exact shape, color, material, straps, logo and design
   completely unchanged and identical to the reference image. Photorealistic, vertical 9:16."
3) generate-video: fal.ai 의 fal-ai/veo3.1/fast/image-to-video 호출.
   body: { prompt, image_url, duration: "8s", resolution: "720p", aspect_ratio: "9:16", generate_audio: true }
   prompt 에 한국어 대사를 이렇게 포함: The model looks at the camera and says in Korean: "<대사>"
4) render-ad: Shotstack API 로 최종 9:16(1080x1920) 영상 합성.
   타임라인: (선택)AI 인트로 클립/이미지 → 실제 제품 사진들 각 2.5~5초 zoomIn 효과 + 하단 자막 오버레이
   → 마지막 실제 제품 컷 + 가격 → 배경음악 트랙(페이드 인/아웃). 결과 mp4 를 Supabase Storage 공개 버킷에 저장.
5) publish-instagram: Graph API 3단계 (POST /{ig-user-id}/media 로 media_type=REELS + 공개 video_url →
   status_code 가 FINISHED 될 때까지 폴링 → POST /{ig-user-id}/media_publish). 24시간 100건 제한 가드.

시크릿은 엣지 함수 시크릿으로: FAL_KEY, SHOTSTACK_API_KEY, IG_USER_ID, IG_ACCESS_TOKEN.
프론트엔드에는 절대 노출하지 말 것.

[페이지]
- /            제품 목록 + "제품 새로 크롤링" 버튼
- /studio/:id  두 가지 광고 모드
    (A) 브랜드 정확 광고(하이브리드) — 기본/추천:
        AI 인트로 선택(없음 | 사진 1컷 | 말하는 영상), 장면 묘사 입력,
        "장점 자막"을 한 줄에 하나씩 입력(예: 방수 완벽 / 꼼꼼한 디테일 / 데일리로 딱),
        [생성] [생성+게시]
    (B) 말하는 시네마틱 영상: 장면 묘사, 대사, 길이(8/16/24/30초), 화질(720p/1080p), [생성] [생성+게시]
- /jobs        작업 현황(단계 표시, 영상 미리보기, 작업 취소 버튼)
- /posts       게시 이력(permalink)

[매우 중요한 규칙]
1. 광고 1개 = 가방 1개. 한 제품의 대표 이미지만 쓰고 색상 변형을 섞지 마라.
2. 브랜드 정확성: 로고와 사이즈가 정확해야 하므로 **실제 제품 사진이 광고의 메인**이고,
   AI 생성 장면은 짧은 분위기 인트로로만 쓴다. (AI 영상은 작은 로고를 뭉갠다)
3. 출력은 항상 세로 9:16, 인스타 릴스 규격(H.264 + AAC, 5~90초).
4. 30초 영상은 Veo가 한 번에 8초까지만 되므로 8초 클립을 이어붙여 만든다.

먼저 로그인 + 제품 목록 + 크롤링 엣지 함수까지 만들고 보여줘.
```

---

## 진행 순서 추천

1. 위 프롬프트로 프로젝트 생성 → **로그인 + 제품 목록 + 크롤링**까지 확인
2. `generate-scene` → 장면 이미지 1장 확인
3. `render-ad`(Shotstack) → **브랜드 정확 하이브리드** 광고 완성 (여기까지가 핵심)
4. `generate-video`(Veo) → 말하는 영상 모드 추가
5. `publish-instagram` → 자동 게시

> 3번까지만 해도 "실제 제품 사진 메인 + 자막 + 음악" 광고가 24시간 자동으로 나옵니다.
