# -*- coding: utf-8 -*-
"""
에카사 자동운영 서버
- 판매 사이트를 등록해 두면, 정해진 주기마다 AI 에이전트가 자동으로 운영 사이클을 수행합니다.
- 사이트 페이지 점검(접속·품절·가격 이상), 문의 답변, 재고 점검, 리포트 작성.
- 사람 확인이 필요한 일은 '승인·알림함'에 쌓입니다.
- 실행: python server.py  (또는 에카사-자동운영-시작.bat 더블클릭)
- 외부로 자동 전송하는 것은 없습니다. 모든 결과는 이 프로그램 안에 저장됩니다.
표준 라이브러리만 사용 (별도 설치 불필요).
"""
import json, os, re, sys, threading, time, html, urllib.request, urllib.error, webbrowser
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
STORE_PATH = os.path.join(DATA_DIR, "store.json")
PORT = 8930
LOCK = threading.RLock()

SEED_PRODUCTS = [
    {"id": "P1", "name": "싱글 보냉백", "nameEn": "Single Cooler Bag", "price": 41000, "weight": 350, "stock": 50, "safe": 10},
    {"id": "P2", "name": "데일리 보틀백(보냉백)", "nameEn": "Daily Bottle Cooler Bag", "price": 38000, "weight": 250, "stock": 50, "safe": 10},
    {"id": "P3", "name": "스팽글 토트백", "nameEn": "Sequin Tote Bag", "price": 41000, "weight": 300, "stock": 50, "safe": 10},
    {"id": "P4", "name": "에카사 트래블 파우치", "nameEn": "Travel Pouch", "price": 19000, "weight": 120, "stock": 50, "safe": 10},
    {"id": "P5", "name": "컬러 파우치", "nameEn": "Color Pouch", "price": 15000, "weight": 80, "stock": 50, "safe": 10},
    {"id": "P6", "name": "스트랩 파우치", "nameEn": "Strap Pouch", "price": 19000, "weight": 100, "stock": 50, "safe": 10},
    {"id": "P7", "name": "스퀘어 보냉백", "nameEn": "Square Cooler Bag", "price": 45000, "weight": 400, "stock": 50, "safe": 10},
    {"id": "P8", "name": "원형 보냉백", "nameEn": "Round Cooler Bag", "price": 45000, "weight": 380, "stock": 50, "safe": 10},
    {"id": "P9", "name": "토바 보냉백", "nameEn": "Toba Cooler Bag", "price": 53000, "weight": 450, "stock": 50, "safe": 10},
    {"id": "P10", "name": "모노백", "nameEn": "Mono Bag", "price": 41000, "weight": 320, "stock": 50, "safe": 10},
    {"id": "P11", "name": "토바백", "nameEn": "Toba Bag", "price": 33000, "weight": 300, "stock": 50, "safe": 10},
    {"id": "P12", "name": "노트북 파우치 16인치", "nameEn": "Laptop Pouch 16 inch", "price": 39000, "weight": 350, "stock": 50, "safe": 10},
    {"id": "P13", "name": "피크닉 매트", "nameEn": "Picnic Mat", "price": 29000, "weight": 500, "stock": 50, "safe": 10},
    {"id": "P14", "name": "플레이 스트랩", "nameEn": "Play Strap", "price": 5000, "weight": 50, "stock": 50, "safe": 10},
]

DEFAULT_STORE = {
    "settings": {
        "apiKey": "", "intervalMin": 60, "autoRun": True,
        "policy": "기본 마진 25%. 주문 후 2영업일 내 발송. 일본은 K-Packet 기본, 고가상품 EMS. "
                  "반품은 수령 7일 이내(왕복 배송비 고객 부담), 불량은 무료 교환. 문의 답변은 정중하고 간결하게.",
        "fx": {"JPY": 9.3, "CNY": 190, "USD": 1380},
        "seller": {"name": "", "phone": "", "addr": ""},
    },
    "sites": [], "products": SEED_PRODUCTS,
    "orders": [], "inquiries": [], "listings": [], "marketing": [], "reports": [], "alerts": [],
    "logs": [], "lastRun": None, "nextRun": None, "running": False, "cycleCount": 0,
}

