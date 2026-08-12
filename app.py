import json, time, logging, threading, sys, os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

PORT = 80
CENTER_ID = "DP2511060448"
BASE_API_URL = "https://api-deliverycenter.baemin.com/v4/management/delivery-status?size=100&orderName=name&orderBy=asc&name=&userId=&phoneNumber=&riderStatus="

LATEST_DATA = {}
CUSTOM_SETTINGS = {}
DATA_LOCK = threading.Lock()

TARGETS = {
    "morning":   [19, 19, 19, 19, 21, 27, 29],
    "afternoon": [18, 18, 18, 18, 21, 22, 22],
    "evening":   [30, 30, 30, 30, 32, 36, 35],
    "night":     [23, 23, 23, 23, 26, 25, 24],
}
DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("app")

def safe_int(v):
    try: return int(v) if v is not None else 0
    except: return 0

def fetch_via_playwright(page):
    try:
        # 배민 협력사 센터 접속 (Cloudflare JS 인증 자동 수행)
        page.goto("https://deliverycenter.baemin.com", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # 0페이지 우선 호출
        url_0 = f"{BASE_API_URL}&page=0"
        raw_0 = page.evaluate(f"""async () => {{
            const res = await fetch('{url_0}', {{
                headers: {{ 'center-id': '{CENTER_ID}', 'accept': 'application/json, text/plain, */*' }}
            }});
            return await res.json();
        }}""")

        if not raw_0 or "deliveryStatusTotalResponse" not in raw_0:
            log.error("❌ API 데이터 수신 실패 (보안 페이지 또는 로그인 필요)")
            return None, []

        total_summary = raw_0.get("deliveryStatusTotalResponse", {})
        total_pages = raw_0.get("totalPage", 1)
        all_riders = []

        # 전체 페이지 순회 수집
        for p in range(total_pages):
            url = f"{BASE_API_URL}&page={p}"
            data = page.evaluate(f"""async () => {{
                const res = await fetch('{url}', {{
                    headers: {{ 'center-id': '{CENTER_ID}', 'accept': 'application/json, text/plain, */*' }}
                }});
                return await res.json();
            }}""")
            rider_rows = data.get("data", [])
            for r in rider_rows:
                ac = r.get("deliveryAcceptanceCount", {}) or {}
                pt = r.get("deliveryPeakTimeCount", {}) or {}
                st = r.get("status", {})
                status_code = st.get("code", "READY") if isinstance(st, dict) else str(st)
                status_desc = st.get("desc", "운행 종료") if isinstance(st, dict) else ""
                all_riders.append({
                    "name": r.get("name", ""),
                    "userId": r.get("userId", ""),
                    "phoneNumber": r.get("phoneNumber", ""),
                    "status": {"code": status_code, "desc": status_desc},
                    "acceptance": {
                        "foodComplete": safe_int(ac.get("foodComplete")),
                        "bmartComplete": safe_int(ac.get("bmartComplete")),
                        "storeComplete": safe_int(ac.get("storeComplete")),
                        "totalComplete": safe_int(ac.get("totalComplete")),
                        "allDayComplete": safe_int(ac.get("allDayComplete")),
                        "slaOutComplete": safe_int(ac.get("slaOutComplete")),
                        "foodReject": safe_int(ac.get("foodReject")),
                        "bmartReject": safe_int(ac.get("bmartReject")),
                        "storeReject": safe_int(ac.get("storeReject")),
                        "totalReject": safe_int(ac.get("totalReject")),
                        "foodCancel": safe_int(ac.get("foodCancel")),
                        "bmartCancel": safe_int(ac.get("bmartCancel")),
                        "storeCancel": safe_int(ac.get("storeCancel")),
                        "totalCancel": safe_int(ac.get("totalCancel")),
                        "foodRiderFault": safe_int(ac.get("foodRiderFault")),
                        "bmartRiderFault": safe_int(ac.get("bmartRiderFault")),
                        "storeRiderFault": safe_int(ac.get("storeRiderFault")),
                        "totalRiderFault": safe_int(ac.get("totalRiderFault")),
                    },
                    "peakTime": {
                        "morning": safe_int(pt.get("morning")),
                        "afternoon": safe_int(pt.get("afternoon")),
                        "evening": safe_int(pt.get("evening")),
                        "midnight": safe_int(pt.get("midnight"))
                    },
                    "hourlyCompleted": r.get("hourlyCompleted", [])
                })
        return total_summary, all_riders
    except Exception as e:
        log.error(f"⚠️ Playwright 수집 오류: {e}")
        return None, []

def collect_loop():
    global LATEST_DATA
    log.info("🚀 [GCP Playwright 수집 엔진] 가동 시작")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        while True:
            try:
                total_summary, all_riders = fetch_via_playwright(page)
                if total_summary is not None:
                    riding_count = sum(1 for r in all_riders if r.get("status", {}).get("code") == "DELIVERING")
                    with DATA_LOCK:
                        LATEST_DATA = {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "total": total_summary,
                            "ridingCount": riding_count,
                            "riderList": all_riders
                        }
                    log.info(f"✔️ 데이터 수집 완료 | 총 기사 수: {len(all_riders)}명 | 운행중: {riding_count}명")
            except Exception as e:
                log.error(f"⚠️ 수집 루프 예외: {e}")

            h = datetime.now().hour
            time.sleep(60 if 17 <= h < 20 else 90)

def get_processed_data():
    with DATA_LOCK: data = LATEST_DATA
    now = datetime.now()
    hour, day_idx = now.hour, 6 if now.weekday() == 6 else now.weekday()
    is_weekend = (day_idx in (5, 6))
    times = CUSTOM_SETTINGS.get("times", {
        "morning_end": 14 if is_weekend else 13,
        "afternoon_end": 17,
        "evening_end": 20,
    })
    if 9 <= hour < times["morning_end"]: active_slot = "morning"
    elif times["morning_end"] <= hour < times["afternoon_end"]: active_slot = "afternoon"
    elif times["afternoon_end"] <= hour < times["evening_end"]: active_slot = "evening"
    else: active_slot = "night"

    total_summary = data.get("total", {})
    set_count = CUSTOM_SETTINGS.get("setCount", 8)
    ratio = set_count / 1.0
    default_targets = {
        "morning": round(TARGETS["morning"][day_idx] * ratio),
        "afternoon": round(TARGETS["afternoon"][day_idx] * ratio),
        "evening": round(TARGETS["evening"][day_idx] * ratio),
        "night": round(TARGETS["night"][day_idx] * ratio)
    }
    targets = CUSTOM_SETTINGS.get("targets", default_targets)
    return {
        "dayName": DAY_NAMES[day_idx], "dayIdx": day_idx, "activeSlot": active_slot,
        "updatedAt": data.get("time", "-"), "total": total_summary,
        "targets": targets, "times": times, "ridingCount": data.get("ridingCount", 0),
        "riderList": data.get("riderList", []), "isCustom": bool(CUSTOM_SETTINGS), "baseTargets": TARGETS, "setCount": set_count
    }

def get_html():
    paths = [os.path.expanduser("~/index.html"), "/home/pdm0809/index.html", "/root/index.html", "index.html"]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    c = f.read()
                    if len(c) > 100: return c
            except: pass
    return b"<h1>Loading...</h1>"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/data":
            body = json.dumps(get_processed_data(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            body = get_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/settings":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            global CUSTOM_SETTINGS
            CUSTOM_SETTINGS = json.loads(body.decode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")

    def log_message(self, format, *args): return

if __name__ == "__main__":
    threading.Thread(target=collect_loop, daemon=True).start()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
