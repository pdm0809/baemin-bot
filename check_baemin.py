import json
import requests
import sys
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright

# ==============================================================================
# [설정 항목]
# ==============================================================================
GAS_URL = "https://script.google.com/macros/s/AKfycbybEopFhrpBc1IfVtgoWatjNcjq-ucF_i3jnCRpNiUVQ-GNhVkEbt6SjAq9Bv0ipM5h/exec"
CENTER_ID = "DP2511060448"

# 최신 세션 쿠키
COOKIE = "dsid=8dff4928-c182-47d4-8772-e2a5a402a157; _wp_uid=1-b64e91cb5ed11a28894cc86e59e4b722-s1776862146.426964|windows_10|chrome-dy1hgz; tbid=6c55babc-a664-4fba-bace-5efe4648c258; _hjSessionUser_5123796=eyJpZCI6IjU3NGNiYzc4LWM4YjctNWI2Yy04MDg4LTcxZDFmYTc5ODVlZCIsImNyZWF0ZWQiOjE3NzY5NDk4MTgzNDEsImV4aXN0aW5nIjp0cnVlfQ==; _ga_QZ54WQ25KW=GS2.1.s1777119700$o2$g1$t1777119717$j43$l0$h0; _ga=GA1.1.1294575212.1776949812; _ga_DD6D4M7LEB=GS2.1.s1777119699$o2$g1$t1777119718$j41$l0$h0; _ga_BVQGVEDG55=GS2.1.s1777119687$o2$g1$t1777119728$j19$l0$h0; _ceo_v2_gk_sid=a0634d36-0886-4231-8074-8acd2a12657b; CENTER_SESSION=NDg0MjFlYjMtNjQ4Ny00OTUxLWJhNjMtM2Q4MWM0NmQwYTg2; __cf_bm=DT4FWbsqEWJFaixDax2ul7wZJotzE9e5LpMzdY3Zc3A-1786511676.58738-1.0.1.1-jcAKtGddzMLLsIzWE6msKMB5LoBidIv1nR0nAwp_h.ImiJ9zrViI0cgy1MpnzZkT7oZ1ckAR1o_Dx8MTOEs1w8FQhu7ZGQDVIIVv_i3fs98b_DcHjZmCSlKM30DB2eoOt1GUI5vDTTQnOMVac4Pf.Q; _ga_ZGDXE0V87X=GS2.1.s1786506922$o25$g1$t1786512423$j54$l0$h0"

BASE_API_URL = "https://api-deliverycenter.baemin.com/v4/management/delivery-status?size=100&orderName=name&orderBy=asc&name=&userId=&phoneNumber="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("baemin_collector")


def safe_int(val):
    if val is None:
        return 0
    try:
        return int(val)
    except Exception:
        return 0


def push_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    resp = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=15)
    return resp.text.strip()


def collect_all_data():
    all_riders = []
    total_summary = {}
    riding_count = 0

    with sync_playwright() as p:
        # 가상 크롬 브라우저 실행
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA)
        page_obj = context.new_page()

        # 1. 배민 메인 페이지 접속으로 방화벽(자바스크립트 보안) 통과
        log.info("🌐 크롬 브라우저 가동 및 배민 방화벽 통과 중...")
        page_obj.goto("https://deliverycenter.baemin.com/", wait_until="networkidle", timeout=30000)

        page_num = 0
        while True:
            url = f"{BASE_API_URL}&page={page_num}"
            
            # 2. 브라우저 내부 세션으로 API 타격
            response = context.request.get(
                url,
                headers={
                    "authority": "api-deliverycenter.baemin.com",
                    "accept": "application/json, text/plain, */*",
                    "center-id": CENTER_ID,
                    "cookie": COOKIE,
                    "origin": "https://deliverycenter.baemin.com",
                    "referer": "https://deliverycenter.baemin.com/",
                }
            )

            if response.status not in (200, 201):
                log.error(f"❌ HTTP {response.status}: {response.text()[:200]}")
                raise PermissionError(f"API 요청 실패 (Status: {response.status})")

            data = response.json()

            if page_num == 0:
                total_summary = data.get("deliveryStatusTotalResponse", {})

            rider_rows = data.get("data", [])
            for r in rider_rows:
                ac = r.get("deliveryAcceptanceCount", {}) or {}
                pt = r.get("deliveryPeakTimeCount", {}) or {}
                st = r.get("status", {})

                status_code = st.get("code", "READY") if isinstance(st, dict) else str(st)
                status_desc = st.get("desc", "운행 종료") if isinstance(st, dict) else ""

                if status_code == "DELIVERING":
                    riding_count += 1

                all_riders.append({
                    "name": r.get("name", ""),
                    "userId": r.get("userId", ""),
                    "phoneNumber": r.get("phoneNumber", ""),
                    "status": {
                        "code": status_code,
                        "desc": status_desc
                    },
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

            total_pages = data.get("totalPage", 1)
            page_num += 1

            if page_num >= total_pages:
                break

        browser.close()

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": total_summary,
        "ridingCount": riding_count,
        "riderList": all_riders
    }


if __name__ == "__main__":
    log.info("🚀 [Playwright 크롬 가상 수집기] 데이터 수집 시작")
    try:
        payload = collect_all_data()
        resp = push_to_gas(payload)
        log.info(f"✔️ 전송 완료 ({resp}) | 총 기사 수: {len(payload['riderList'])}명 | 운행중: {payload['ridingCount']}명")
    except Exception as exc:
        log.error(f"❌ 수집 중 오류 발생: {exc}")
        sys.exit(1)
