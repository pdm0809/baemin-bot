import subprocess
import json
import requests
import time
import logging
import threading
import sys
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 80
CENTER_ID = "DP2511060448"

# 배민 세션 쿠키
COOKIE = "dsid=8dff4928-c182-47d4-8772-e2a5a402a157; _wp_uid=1-b64e91cb5ed11a28894cc86e59e4b722-s1776862146.426964|windows_10|chrome-dy1hgz; tbid=6c55babc-a664-4fba-bace-5efe4648c258; _hjSessionUser_5123796=eyJpZCI6IjU3NGNiYzc4LWM4YjctNWI2Yy04MDg4LTcxZDFmYTc5ODVlZCIsImNyZWF0ZWQiOjE3NzY5NDk4MTgzNDEsImV4aXN0aW5nIjp0cnVlfQ==; _ga_QZ54WQ25KW=GS2.1.s1777119700$o2$g1$t1777119717$j43$l0$h0; _ga=GA1.1.1294575212.1776949812; _ga_DD6D4M7LEB=GS2.1.s1777119699$o2$g1$t1777119718$j41$l0$h0; _ga_BVQGVEDG55=GS2.1.s1777119687$o2$g1$t1777119728$j19$l0$h0; _ceo_v2_gk_sid=a0634d36-0886-4231-8074-8acd2a12657b; CENTER_SESSION=NDg0MjFlYjMtNjQ4Ny00OTUxLWJhNjMtM2Q4MWM0NmQwYTg2; __cf_bm=DT4FWbsqEWJFaixDax2ul7wZJotzE9e5LpMzdY3Zc3A-1786511676.58738-1.0.1.1-jcAKtGddzMLLsIzWE6msKMB5LoBidIv1nR0nAwp_h.ImiJ9zrViI0cgy1MpnzZkT7oZ1ckAR1o_Dx8MTOEs1w8FQhu7ZGQDVIIVv_i3fs98b_DcHjZmCSlKM30DB2eoOt1GUI5vDTTQnOMVac4Pf.Q; _ga_ZGDXE0V87X=GS2.1.s1786506922$o25$g1$t1786512423$j54$l0$h0"

BASE_API_URL = "https://api-deliverycenter.baemin.com/v4/management/delivery-status?size=100&orderName=name&orderBy=asc&name=&userId=&phoneNumber="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

LATEST_DATA = {}
CUSTOM_SETTINGS = {}
DATA_LOCK = threading.Lock()

# 1세트 기준 기본 물량표 (표준경북포항북A)
TARGETS = {
    "morning":   [19, 19, 19, 19, 21, 27, 29],
    "afternoon": [18, 18, 18, 18, 21, 22, 22],
    "evening":   [30, 30, 30, 30, 32, 36, 35],
    "night":     [23, 23, 23, 23, 26, 25, 24],
}
DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("app")

def safe_int(val):
    if val is None: return 0
    try: return int(val)
    except Exception: return 0

