import subprocess, json, requests, time, logging, threading, sys, os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 80
CENTER_ID = "DP2511060448"

COOKIE = "dsid=8dff4928-c182-47d4-8772-e2a5a402a157; _wp_uid=1-b64e91cb5ed11a28894cc86e59e4b722-s1776862146.426964|windows_10|chrome-dy1hgz; tbid=6c55babc-a664-4fba-bace-5efe4648c258; _hjSessionUser_5123796=eyJpZCI6IjU3NGNiYzc4LWM4YjctNWI2Yy04MDg4LTcxZDFmYTc5ODVlZCIsImNyZWF0ZWQiOjE3NzY5NDk4MTgzNDEsImV4aXN0aW5nIjp0cnVlfQ==; _ga_QZ54WQ25KW=GS2.1.s1777119700$o2$g1$t1777119717$j43$l0$h0; _ga=GA1.1.1294575212.1776949812; _ga_DD6D4M7LEB=GS2.1.s1777119699$o2$g1$t1777119718$j41$l0$h0; _ga_BVQGVEDG55=GS2.1.s1777119687$o2$g1$t1777119728$j19$l0$h0; _ceo_v2_gk_sid=a0634d36-0886-4231-8074-8acd2a12657b; CENTER_SESSION=NDg0MjFlYjMtNjQ4Ny00OTUxLWJhNjMtM2Q4MWM0NmQwYTg2; __cf_bm=DT4FWbsqEWJFaixDax2ul7wZJotzE9e5LpMzdY3Zc3A-1786511676.58738-1.0.1.1-jcAKtGddzMLLsIzWE6msKMB5LoBidIv1nR0nAwp_h.ImiJ9zrViI0cgy1MpnzZkT7oZ1ckAR1o_Dx8MTOEs1w8FQhu7ZGQDVIIVv_i3fs98b_DcHjZmCSlKM30DB2eoOt1GUI5vDTTQnOMVac4Pf.Q; _ga_ZGDXE0V87X=GS2.1.s1786506922$o25$g1$t1786512423$j54$l0$h0"
BASE_API_URL = "https://api-deliverycenter.baemin.com/v4/management/delivery-status?size=100&orderName=name&orderBy=asc&name=&userId=&phoneNumber="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

LATEST_DATA = {}
DATA_LOCK = threading.Lock()
TARGETS = {"morning": [126,126,126,126,144,186,198], "afternoon": [120,120,120,120,126,132,132], "evening": [180,180,180,180,192,216,210], "night": [174,174,174,174,198,186,180]}
DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("app")

def safe_int(v):
    try: return int(v) if v is not None else 0
    except: return 0

