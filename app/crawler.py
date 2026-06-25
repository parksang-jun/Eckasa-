"""Cafe24(eckasa.com) 제품 크롤러.

흐름:
1) 카테고리 목록 페이지에서 제품(product_no, 이름, 가격, 품절여부, 썸네일) 수집
2) 각 제품 상세 페이지에서 제품 갤러리 이미지(스튜디오 컷) 추가 수집
3) 이미지를 로컬(data/images/<product_no>/)에 내려받고 DB upsert

Cafe24 마크업이 바뀌면 이 파일 상단의 선택자 상수만 고치면 된다.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .config import IMAGES_DIR, settings
from . import db

# ----------------------- Cafe24 선택자 / 패턴 -----------------------
# 목록 페이지의 제품 1건을 감싸는 요소
LIST_ITEM_SELECTOR = "ul.prdList > li, .xans-product-listmain li, .prdList > li"
# 제품 상세 링크 (이 안에서 product_no 추출)
PRODUCT_LINK_SELECTOR = "a[href*='/product/']"
# 제품명
NAME_SELECTOR = ".description .name, .name a, .description strong.name"
# 가격
PRICE_SELECTOR = ".description .xans-record- span, .description li, .price"
# 상세페이지의 제품 대표/추가 이미지 (스튜디오 컷)
DETAIL_IMAGE_SELECTOR = (
    ".xans-product-image img, .keyImg img, .xans-product-addimage img, "
    ".thumbnail img, .bigImage img"
)
# URL 에서 product_no 추출: /product/<name>/<id>/...
PRODUCT_NO_RE = re.compile(r"/product/[^/]+/(\d+)/")
# 품절 표기 (이름에 포함되는 경우가 많음)
SOLDOUT_RE = re.compile(r"품절|sold\s*out", re.IGNORECASE)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )


def _abs(url: str) -> str:
    """`//eckasa.com/...` 또는 상대경로를 절대 https URL 로."""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    return urljoin(settings.eckasa_base_url + "/", url.lstrip("/"))


def _to_big(url: str) -> str:
    """Cafe24 이미지의 small/medium/tiny 버전을 고해상도 big 으로 치환."""
    return re.sub(r"/web/product/(?:tiny|small|medium)/",
                  "/web/product/big/", url)


def _extract_product_no(href: str) -> Optional[int]:
    m = PRODUCT_NO_RE.search(href)
    return int(m.group(1)) if m else None


def _clean_name(name: str) -> str:
    """Cafe24 접근성 라벨('상품명 :', 'Product :' 등)과 공백을 정리한다."""
    name = re.sub(r"^\s*(상품명|product\s*name|name)\s*[:：]\s*", "",
                  name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip()


def _clean_price(price: str) -> str:
    """'판매가 : ₩45,000' 같은 라벨/공백을 정리해 '₩45,000' 만 남긴다."""
    price = re.sub(r"^\s*(판매가|소비자가|가격|price)\s*[:：]\s*", "",
                   price, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", price).strip()


def parse_list_page(html: str) -> List[Dict]:
    """목록 페이지 HTML → 제품 요약 리스트."""
    soup = BeautifulSoup(html, "lxml")
    items: Dict[int, Dict] = {}

    for li in soup.select(LIST_ITEM_SELECTOR):
        link = li.select_one(PRODUCT_LINK_SELECTOR)
        if not link or not link.get("href"):
            continue
        pno = _extract_product_no(link["href"])
        if pno is None:
            continue

        name_el = li.select_one(NAME_SELECTOR)
        name = (name_el.get_text(strip=True) if name_el
                else link.get("title") or link.get_text(strip=True))
        name = _clean_name(name) or f"product-{pno}"

        price_el = li.select_one(PRICE_SELECTOR)
        price = _clean_price(price_el.get_text(strip=True)) if price_el else None

        thumb = None
        img = li.select_one("img")
        if img:
            thumb = img.get("src") or img.get("ec-data-src") or img.get("data-src")

        items.setdefault(pno, {
            "product_no": pno,
            "name": name,
            "price": price,
            "url": _abs(link["href"]),
            "thumb": _to_big(_abs(thumb)) if thumb else None,
            "sold_out": bool(SOLDOUT_RE.search(name)),
        })

    return list(items.values())


def fetch_detail_images(client: httpx.Client, product_url: str,
                        max_images: int = 6) -> List[str]:
    """상세 페이지에서 제품 갤러리 이미지(고해상도) URL 목록."""
    try:
        resp = client.get(product_url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    urls: List[str] = []
    seen = set()
    for img in soup.select(DETAIL_IMAGE_SELECTOR):
        src = img.get("src") or img.get("ec-data-src") or img.get("data-src")
        if not src:
            continue
        full = _to_big(_abs(src))
        # 제품 이미지(/web/product/)만, 로고/아이콘 류 제외
        if "/web/product/" not in full:
            continue
        if full in seen:
            continue
        seen.add(full)
        urls.append(full)
        if len(urls) >= max_images:
            break
    return urls


def download_image(client: httpx.Client, url: str, dest: Path) -> Optional[Path]:
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    ctype = resp.headers.get("content-type", "")
    if "image" not in ctype:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def _image_filename(url: str, index: int) -> str:
    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    return f"{index:02d}{ext}"


def crawl(category_nos: Optional[List[int]] = None,
          max_detail_images: int = 6,
          delay: float = 0.4) -> Tuple[int, int]:
    """전체 크롤 실행. (수집한 제품 수, 내려받은 이미지 수) 반환."""
    db.init_db()
    cats = category_nos or settings.category_list
    if not cats:
        raise ValueError("크롤할 카테고리 번호가 없습니다. .env 의 ECKASA_CATEGORY_NOS 확인.")

    product_count = 0
    image_count = 0

    with _client() as client:
        summaries: Dict[int, Dict] = {}
        for cate_no in cats:
            list_url = f"{settings.eckasa_base_url}/product/list.html?cate_no={cate_no}"
            try:
                resp = client.get(list_url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                print(f"[warn] 목록 페이지 실패 cate_no={cate_no}: {e}")
                continue
            for p in parse_list_page(resp.text):
                summaries.setdefault(p["product_no"], p)
            time.sleep(delay)

        for pno, p in summaries.items():
            images: List[str] = []
            # 1) 상세 갤러리 이미지
            gallery = fetch_detail_images(client, p["url"], max_detail_images)
            # 2) 없으면 목록 썸네일이라도
            candidate_urls = gallery or ([p["thumb"]] if p["thumb"] else [])

            dest_dir = IMAGES_DIR / str(pno)
            for i, url in enumerate(candidate_urls):
                dest = dest_dir / _image_filename(url, i)
                saved = download_image(client, url, dest)
                if saved:
                    images.append(str(saved))
                    image_count += 1
                time.sleep(delay)

            db.upsert_product(
                product_id=pno,
                name=p["name"],
                price=p["price"],
                url=p["url"],
                images=images,
                sold_out=p["sold_out"],
            )
            product_count += 1
            print(f"[ok] #{pno} {p['name']} - 이미지 {len(images)}장"
                  f"{' (품절)' if p['sold_out'] else ''}")

    return product_count, image_count


if __name__ == "__main__":
    pc, ic = crawl()
    print(f"\n완료: 제품 {pc}건, 이미지 {ic}장 수집")