# ---------------- 저장소 ----------------

def load_store():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                s = json.load(f)
            for k, v in DEFAULT_STORE.items():
                s.setdefault(k, v if not isinstance(v, (dict, list)) else json.loads(json.dumps(v)))
            return s
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_STORE))

STORE = load_store()

def save_store():
    with LOCK:
        STORE["logs"] = STORE["logs"][-400:]
        tmp = STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(STORE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STORE_PATH)

def log(kind, text):
    with LOCK:
        STORE["logs"].append({"ts": datetime.now().strftime("%m-%d %H:%M:%S"), "kind": kind, "text": str(text)[:2000]})
    save_store()
    print(f"[{kind}] {str(text)[:160]}")

def gen_id(prefix):
    return prefix + format(int(time.time() * 1000), "x").upper() + str(int(time.time() * 1000000) % 97)

def today():
    return datetime.now().strftime("%Y-%m-%d")

# ---------------- 유틸 ----------------

def product_by_id(pid):
    return next((p for p in STORE["products"] if p["id"] == pid), None)

def listing_of(pid, country):
    return next((l for l in STORE["listings"] if l["productId"] == pid and l["country"] == country), None)

def jpcn_orders():
    return [o for o in STORE["orders"]]

def order_total(o):
    return sum(it["qty"] * it["unitPrice"] for it in o.get("items", []))

def order_total_krw(o):
    fx = STORE["settings"]["fx"].get(o.get("currency", "KRW"), 1)
    return round(order_total(o) * fx)

MARKET_FEES = {"JP": {"qoo10": 10, "amazonjp": 15, "rakuten": 10}, "CN": {"taobao": 8, "red": 5, "douyin": 5}}
CURRENCY = {"JP": "JPY", "CN": "CNY"}

