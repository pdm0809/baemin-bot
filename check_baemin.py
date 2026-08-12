import subprocess
import json
import requests
import time
import logging
import signal
import sys
from datetime import datetime

# ==============================================================================
# [설정 항목]
# ==============================================================================
GAS_URL = "https://script.google.com/macros/s/AKfycbybEopFhrpBc1IfVtgoWatjNcjq-ucF_i3jnCRpNiUVQ-GNhVkEbt6SjAq9Bv0ipM5h/exec"
CENTER_ID = "DP2511060448"

# 배민 세션 쿠키
COOKIE = "dsid=8dff4928-c182-47d4-8772-e2a5a402a157; _wp_uid=1-b64e91cb5ed11a28894cc86e59e4b722-s1776862146.426964|windows_10|chrome-dy1hgz; _gcl_au=1.1.2061061991.1776949812; _fbp=fb.1.1776949818364.811198069494254366; _kmpid=km|baemin.com|1776949827212|7d770d2a-5524-4b5c-b919-166db05b40ca; tbid=6c55babc-a664-4fba-bace-5efe4648c258; _hjSessionUser_5123796=eyJpZCI6IjU3NGNiYzc4LWM4YjctNWI2Yy04MDg4LTcxZDFmYTc5ODVlZCIsImNyZWF0ZWQiOjE3NzY5NDk4MTgzNDEsImV4aXN0aW5nIjp0cnVlfQ==; _ga_QZ54WQ25KW=GS2.1.s1777119700$o2$g1$t1777119717$j43$l0$h0; _ga=GA1.1.1294575212.1776949812; _ga_DD6D4M7LEB=GS2.1.s1777119699$o2$g1$t1777119718$j41$l0$h0; _ga_BVQGVEDG55=GS2.1.s1777119687$o2$g1$t1777119728$j19$l0$h0; _ceo_v2_gk_sid=a0634d36-0886-4231-8074-8acd2a12657b; __cf_bm=mVZqCCsd8tDYdg.bBThTzqOzFX8EP5qz07st6Z7RUCM-1782348149.9522622-1.0.1.1-eADICZLTQXEhbAInfnNM7TKsY2Dd1s9u2rSOdsiV9Dy5105JBorWU2Ixa..p4h4Xrmuc_Pr7uTrikIv2wkrLPTedutSf3_j_oBiqFr6.8viGHa.PTxI0UNf6b5SNxmN4QBzCDU2QNxNu0._z6vXCzg; CENTER_SESSION=ODI0ZGMzOTAtNzc3YS00NjcwLTgyMmEtZTJhZTNjNGEyNmJk; _ga_ZGDXE0V87X=GS2.1.s1782348150$o23$g1$t1782348202$j8$l0$h0"

# 배민 API 주소 템플릿
BASE_API_URL = "https://api-deliverycenter.baemin.com/v4/management/delivery-status?size=100&orderName=name&orderBy=asc&name=&userId=&phoneNumber="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

# 로깅 설정
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


def get_interval():
    """시간대별 수집 주기 설정 (초 단위)"""
    h = datetime.now().hour
    if 17 <= h < 20:      # 저녁 피크타임 (60초)
        return 60
    elif 6 <= h < 17:     # 아침/낮 (90초)
        return 90
    else:                 # 야간/심야 (120초)
        return 120


def fetch_curl(url):
    """curl 명령어를 통해 배민 API 타격 (Cloudflare 방화벽 우회)"""
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
    """구글 앱스크립트(GAS)로 수집한 데이터 POST 전송"""
    headers = {"Content-Type": "application/json"}
    resp = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=15)
    return resp.text.strip()


def collect_all_data():
    """페이지네이션을 고려하여 전체 기사 데이터 수집"""
    page = 0
    all_riders = []
    total_summary = {}
    riding_count = 0

    while True:
        url = f"{BASE_API_URL}&page={page}"
        raw = fetch_curl(url)
        if not raw:
            raise ValueError("API 응답이 비어있습니다. (네트워크 오류 또는 차단)")

        data = json.loads(raw)

        # 권한 및 세션 에러 체크
        if isinstance(data, dict) and data.get("status") in (401, 403):
            raise PermissionError("쿠키 세션이 만료되었습니다. 새 쿠키로 교체해 주세요.")

        # 1페이지(page=0)일 때 전체 요약(total) 정보 저장
        if page == 0:
            total_summary = data.get("deliveryStatusTotalResponse", {})
            total_riders_count = data.get("total", 0)

        # 기사 목록 파싱
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
                # SLA 완료 상세
                "acceptance": {
                    "foodComplete": safe_int(ac.get("foodComplete")),
                    "bmartComplete": safe_int(ac.get("bmartComplete")),
                    "storeComplete": safe_int(ac.get("storeComplete")),
                    "totalComplete": safe_int(ac.get("totalComplete")),
                    "allDayComplete": safe_int(ac.get("allDayComplete")),
                    "slaOutComplete": safe_int(ac.get("slaOutComplete")),

                    # SLA 거절
                    "foodReject": safe_int(ac.get("foodReject")),
                    "bmartReject": safe_int(ac.get("bmartReject")),
                    "storeReject": safe_int(ac.get("storeReject")),
                    "totalReject": safe_int(ac.get("totalReject")),

                    # SLA 배차취소
                    "foodCancel": safe_int(ac.get("foodCancel")),
                    "bmartCancel": safe_int(ac.get("bmartCancel")),
                    "storeCancel": safe_int(ac.get("storeCancel")),
                    "totalCancel": safe_int(ac.get("totalCancel")),

                    # SLA 배달취소 (라이더 귀책)
                    "foodRiderFault": safe_int(ac.get("foodRiderFault")),
                    "bmartRiderFault": safe_int(ac.get("bmartRiderFault")),
                    "storeRiderFault": safe_int(ac.get("storeRiderFault")),
                    "totalRiderFault": safe_int(ac.get("totalRiderFault")),
                },
                # SLA 피크 슬롯별 완료
                "peakTime": {
                    "morning": safe_int(pt.get("morning")),
                    "afternoon": safe_int(pt.get("afternoon")),
                    "evening": safe_int(pt.get("evening")),
                    "midnight": safe_int(pt.get("midnight"))
                },
                # 24시간 세부 시간별 완료
                "hourlyCompleted": r.get("hourlyCompleted", [])
            })

        total_pages = data.get("totalPage", 1)
        page += 1

        # 모든 페이지를 다 읽었으면 종료
        if page >= total_pages:
            break

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": total_summary,
        "ridingCount": riding_count,
        "riderList": all_riders
    }


signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))


# ==============================================================================
# [메인 실행 루프]
# ==============================================================================
if __name__ == "__main__":
    log.info("🚀 [배민 데이터 통합 수집 스크립트] 가동 시작")
    fails = 0

    while True:
        try:
            payload = collect_all_data()
            resp = push_to_gas(payload)
            log.info(f"✔️ 데이터 수집 및 전송 완료 ({resp}) | 기사 수: {len(payload['riderList'])}명 | 운행중: {payload['ridingCount']}명")
            fails = 0

        except PermissionError as e:
            log.error(f"❌ {e}")
            time.sleep(120)

        except Exception as exc:
            log.error(f"⚠️ 시스템 오류: {exc}")
            fails += 1

        # 연속 실패 시 대기 시간 증가
        sleep_time = min(60 * fails, 600) if fails else get_interval()
        time.sleep(sleep_time)