def fetch_curl(url):
    cmd = ["curl", "-s", url, "-H", f"authority: api-deliverycenter.baemin.com", "-H", "accept: application/json", "-H", f"center-id: {CENTER_ID}", "-H", f"cookie: {COOKIE}", "-H", f"user-agent: {UA}", "--compressed"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout

def collect_loop():
    global LATEST_DATA
    log.info("🚀 [통합 수집 엔진] 가동 시작")
    while True:
        try:
            page, all_riders, total_summary, riding_count = 0, [], {}, 0
            while True:
                raw = fetch_curl(f"{BASE_API_URL}&page={page}")
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
    times = {"morning_end": 14 if is_weekend else 13, "afternoon_end": 17, "evening_end": 24}
    if 9 <= hour < times["morning_end"]: active_slot = "morning"
    elif times["morning_end"] <= hour < times["afternoon_end"]: active_slot = "afternoon"
    elif times["afternoon_end"] <= hour < times["evening_end"]: active_slot = "evening"
    else: active_slot = "night"
    targets = {"morning": round(TARGETS["morning"][day_idx]), "afternoon": round(TARGETS["afternoon"][day_idx]), "evening": round(TARGETS["evening"][day_idx]), "night": round(TARGETS["night"][day_idx])}
    return {"dayName": DAY_NAMES[day_idx], "dayIdx": day_idx, "activeSlot": active_slot, "updatedAt": data.get("time", "-"), "total": data.get("total", {}), "targets": targets, "times": times, "ridingCount": data.get("ridingCount", 0), "riderList": data.get("riderList", []), "isCustom": False, "baseTargets": TARGETS, "setCount": 6}

HTML_CODE = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>초곡 기지국</title><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"><style>*{box-sizing:border-box;margin:0;padding:0;}body{background:#000;color:#fff;font-family:-apple-system,sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden;user-select:none;}.header{background:#1c1c1e;padding:3vw 4vw;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #333;}.btn{border:none;padding:2.5vw 4vw;border-radius:10px;font-weight:900;font-size:4vw;cursor:pointer;}.card-container{flex:1;display:flex;flex-direction:column;gap:2px;padding:2px;}.card{flex:1;display:flex;flex-direction:column;justify-content:center;background:#111;padding:3vw 5vw;border-radius:6px;border:1px solid #222;}.card.active{border:2.5px solid #fff;background:#1a1a1a;}.total-section{background:#000;padding:4vw 5vw;border-top:1px solid #333;}.rider-modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:#000;color:#fff;z-index:1000;flex-direction:column;}.rider-header{background:#1c1c1e;padding:3vw 4vw;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #333;}.table-wrapper{flex:1;overflow:auto;background:#000;}.rider-table{width:max-content;border-collapse:collapse;font-size:3.2vw;color:#ddd;}.rider-table th,.rider-table td{padding:2vw 2.5vw;text-align:center;border:1px solid #222;white-space:nowrap;background:#111;}.rider-table th{background:#1c1c1e;color:#bbb;cursor:pointer;}.sticky-name{position:sticky;left:0;z-index:5;background:#1c1c1e !important;border-right:2px solid #444 !important;font-weight:bold;color:#fff !important;}td.sticky-name{background:#161616 !important;}.sum-row td{background:#222 !important;font-weight:900;color:#34C759;position:sticky;top:0;z-index:4;}.sum-row td.sticky-name{z-index:6;background:#222 !important;}.status-badge{padding:0.6vw 2vw;border-radius:12px;font-size:2.8vw;font-weight:700;display:inline-block;}.status-delivering{background:#0a3a1a;color:#34C759;}.status-ready{background:#222;color:#888;}</style></head><body>
<div id='security-login-screen' style='position:fixed;top:0;left:0;width:100vw;height:100vh;background:#000;z-index:999999;display:flex;flex-direction:column;justify-content:center;align-items:center;'><div style='background:#1c1c1e;padding:8vw 6vw;border-radius:16px;border:1px solid #333;text-align:center;width:80%;max-width:350px;'><div style='font-size:6vw;font-weight:900;color:#34C759;margin-bottom:2vw;'>🛡️ 기지국 접속</div><input type='password' id='pwd' placeholder='비밀번호' style='width:100%;padding:4vw;margin-bottom:5vw;background:#000;color:#fff;border:1px solid #444;border-radius:8px;font-size:5vw;text-align:center;' onkeypress='if(event.keyCode===13) unlock()'><button onclick='unlock()' style='width:100%;padding:4vw;background:#34C759;color:#000;border:none;border-radius:8px;font-size:4.5vw;font-weight:bold;'>열기</button></div></div>
<div class='header'><div style='display:flex;align-items:center;gap:1.5vw;'><div id='dayName' style='font-size:7.5vw;font-weight:900;'></div><div id='ridingCount' onclick='openRiders()' style='background:#2c2c2e;color:#34C759;font-size:3.8vw;font-weight:900;padding:1.5vw 2.5vw;border-radius:8px;cursor:pointer;'>🛵 -명</div></div><div><button class='btn' style='background:#3a3a3c;color:#fff;' onclick='loadData()'>🔄 갱신</button></div></div>
<div id='cards' class='card-container'></div>
<div class='total-section' style='text-align:right;'><div style='color:#666;font-size:3.5vw;font-weight:bold;'>오늘 합계 (SLA 09~24시)</div><div id='totalDone' style='font-size:16vw;font-weight:900;line-height:1;'>-</div><div id='updatedAt' style='color:#444;font-size:3vw;margin-top:6px;'></div></div>
<div id='riderModal' class='rider-modal'><div style='height:100vh;display:flex;flex-direction:column;'><div class='rider-header'><div style='font-size:4.2vw;font-weight:900;color:#34C759;'>🛵 기사 상세 현황</div><button class='btn' style='background:#3a3a3c;color:#fff;' onclick='closeRiders()'>✕ 닫기</button></div><div class='table-wrapper'><table class='rider-table'><thead id='riderTableHead'></thead><tbody id='riderTableBody'></tbody></table></div></div></div>
<script>
var COLORS={morning:'#FF9500',afternoon:'#34C759',evening:'#FF3B30',night:'#AF52DE'},NAMES={morning:'아침/점심피크',afternoon:'오후논피크',evening:'저녁피크',night:'심야'},ORDER=['morning','afternoon','evening','night'],KEYS={morning:'totalMorningCompleted',afternoon:'totalLunchCompleted',evening:'totalDinnerCompleted',night:'totalNightCompleted'};
var currentData=null,statusFilter='DELIVERING',sortCol='allDay',sortAsc=false;
function unlock(){if(document.getElementById('pwd').value==='8289')document.getElementById('security-login-screen').style.display='none';}
function render(d){currentData=d;document.getElementById('dayName').textContent=d.dayName+'요일';document.getElementById('updatedAt').textContent='신호: '+d.updatedAt;var activeRiders=d.riderList?d.riderList.filter(function(r){var st=r.status?(r.status.code||r.status):'DELIVERING';return st==='DELIVERING';}).length:0;document.getElementById('ridingCount').textContent='🛵 '+activeRiders+'명';var total=d.total||{},html='',totalDone=0;ORDER.forEach(function(id){var target=d.targets[id]||0,done=total[KEYS[id]]||0;totalDone+=done;var remain=Math.max(target-done,0),isActive=id===d.activeSlot,isDone=done>=target;html+='<div class="card '+(isActive?'active':'')+'"><div style="display:flex;justify-content:space-between;align-items:center;"><div><div style="font-size:6vw;font-weight:900;color:'+(isActive?COLORS[id]:'#555')+'">'+NAMES[id]+'</div><div style="display:flex;gap:20px;margin-top:10px;"><div style="text-align:center;"><div style="font-size:1.8rem;font-weight:900;">'+target+'</div><div style="color:#bbb;font-size:0.8rem;">목표</div></div><div style="text-align:center;"><div style="font-size:1.8rem;font-weight:900;">'+done+'</div><div style="color:#bbb;font-size:0.8rem;">달성</div></div></div></div><div style="text-align:right;"><div style="font-size:'+(isDone?'2rem':'4.5rem')+';font-weight:900;">'+(isDone?'달성완료':remain)+'</div></div></div></div>';});document.getElementById('cards').innerHTML=html;document.getElementById('totalDone').textContent=totalDone;}
function toggleSort(c){if(sortCol===c)sortAsc=!sortAsc;else{sortCol=c;sortAsc=false;}updateRiderTableHTML();}
function toggleStatusFilter(){statusFilter=(statusFilter==='DELIVERING')?'READY':'DELIVERING';updateRiderTableHTML();}
function updateRiderTableHTML(){if(!currentData||!currentData.riderList)return;var stLabel=statusFilter==='DELIVERING'?' (운행중만)':' (운행종료만)';var thead='<tr><th rowspan="2" class="sticky-name" onclick="toggleSort(\'name\')">이름</th><th rowspan="2" onclick="toggleStatusFilter()" style="color:#34C759;">운행상태'+stLabel+'</th><th rowspan="2">아이디</th><th rowspan="2">휴대폰번호</th><th rowspan="2" onclick="toggleSort(\'allDay\')" style="background:#003366;color:#66b2ff;">총 배달완료</th><th colspan="4">SLA 배달완료</th><th colspan="4">SLA 거절</th><th colspan="4">SLA 배차취소</th><th colspan="4">SLA 배달취소</th><th colspan="5">SLA 슬롯별</th><th rowspan="2">SLA 시간외</th><th colspan="24">시간대별 배달완료</th></tr><tr><th>푸드</th><th>비마트</th><th>스토어</th><th>합계</th><th>합계</th><th>푸드</th><th>비마트</th><th>스토어</th><th>합계</th><th>푸드</th><th>비마트</th><th>스토어</th><th>합계</th><th>푸드</th><th>비마트</th><th>스토어</th><th>아점</th><th>오후</th><th>저녁</th><th>심야</th><th>합계</th><th>6시</th><th>7시</th><th>8시</th><th>9시</th><th>10시</th><th>11시</th><th>12시</th><th>13시</th><th>14시</th><th>15시</th><th>16시</th><th>17시</th><th>18시</th><th>19시</th><th>20시</th><th>21시</th><th>22시</th><th>23시</th><th>0시</th><th>1시</th><th>2시</th><th>3시</th><th>4시</th><th>5시</th></tr>';var list=currentData.riderList.filter(function(r){var st=r.status?(r.status.code||r.status):'READY';if(statusFilter==='DELIVERING'&&st!=='DELIVERING')return false;if(statusFilter==='READY'&&st==='DELIVERING')return false;return true;});list.sort(function(a,b){var accA=a.acceptance||{},accB=b.acceptance||{};var vA=sortCol==='name'?a.name:accA.allDayComplete||0,vB=sortCol==='name'?b.name:accB.allDayComplete||0;return sortAsc?(vA>vB?1:-1):(vA<vB?1:-1);});var sumAllDay=0,sumCompTotal=0,sumRejTotal=0,sumCanTotal=0,sumFaultTotal=0,sumPeakTot=0,sumSlaOut=0,sumHourly=new Array(24).fill(0),rows='';list.forEach(function(r){var acc=r.acceptance||{},pt=r.peakTime||{},st=r.status?(r.status.code||r.status):'READY',stDesc=(r.status&&r.status.desc)?r.status.desc:(st==='DELIVERING'?'운행중':'운행 종료'),badgeClass=st==='DELIVERING'?'status-delivering':'status-ready';var allDay=acc.allDayComplete!==undefined?acc.allDayComplete:(acc.totalComplete||0),cTot=acc.totalComplete||0,rTot=acc.totalReject||0,canTot=acc.totalCancel||0,fTot=acc.totalRiderFault||0,pTot=(pt.morning||0)+(pt.afternoon||0)+(pt.evening||0)+(pt.midnight||0),sOut=acc.slaOutComplete||0;sumAllDay+=allDay;sumCompTotal+=cTot;sumRejTotal+=rTot;sumCanTotal+=canTot;sumFaultTotal+=fTot;sumPeakTot+=pTot;sumSlaOut+=sOut;rows+='<tr><td class="sticky-name">'+r.name+'</td><td><span class="status-badge '+badgeClass+'">'+stDesc+'</span></td><td>'+(r.userId||'-')+'</td><td>'+(r.phoneNumber||'-')+'</td><td style="font-weight:900;color:#66b2ff;background:#002244;">'+allDay+'</td><td>'+(acc.foodComplete||0)+'</td><td>'+(acc.bmartComplete||0)+'</td><td>'+(acc.storeComplete||0)+'</td><td style="font-weight:bold;">'+cTot+'</td><td style="font-weight:bold;color:#FF3B30;">'+rTot+'</td><td>'+(acc.foodReject||0)+'</td><td>'+(acc.bmartReject||0)+'</td><td>'+(acc.storeReject||0)+'</td><td style="font-weight:bold;">'+canTot+'</td><td>'+(acc.foodCancel||0)+'</td><td>'+(acc.bmartCancel||0)+'</td><td>'+(acc.storeCancel||0)+'</td><td style="font-weight:bold;">'+fTot+'</td><td>'+(acc.foodRiderFault||0)+'</td><td>'+(acc.bmartRiderFault||0)+'</td><td>'+(acc.storeRiderFault||0)+'</td><td>'+(pt.morning||0)+'</td><td>'+(pt.afternoon||0)+'</td><td>'+(pt.evening||0)+'</td><td>'+(pt.midnight||0)+'</td><td style="font-weight:bold;">'+pTot+'</td><td>'+sOut+'</td>';var hArr=r.hourlyCompleted||[],hMap={};hArr.forEach(function(i){hMap[i.hour]=i.count;});for(var h=6;h<=29;h++){var targetH=h>=24?h-24:h,val=hMap[targetH]!==undefined?hMap[targetH]:0;sumHourly[h-6]+=val;rows+='<td>'+val+'</td>';}rows+='</tr>';});var sumRow='<tr class="sum-row"><td class="sticky-name">합계</td><td>-</td><td>-</td><td>-</td><td style="color:#66b2ff;">'+sumAllDay+'</td><td>-</td><td>-</td><td>-</td><td>'+sumCompTotal+'</td><td>'+sumRejTotal+'</td><td>-</td><td>-</td><td>-</td><td>'+sumCanTotal+'</td><td>-</td><td>-</td><td>-</td><td>'+sumFaultTotal+'</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>'+sumPeakTot+'</td><td>'+sumSlaOut+'</td>';for(var i=0;i<24;i++)sumRow+='<td>'+sumHourly[i]+'</td>';sumRow+='</tr>';document.getElementById('riderTableHead').innerHTML=thead+sumRow;document.getElementById('riderTableBody').innerHTML=rows||'<tr><td colspan="45" style="padding:10vw;">데이터가 없습니다.</td></tr>';}
function openRiders(){updateRiderTableHTML();document.getElementById('riderModal').style.display='flex';}
function closeRiders(){document.getElementById('riderModal').style.display='none';}
function loadData(){fetch('/api/data').then(function(res){return res.json();}).then(function(d){render(d);if(document.getElementById('riderModal').style.display==='flex')updateRiderTableHTML();});}
loadData();setInterval(loadData,60000);
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/data":
            body = json.dumps(get_processed_data(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML_CODE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
    def log_message(self, format, *args): return

if __name__ == "__main__":
    threading.Thread(target=collect_loop, daemon=True).start()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