def calc_price_for(pid, country, market_key=None, margin_pct=None):
    p = product_by_id(pid)
    if not p:
        return {"error": "제품 없음: " + str(pid)}
    fees = MARKET_FEES.get(country, {"generic": 10})
    fee = fees.get(market_key or "", list(fees.values())[0]) / 100.0
    m = re.search(r"마진\s*(\d+)", STORE["settings"]["policy"])
    margin = (margin_pct if margin_pct is not None else (float(m.group(1)) if m else 25)) / 100.0
    ship = (10000 if p["weight"] <= 450 else 13000) if country == "JP" else (18000 if p["weight"] <= 450 else 22000)
    cost = round(p["price"] * 0.5)
    denom = 1 - fee - 0.03 - margin
    if denom <= 0.05:
        return {"error": "마진+수수료 과다"}
    cur = CURRENCY.get(country, "USD")
    fx = STORE["settings"]["fx"].get(cur, 1380)
    local = (cost + ship) / denom / fx
    local = (int(local // 100) * 100 + 90) if country == "JP" else round(local)
    profit = round(local * fx * (1 - fee - 0.03) - (cost + ship))
    return {"product": p["name"], "country": country, "currency": cur, "recommendedPrice": local,
            "costKRW": cost, "shipKRW": ship, "feePct": fee * 100, "marginPct": margin * 100,
            "expectedProfitKRW": profit}

# ---------------- 판매 사이트 페이지 읽기 ----------------

def fetch_page_text(url, max_chars=12000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EckasaAutoOps/1.0",
        "Accept-Language": "ko,ja,zh-CN,en"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(400_000)
        status = r.status
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return status, text[:max_chars]

# ---------------- Anthropic API ----------------

API_URL = "https://api.anthropic.com/v1/messages"

def anthropic_call(system, messages, tools=None, max_tokens=4096):
    key = STORE["settings"]["apiKey"]
    if not key:
        raise RuntimeError("NO_KEY")
    body = {"model": "claude-opus-4-8", "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(API_URL, method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            err = ""
        if e.code == 401:
            raise RuntimeError("API 키가 올바르지 않습니다.")
        if e.code == 429:
            raise RuntimeError("요청 한도 초과 — 다음 사이클에 재시도합니다.")
        raise RuntimeError(f"API 오류 {e.code}: {err[:200]}")

# ---------------- 에이전트 도구 ----------------

AGENT_TOOLS = [
    {"name": "get_overview", "description": "상점 현황 요약(재고부족·대기문의·발송대기·등록 사이트 목록). 사이클 시작 시 먼저 호출.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_site_page", "description": "등록된 판매 사이트의 페이지를 실제로 접속해 텍스트를 읽어온다. 접속 상태와 본문을 반환. 사이트 점검에 사용.",
     "input_schema": {"type": "object", "properties": {"siteId": {"type": "string"}}, "required": ["siteId"]}},
    {"name": "report_site_status", "description": "사이트 점검 결과를 기록한다(정상/이상). 이상이면 무엇이 문제인지 명시.",
     "input_schema": {"type": "object", "properties": {
         "siteId": {"type": "string"}, "status": {"type": "string", "enum": ["정상", "주의", "이상"]},
         "note": {"type": "string"}}, "required": ["siteId", "status", "note"]}},
    {"name": "get_products", "description": "전체 제품(가격·무게·재고·리스팅 유무) 목록.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_orders", "description": "주문 목록.",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string"}}, "required": []}},
    {"name": "get_inquiries", "description": "고객 문의 목록.",
     "input_schema": {"type": "object", "properties": {"only_pending": {"type": "boolean"}}, "required": []}},
    {"name": "calc_price", "description": "제품의 국가별 적정 판매가 계산(수수료·배송비·마진 반영).",
     "input_schema": {"type": "object", "properties": {
         "productId": {"type": "string"}, "country": {"type": "string", "enum": ["JP", "CN"]},
         "marketKey": {"type": "string"}, "marginPct": {"type": "number"}}, "required": ["productId", "country"]}},
    {"name": "save_listing", "description": "제품 리스팅(현지어 상품명/설명/키워드/가격) 저장. 반드시 해당 국가 언어로.",
     "input_schema": {"type": "object", "properties": {
         "productId": {"type": "string"}, "country": {"type": "string", "enum": ["JP", "CN"]},
         "title": {"type": "string"}, "desc": {"type": "string"}, "keywords": {"type": "string"},
         "price": {"type": "number"}, "status": {"type": "string", "enum": ["초안", "게시중", "중지"]}},
      "required": ["productId", "country", "title", "desc", "price"]}},
    {"name": "answer_inquiry", "description": "문의 답변 저장. reply=고객 언어, replyKo=한국어 번역.",
     "input_schema": {"type": "object", "properties": {
         "inquiryId": {"type": "string"}, "reply": {"type": "string"}, "replyKo": {"type": "string"}},
      "required": ["inquiryId", "reply", "replyKo"]}},
    {"name": "update_order", "description": "주문 결제/배송 상태 변경. 발송완료 시 재고 자동 차감.",
     "input_schema": {"type": "object", "properties": {
         "orderId": {"type": "string"}, "payStatus": {"type": "string"}, "shipStatus": {"type": "string"},
         "carrier": {"type": "string"}, "tracking": {"type": "string"}}, "required": ["orderId"]}},
    {"name": "update_stock", "description": "재고 조정(+입고/-차감). 사유 필수.",
     "input_schema": {"type": "object", "properties": {
         "productId": {"type": "string"}, "delta": {"type": "number"}, "reason": {"type": "string"}},
      "required": ["productId", "delta", "reason"]}},
    {"name": "add_alert", "description": "판매자(사람)의 확인·조치가 필요한 일을 승인·알림함에 등록한다. 자동으로 처리하면 안 되는 일(가격 인상 결정, 사이트 이상, 환불 승인 등)에 사용.",
     "input_schema": {"type": "object", "properties": {
         "message": {"type": "string"}, "importance": {"type": "string", "enum": ["보통", "중요", "긴급"]}},
      "required": ["message"]}},
    {"name": "save_marketing", "description": "마케팅 콘텐츠 저장(현지어+한국어 번역 포함).",
     "input_schema": {"type": "object", "properties": {
         "country": {"type": "string"}, "channel": {"type": "string"}, "content": {"type": "string"}},
      "required": ["country", "channel", "content"]}},
    {"name": "save_report", "description": "운영 리포트 저장(한국어).",
     "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
      "required": ["title", "content"]}},
]

def exec_tool(name, inp):
    with LOCK:
        if name == "get_overview":
            low = [{"id": p["id"], "name": p["name"], "stock": p["stock"], "safe": p["safe"]}
                   for p in STORE["products"] if p["stock"] <= p["safe"]]
            pend = [{"id": i["id"], "country": i["country"], "text": i["text"][:80]}
                    for i in STORE["inquiries"] if i["status"] == "대기"]
            noship = [{"id": o["id"], "country": o["country"], "customer": o["customer"]}
                      for o in STORE["orders"] if o.get("payStatus") == "결제완료" and o.get("shipStatus") in (None, "", "준비중")]
            sites = [{"id": s["id"], "name": s["name"], "url": s["url"], "country": s.get("country", ""),
                      "lastStatus": s.get("lastStatus", "미점검"), "lastCheck": s.get("lastCheck", "")}
                     for s in STORE["sites"]]
            missing = [{"id": p["id"], "name": p["name"], "jp": bool(listing_of(p["id"], "JP")), "cn": bool(listing_of(p["id"], "CN"))}
                       for p in STORE["products"] if not listing_of(p["id"], "JP") or not listing_of(p["id"], "CN")]
            ym = today()[:7]
            sales = sum(order_total_krw(o) for o in STORE["orders"]
                        if o.get("payStatus") == "결제완료" and (o.get("date") or "").startswith(ym))
            return {"date": today(), "monthSalesKRW": sales, "sites": sites, "lowStock": low,
                    "pendingInquiries": pend, "ordersAwaitingShipment": noship, "productsMissingListings": missing}
        if name == "read_site_page":
            s = next((x for x in STORE["sites"] if x["id"] == inp.get("siteId")), None)
            if not s:
                return {"error": "사이트 없음"}
            try:
                status, text = fetch_page_text(s["url"])
                s["lastCheck"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                return {"site": s["name"], "httpStatus": status, "pageText": text}
            except Exception as e:
                s["lastCheck"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                s["lastStatus"] = "이상"
                return {"site": s["name"], "error": f"접속 실패: {e}"}
        if name == "report_site_status":
            s = next((x for x in STORE["sites"] if x["id"] == inp.get("siteId")), None)
            if not s:
                return {"error": "사이트 없음"}
            s["lastStatus"] = inp.get("status", "정상")
            s["lastNote"] = inp.get("note", "")[:500]
            s["lastCheck"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return {"saved": True, "site": s["name"], "status": s["lastStatus"]}
        if name == "get_products":
            return [{"id": p["id"], "name": p["name"], "nameEn": p["nameEn"], "priceKRW": p["price"],
                     "weightG": p["weight"], "stock": p["stock"], "safeStock": p["safe"],
                     "hasListingJP": bool(listing_of(p["id"], "JP")), "hasListingCN": bool(listing_of(p["id"], "CN"))}
                    for p in STORE["products"]]
        if name == "get_orders":
            return [{"id": o["id"], "date": o.get("date"), "country": o.get("country"), "market": o.get("market"),
                     "customer": o.get("customer"), "total": f'{order_total(o)} {o.get("currency")}',
                     "payStatus": o.get("payStatus"), "shipStatus": o.get("shipStatus")}
                    for o in STORE["orders"] if not inp.get("status") or o.get("shipStatus") == inp["status"]]
        if name == "get_inquiries":
            return [{"id": i["id"], "date": i["date"], "country": i["country"], "from": i.get("from", ""),
                     "text": i["text"], "status": i["status"]}
                    for i in STORE["inquiries"] if not inp.get("only_pending") or i["status"] == "대기"]
        if name == "calc_price":
            return calc_price_for(inp.get("productId"), inp.get("country"), inp.get("marketKey"), inp.get("marginPct"))
        if name == "save_listing":
            p = product_by_id(inp.get("productId"))
            if not p:
                return {"error": "productId 없음"}
            l = listing_of(inp["productId"], inp["country"])
            if not l:
                l = {"id": gen_id("LS"), "productId": inp["productId"], "country": inp["country"], "status": "초안"}
                STORE["listings"].append(l)
            l.update({"title": inp.get("title", ""), "desc": inp.get("desc", ""),
                      "keywords": inp.get("keywords", ""), "price": inp.get("price", 0),
                      "status": inp.get("status", l.get("status", "초안")), "updated": today()})
            return {"saved": True, "product": p["name"], "country": inp["country"]}
        if name == "answer_inquiry":
            i = next((x for x in STORE["inquiries"] if x["id"] == inp.get("inquiryId")), None)
            if not i:
                return {"error": "문의 없음"}
            i["reply"] = inp.get("reply", "")
            i["replyKo"] = inp.get("replyKo", "")
            i["status"] = "답변완료"
            return {"saved": True, "inquiryId": i["id"]}
        if name == "update_order":
            o = next((x for x in STORE["orders"] if x["id"] == inp.get("orderId")), None)
            if not o:
                return {"error": "주문 없음"}
            for k in ("payStatus", "carrier", "tracking"):
                if inp.get(k):
                    o[k] = inp[k]
            if inp.get("shipStatus"):
                if not o.get("stockDeducted") and inp["shipStatus"] in ("발송완료", "통관중", "배송중", "배달완료"):
                    for it in o.get("items", []):
                        p = product_by_id(it["productId"])
                        if p:
                            p["stock"] = max(0, p["stock"] - it["qty"])
                    o["stockDeducted"] = True
                o["shipStatus"] = inp["shipStatus"]
            return {"saved": True, "order": o["id"], "shipStatus": o.get("shipStatus"), "payStatus": o.get("payStatus")}
        if name == "update_stock":
            p = product_by_id(inp.get("productId"))
            if not p:
                return {"error": "제품 없음"}
            p["stock"] = max(0, p["stock"] + int(inp.get("delta", 0)))
            return {"saved": True, "product": p["name"], "newStock": p["stock"], "reason": inp.get("reason", "")}
        if name == "add_alert":
            STORE["alerts"].append({"id": gen_id("AL"), "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "message": inp.get("message", ""), "importance": inp.get("importance", "보통"),
                                    "done": False})
            return {"saved": True}
        if name == "save_marketing":
            STORE["marketing"].append({"id": gen_id("MK"), "date": today(), "country": inp.get("country", ""),
                                       "channel": inp.get("channel", ""), "content": inp.get("content", "")})
            return {"saved": True}
        if name == "save_report":
            STORE["reports"].append({"id": gen_id("RP"), "date": today(),
                                     "title": inp.get("title", ""), "content": inp.get("content", "")})
            return {"saved": True, "title": inp.get("title", "")}
        return {"error": "알 수 없는 도구: " + name}

def system_prompt():
    s = STORE["settings"]
    return f"""당신은 한국 가방 브랜드 에카사(ECKASA)의 해외판매를 자동으로 운영하는 AI 운영 매니저입니다.
사람이 지켜보지 않아도 스스로 판단해 업무를 수행합니다. 도구를 호출해야 실제로 저장/처리됩니다.

[브랜드] 에카사 — 보냉백·토트백·파우치 (eckasa.com)
[운영 정책] {s['policy']}
[환율] 1 JPY=₩{s['fx']['JPY']}, 1 CNY=₩{s['fx']['CNY']}
[배송] 일본: K-Packet(4~8일)/EMS(2~4일), 중국: EMS(3~7일)/플랫폼 물류
[통관] 일본: 소매가 약 16,666엔 이하 대부분 면세 / 중국: 크로스보더 종합세 약 9.1% 또는 행우세

[자동운영 규칙 — 중요]
1. 사이클 시작 시 get_overview로 현황부터 파악.
2. 등록된 판매 사이트는 read_site_page로 실제 접속해 점검하고 report_site_status로 결과를 기록.
   페이지에서 확인할 것: 접속 가능 여부, 에카사/제품 관련 내용 존재, 품절·가격 이상 징후.
3. 스스로 해도 되는 일: 문의 답변 작성·저장, 리스팅 작성, 재고 '기록' 점검, 리포트 작성, 사이트 점검.
4. 사람 확인이 필요한 일은 직접 하지 말고 add_alert로 등록: 가격 변경 결정, 환불 승인, 재고 발주 확정,
   사이트 이상 발견, 큰 금액 관련 판단. (재고 임의 조정 금지 — 발주는 제안만)
5. 고객에게 보이는 글은 해당 국가 언어(일본어 丁寧語/중국어 간체)로, 한국어 번역 포함.
6. 가격은 반드시 calc_price 결과 기준. 지어내지 말 것.
7. 사이클 마지막에는 반드시 save_report로 사이클 리포트를 저장하고(제목에 날짜·시각 포함),
   마지막 답변에 수행 내용을 한국어로 3~6줄 요약할 것."""

CYCLE_GOAL = """정기 자동운영 사이클을 수행하라:
① get_overview로 현황 파악
② 등록된 판매 사이트 각각 read_site_page로 접속 점검 → report_site_status 기록 (이상 시 add_alert)
③ 답변 대기 문의가 있으면 전부 답변 작성·저장
④ 재고 부족 상품 확인 → 발주 제안을 add_alert로 등록 (재고를 직접 조정하지 말 것)
⑤ 결제완료인데 발송 안 된 주문이 있으면 add_alert로 발송 요청 등록
⑥ 사이클 리포트 저장 (수행 내용 + 판매자가 할 일 목록)
불필요한 작업은 생략해도 되지만 ①②⑥은 반드시 수행."""

# ---------------- 사이클 실행 ----------------

def run_cycle(trigger="자동"):
    with LOCK:
        if STORE.get("running"):
            log("warn", "이미 사이클 실행 중 — 건너뜀")
            return
        STORE["running"] = True
    save_store()
    log("cycle", f"===== 운영 사이클 시작 ({trigger}) =====")
    try:
        if not STORE["settings"]["apiKey"]:
            log("err", "Claude API 키가 없어 AI 사이클을 건너뜁니다. 설정에서 키를 저장하세요.")
            return
        messages = [{"role": "user", "content": CYCLE_GOAL}]
        for turn in range(14):
            resp = anthropic_call(system_prompt(), messages, tools=AGENT_TOOLS, max_tokens=4096)
            if resp.get("stop_reason") == "refusal":
                log("err", "요청이 거절되었습니다.")
                break
            texts = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
            tool_uses = [b for b in resp.get("content", []) if b.get("type") == "tool_use"]
            if resp.get("stop_reason") != "tool_use":
                if texts:
                    log("final", texts)
                break
            if texts:
                log("think", texts[:500])
            messages.append({"role": "assistant", "content": resp["content"]})
            results = []
            for tu in tool_uses:
                log("tool", f'{tu["name"]}({json.dumps(tu.get("input", {}), ensure_ascii=False)[:120]})')
                try:
                    out = exec_tool(tu["name"], tu.get("input") or {})
                except Exception as e:
                    out = {"error": str(e)}
                if isinstance(out, dict) and out.get("error"):
                    log("warn", f'→ {out["error"]}')
                results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                "content": json.dumps(out, ensure_ascii=False)[:8000]})
            messages.append({"role": "user", "content": results})
            save_store()
        else:
            log("warn", "최대 작업 횟수 도달 — 사이클 종료")
    except Exception as e:
        log("err", f"사이클 오류: {e}")
    finally:
        with LOCK:
            STORE["running"] = False
            STORE["lastRun"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            STORE["cycleCount"] = STORE.get("cycleCount", 0) + 1
            nxt = datetime.now() + timedelta(minutes=int(STORE["settings"].get("intervalMin", 60)))
            STORE["nextRun"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
        save_store()
        log("cycle", "===== 사이클 종료 =====")

def scheduler_loop():
    with LOCK:
        if not STORE.get("nextRun"):
            STORE["nextRun"] = (datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    save_store()
    while True:
        time.sleep(20)
        try:
            with LOCK:
                auto = STORE["settings"].get("autoRun", True)
                nxt = STORE.get("nextRun")
                running = STORE.get("running")
            if auto and not running and nxt and datetime.now() >= datetime.strptime(nxt, "%Y-%m-%d %H:%M:%S"):
                run_cycle("자동")
        except Exception as e:
            log("err", f"스케줄러 오류: {e}")

# ---------------- HTTP 서버 ----------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(os.path.join(BASE, "index.html"), "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self._json({"error": "index.html 없음"}, 500)
            return
        if self.path == "/api/state":
            with LOCK:
                s = STORE
                self._json({
                    "settings": {**s["settings"], "apiKey": ("saved" if s["settings"]["apiKey"] else "")},
                    "sites": s["sites"], "running": s.get("running"), "lastRun": s.get("lastRun"),
                    "nextRun": s.get("nextRun"), "cycleCount": s.get("cycleCount", 0),
                    "counts": {
                        "orders": len(s["orders"]), "pendingInq": len([i for i in s["inquiries"] if i["status"] == "대기"]),
                        "lowStock": len([p for p in s["products"] if p["stock"] <= p["safe"]]),
                        "alerts": len([a for a in s["alerts"] if not a["done"]]),
                        "reports": len(s["reports"]), "listings": len(s["listings"]),
                    },
                    "logs": s["logs"][-120:],
                    "alerts": [a for a in s["alerts"] if not a["done"]][-30:],
                })
            return
        if self.path == "/api/data":
            with LOCK:
                self._json({"products": STORE["products"], "orders": STORE["orders"][-50:],
                            "inquiries": STORE["inquiries"][-50:], "listings": STORE["listings"],
                            "reports": STORE["reports"][-20:], "marketing": STORE["marketing"][-20:],
                            "alertsAll": STORE["alerts"][-50:]})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._body()
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        path = self.path
        if path == "/api/settings":
            with LOCK:
                st = STORE["settings"]
                if "apiKey" in body and body["apiKey"] != "saved":
                    st["apiKey"] = body["apiKey"].strip()
                for k in ("intervalMin", "policy", "autoRun"):
                    if k in body:
                        st[k] = body[k]
                if "fx" in body:
                    st["fx"].update(body["fx"])
                if "seller" in body:
                    st["seller"].update(body["seller"])
            save_store()
            self._json({"ok": True})
            return
        if path == "/api/sites":
            with LOCK:
                act = body.get("action")
                if act == "add":
                    url = body.get("url", "").strip()
                    if not url.startswith("http"):
                        url = "https://" + url
                    STORE["sites"].append({"id": gen_id("ST"), "name": body.get("name", "").strip() or url,
                                           "url": url, "country": body.get("country", ""),
                                           "notes": body.get("notes", ""), "lastStatus": "미점검",
                                           "lastCheck": "", "lastNote": ""})
                elif act == "del":
                    STORE["sites"] = [s for s in STORE["sites"] if s["id"] != body.get("id")]
            save_store()
            self._json({"ok": True})
            return
        if path == "/api/run":
            threading.Thread(target=run_cycle, args=("수동",), daemon=True).start()
            self._json({"ok": True})
            return
        if path == "/api/inquiry":
            with LOCK:
                STORE["inquiries"].append({"id": gen_id("IQ"), "date": today(),
                                           "country": body.get("country", "JP"), "from": body.get("from", ""),
                                           "text": body.get("text", ""), "status": "대기", "reply": "", "replyKo": ""})
            save_store()
            self._json({"ok": True})
            return
        if path == "/api/alert_done":
            with LOCK:
                for a in STORE["alerts"]:
                    if a["id"] == body.get("id"):
                        a["done"] = True
            save_store()
            self._json({"ok": True})
            return
        if path == "/api/site_check":
            sid = body.get("id")
            s = next((x for x in STORE["sites"] if x["id"] == sid), None)
            if not s:
                self._json({"error": "사이트 없음"}, 404)
                return
            try:
                status, text = fetch_page_text(s["url"], 800)
                with LOCK:
                    s["lastCheck"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    s["lastStatus"] = "정상" if status == 200 else "주의"
                save_store()
                self._json({"ok": True, "httpStatus": status, "preview": text[:400]})
            except Exception as e:
                with LOCK:
                    s["lastCheck"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    s["lastStatus"] = "이상"
                save_store()
                self._json({"ok": False, "error": str(e)})
            return
        self._json({"error": "not found"}, 404)

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    save_store()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print("=" * 55)
    print("  에카사 자동운영 서버가 켜졌습니다")
    print(f"  관리 화면: {url}")
    print("  이 창을 닫으면 자동운영이 멈춥니다. 켜 두세요!")
    print("=" * 55)
    if "--nobrowser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("종료합니다.")

if __name__ == "__main__":
    main()