def fetch_curl(url):
    cmd = [
        "curl", "-s", url,
        "-H", "authority: api-deliverycenter.baemin.com",
        "-H", "accept: application/json",
        "-H", f"center-id: {CENTER_ID}",
        "-H", f"cookie: {COOKIE}",
        "-H", f"user-agent: {UA}",
        "--compressed"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return res.stdout

def collect_loop():
    global LATEST_DATA
    log.info("🚀 [통합 수집 엔진] 가동 시작")
    while True:
        try:
            page, all_riders, total_summary, riding_count = 0, [], {}, 0
            while True:
                url = f"{BASE_API_URL}&page={page}"
                raw = fetch_curl(url)
                if not raw or not raw.strip().startswith("{"): break
                data = json.loads(raw)
                if page == 0: total_summary = data.get("deliveryStatusTotalResponse", {})
                for r in data.get("data", []):
                    ac, pt, st = r.get("deliveryAcceptanceCount", {}) or {}, r.get("deliveryPeakTimeCount", {}) or {}, r.get("status", {})
                    st_code = st.get("code", "READY") if isinstance(st, dict) else str(st)
                    st_desc = st.get("desc", "운행 종료") if isinstance(st, dict) else ""
                    if st_code == "DELIVERING": riding_count += 1
                    all_riders.append({
                        "name": r.get("name", ""), "userId": r.get("userId", ""), "phoneNumber": r.get("phoneNumber", ""),
                        "status": {"code": st_code, "desc": st_desc},
                        "acceptance": {
                            "foodComplete": safe_int(ac.get("foodComplete")), "bmartComplete": safe_int(ac.get("bmartComplete")), "storeComplete": safe_int(ac.get("storeComplete")),
                            "totalComplete": safe_int(ac.get("totalComplete")), "allDayComplete": safe_int(ac.get("allDayComplete")), "slaOutComplete": safe_int(ac.get("slaOutComplete")),
                            "foodReject": safe_int(ac.get("foodReject")), "bmartReject": safe_int(ac.get("bmartReject")), "storeReject": safe_int(ac.get("storeReject")), "totalReject": safe_int(ac.get("totalReject")),
                            "foodCancel": safe_int(ac.get("foodCancel")), "bmartCancel": safe_int(ac.get("bmartCancel")), "storeCancel": safe_int(ac.get("storeCancel")), "totalCancel": safe_int(ac.get("totalCancel")),
                            "foodRiderFault": safe_int(ac.get("foodRiderFault")), "bmartRiderFault": safe_int(ac.get("bmartRiderFault")), "storeRiderFault": safe_int(ac.get("storeRiderFault")), "totalRiderFault": safe_int(ac.get("totalRiderFault"))
                        },
                        "peakTime": {"morning": safe_int(pt.get("morning")), "afternoon": safe_int(pt.get("afternoon")), "evening": safe_int(pt.get("evening")), "midnight": safe_int(pt.get("midnight"))},
                        "hourlyCompleted": r.get("hourlyCompleted", [])
                    })
                page += 1
                if page >= data.get("totalPage", 1): break

            with DATA_LOCK:
                LATEST_DATA = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "total": total_summary, "ridingCount": riding_count, "riderList": all_riders}
            log.info(f"✔️ 데이터 수집 완료 | 총 기사 수: {len(all_riders)}명 | 운행중: {riding_count}명")
        except Exception as e:
            log.error(f"⚠️ 수집 예외: {e}")
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

    m_done, a_done, e_done, n_done = 0, 0, 0, 0
    for r in data.get("riderList", []):
        for h_item in r.get("hourlyCompleted", []):
            h_num = h_item.get("hour", 0)
            h_cnt = h_item.get("count", 0)
            if 9 <= h_num < times["morning_end"]: m_done += h_cnt
            elif times["morning_end"] <= h_num < times["afternoon_end"]: a_done += h_cnt
            elif times["afternoon_end"] <= h_num < times["evening_end"]: e_done += h_cnt
            elif times["evening_end"] <= h_num < 24: n_done += h_cnt

    computed_total = {
        "totalMorningCompleted": m_done,
        "totalLunchCompleted": a_done,
        "totalDinnerCompleted": e_done,
        "totalNightCompleted": n_done
    }

    set_count = CUSTOM_SETTINGS.get("setCount", 6)
    ratio = set_count / 1.0 # 1세트 기준 곱셈

    default_targets = {
        "morning": round(TARGETS["morning"][day_idx] * ratio),
        "afternoon": round(TARGETS["afternoon"][day_idx] * ratio),
        "evening": round(TARGETS["evening"][day_idx] * ratio),
        "night": round(TARGETS["night"][day_idx] * ratio)
    }
    targets = CUSTOM_SETTINGS.get("targets", default_targets)

    return {
        "dayName": DAY_NAMES[day_idx], "dayIdx": day_idx, "activeSlot": active_slot,
        "updatedAt": data.get("time", "-"), "total": computed_total,
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

