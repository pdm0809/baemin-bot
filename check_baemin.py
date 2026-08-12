import subprocess
import json
import requests
import sys
import logging
from datetime import datetime

# ==============================================================================
# [설정 항목]
# ==============================================================================
GAS_URL = "https://script.google.com/macros/s/AKfycbybEopFhrpBc1IfVtgoWatjNcjq-ucF_i3jnCRpNiUVQ-GNhVkEbt6SjAq9Bv0ipM5h/exec"
CENTER_ID = "DP2511060448"

# 전달해 주신 최신 세션 쿠키 적용
COOKIE = "dsid=8dff4928-c182-47d4-8772-e2a5a402a157; _wp_uid=1-b64e91cb5ed11a28894cc86e59e4b722-s1776862146.426964|windows_10|chrome-dy1hgz; tbid=6c55babc-a664-4fba-bace-5efe4648c258; _hjSessionUser_5123796=eyJpZCI6IjU3NGNiYzc4LWM4YjctNWI2Yy04MDg4LTcxZDFmYTc5ODVlZCIsImNyZWF0ZWQiOjE3NzY5NDk4MTgzNDEsImV4aXN0aW5nIjp0cnVlfQ==; _ga_QZ54WQ25KW=GS2.1.s1777119700$o2$g1$t1777119717$j43$l0$h0; _ga=GA1.1.1294575212.1776949812; _ga_DD6D4M7LEB=GS2.1.s1777119699$o2$g1$t1777119718$j41$l0$h0; _ga_BVQGVEDG55=GS2.1.s1777119687$o2$g1$t1777119728$j19$l0$h0; _ceo_v2_gk_sid=a0634d36-0886-4231-8074-8acd2a12657b; CENTER_SESSION=NDg0MjFlYjMtNjQ4Ny00OTUxLWJhNjMtM2Q4MWM0NmQwYTg2; __cf_bm=DT4FWbsqEWJFaixDax2ul7wZJotzE9e5LpMzdY3Zc3A-1786511676.58738-1.0.1.1-jcAKtGddzMLLsIzWE6msKMB5LoBidIv1nR0nAwp_h.ImiJ9zrViI0cgy1MpnzZkT7oZ1ckAR1o_Dx8MTOEs1w8FQhu7ZGQDVIIVv_i3fs98b_DcHjZmCSlKM30DB2eoOt1GUI5vDTTQnOMVac4Pf.Q; _ga_ZGDXE0V87X=GS2.1.s1786506922$o25$g1$t1786512423$j54$l0$h0"

BASE_API_URL = "https://api-deliverycenter.baemin.com/v4/management/delivery-status?size=100&orderName=name&orderBy=asc&name=&userId=&phoneNumber="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

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


def fetch_curl(url):
    """리눅스 내장 curl 기반 타격"""
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


def push_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    resp = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=15)
    return resp.text.strip()


def collect_all_data():
    page = 0
    all_riders = []
    total_summary = {}
    riding_count = 0

    while True:
        url = f"{BASE_API_URL}&page={page}"
        raw = fetch_curl(url)
        
        if not raw or not raw.strip():
            raise ValueError("API 응답이 비어있습니다.")

        if not raw.strip().startswith("{"):
            log.error(f"❌ 배민 API 응답 오류 (응답 미리보기: {raw[:150]})")
            raise ValueError("배민 사이트 응답이 올바른 JSON 형식이 아닙니다.")

        data = json.loads(raw)

        if isinstance(data, dict) and data.get("status") in (401, 403):
            raise PermissionError("쿠키 세션이 만료되었습니다.")

        if page == 0:
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
        page += 1

        if page >= total_pages:
            break

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": total_summary,
        "ridingCount": riding_count,
        "riderList": all_riders
    }


if __name__ == "__main__":
    log.info("🚀 [배민 데이터 수집기] 수집 시작")
    try:
        payload = collect_all_data()
        resp = push_to_gas(payload)
        log.info(f"✔️ 전송 완료 ({resp}) | 총 기사 수: {len(payload['riderList'])}명 | 운행중: {payload['ridingCount']}명")
    except Exception as exc:
        log.error(f"❌ 오류 발생: {exc}")
        sys.exit(1)
