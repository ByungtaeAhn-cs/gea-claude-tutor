# -*- coding: utf-8 -*-
"""지도.py — GPS로 '들른 곳'을 묶고, 장소 이름 후보를 찾고, 일자별 동선 지도 PNG를 그립니다. (규약 2.2·4절)

  1. 묶기: GPS 사진·영상을 300m 안끼리 한 장소로(숙소처럼 여러 날 나온 곳도 한 장소). GPS 없는 사진은 같은 날
     앞뒤 사진 시각으로 장소를 '추정'(장소근거="시간추정") — 그래서 시계 보정을 먼저 해야 정확합니다.
  2. 이름 후보: OpenStreetMap Nominatim 역지오코딩 — 장소마다 1번, 결과는 캐시(여행/.캐시/nominatim.json),
     **초당 1회 이하**, 식별 가능한 User-Agent. 자동 이름은 틀릴 수 있어 '확인됨: false' → 질문 카드로 사람이 확정.
     (정책: https://operations.osmfoundation.org/policies/nominatim/ — 대량·자동완성·격자 조회 금지, 출처 표시)
  3. 집·숙소일 수 있는 곳은 **기본 숨김**(보안 검수 M4 — 판별이 빗나가도 공개되지 않게):
       · 저녁(18시~) 사진 다음 날 이후 아침(~9시) 사진이 있는 곳(숙소)
       · 밤(20시~)·이른 아침(~7시) 사진이 있는 곳(숙소·집일 수 있음 — 일출 명소도 여기 걸려 사람 확인 필요)
       · 첫날·마지막 날에 나오고 다른 장소와 30km 넘게 떨어진 곳(출발 전·귀가 후 집)
     → '숙소추정'·'비공개이유' 표시, 숨김=true(숨김출처=자동), 이름 조회 안 함(좌표를 밖에 보내지 않음), 지도·영상에서 뺌.
       사람이 질문 카드로 '공개해도 됨'을 고른 뒤에만 --장소 Lxx --공개 로 풀림. 여행정보.숨길장소(기본 ["숙소","집"]) 이름도 숨김.
     Nominatim 으로 보내는 좌표는 소수 4자리(약 11m).
  4. 지도: OSM 타일(캐시: 여행/.캐시/지도타일, 30일 지나면 새로) + 동선 선 + 번호, 아래쪽에 번호별 장소 이름,
     오른쪽 아래 '© OpenStreetMap contributors'. → 작업/지도/1일차.png …, 작업/지도/전체.png
  User-Agent는 도구/도구설정.json 의 {"지도_UserAgent": "…"} (또는 환경 변수 TRAVEL_STUDIO_USER_AGENT)로 바꿀 수 있습니다(개인 이메일 대신 단체 연락처 권장).

사용
  python 도구/지도.py --여행 2026-09_제주
  python 도구/지도.py --여행 2026-09_제주 --장소 L03 --이름 "숙소" --확인 --숨김   (화면에서 고친 것 반영 + 지도 다시)
  python 도구/지도.py --여행 2026-09_제주 --장소 L05 --이름 "광치기해변" --확인 --공개 --답변 q_20261008-0912_공개_L05
      (공개는 사람의 답이 있을 때만: --답변 <질문id> = 질문 카드 답 / --요청 <요청 파일> = 화면 ⑤ 숨김 해제)
  python 도구/지도.py --여행 2026-09_제주 --지도만                               (장소는 그대로, 지도만 다시 그리기)
  python 도구/지도.py --여행 2026-09_제주 --오프라인                             (이름 조회 없이 묶기·지도만)
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import (도구오류, 시각읽기, 원자적_쓰기, 인자틀, 읽기_json, 실행틀, 파일잠금, 필요, 한글글꼴, 설정읽기,  # noqa: E402
                 정렬키, 숨긴장소표, 사람이공개함)

기본UA = "GEA-ClaudeTutor-TravelStudio/1.0 (educational travel-blog helper; low-volume single-user desktop tool)"
묶음반경 = 300.0      # m (조사 권장 200~300m)
시간추정_양쪽 = 60     # 분: 앞뒤 사진이 같은 장소이고 둘 다 이 안이면
시간추정_가까움 = 20   # 분: 가장 가까운 GPS 사진이 이 안이면
밤시작, 새벽끝 = 20, 7  # 이 시각 사이 사진이 있는 장소는 기본 숨김(숙소·집일 수 있음)
일정밖km = 30.0        # 첫날·마지막 날 장소가 다른 장소들과 이만큼 넘게 떨어지면 '출발 전·귀가 후 집'일 수 있음
일차색 = ["#E8590C", "#1C7ED6", "#2F9E44", "#AE3EC9", "#F08C00", "#0CA678", "#E64980"]
출처문구 = "© OpenStreetMap contributors"


def 거리(a: dict, b: dict) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a["위도"]), math.radians(b["위도"])
    dp, dl = p2 - p1, math.radians(b["경도"] - a["경도"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# ───────────────────────────────────────────── Nominatim(초당 1회·캐시)
class 장소이름찾기:
    주소 = "https://nominatim.openstreetmap.org/reverse"

    def __init__(self, 캐시폴더: Path, UA: str, 연락처: str | None, 오프라인: bool, 로그):
        self.파일 = 캐시폴더 / "nominatim.json"
        self.UA, self.연락처, self.오프라인, self.로그 = UA, 연락처, 오프라인, 로그
        self.호출수, self.캐시사용 = 0, 0

    def 찾기(self, 위도: float, 경도: float) -> dict | None:
        키 = f"{위도:.4f},{경도:.4f},z18,poi,ko"
        캐시 = 읽기_json(self.파일, {}) or {}
        if 키 in (캐시.get("결과") or {}):
            self.캐시사용 += 1
            return 캐시["결과"][키]
        if self.오프라인:
            return None
        with 파일잠금(self.파일.with_name(".nominatim.lock"), 기다림=60, 이름="지도"):
            캐시 = 읽기_json(self.파일, {}) or {}
            if 키 in (캐시.get("결과") or {}):
                self.캐시사용 += 1
                return 캐시["결과"][키]
            쉼 = 1.1 - (time.time() - float(캐시.get("마지막호출") or 0))  # 다른 실행과 합쳐도 초당 1회 이하
            if 쉼 > 0:
                time.sleep(쉼)
            # layer=poi,natural: 길 이름보다 '협재해수욕장'·'동문시장' 같은 들른 곳 이름이 나올 가능성이 큼(주소 칸은 그대로 옴)
            질의 = {"format": "jsonv2", "lat": f"{위도:.4f}", "lon": f"{경도:.4f}", "zoom": "18",  # 소수 4자리(약 11m) — 필요 이상 정밀하게 보내지 않음
                  "layer": "poi,natural", "addressdetails": "1", "accept-language": "ko"}
            if self.연락처:
                질의["email"] = self.연락처
            req = urllib.request.Request(self.주소 + "?" + urllib.parse.urlencode(질의),
                                         headers={"User-Agent": self.UA, "Accept-Language": "ko"})
            결과 = None
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    결과 = json.loads(r.read().decode("utf-8"))
            except Exception as e:
                self.로그(f"Nominatim 조회 실패({위도:.4f},{경도:.4f}): {e}", "경고")
            self.호출수 += 1
            캐시["마지막호출"] = time.time()
            if 결과 is not None:
                캐시.setdefault("결과", {})[키] = 결과
            self.파일.parent.mkdir(parents=True, exist_ok=True)
            원자적_쓰기(self.파일, 캐시)
            return 결과


def 이름후보(결과: dict | None) -> tuple[str | None, list[str], str]:
    if not isinstance(결과, dict) or 결과.get("error"):
        return None, [], ""
    주소 = 결과.get("address") or {}
    후보 = []
    시설 = {"toilets", "parking", "parking_space", "parking_entrance", "bench", "waste_basket", "bicycle_parking",
          "vending_machine", "atm", "post_box", "telephone", "recycling", "drinking_water", "fuel", "charging_station"}
    if 결과.get("name") and 결과.get("type") not in 시설:
        후보.append(결과["name"])
    for k in ("tourism", "leisure", "natural", "amenity", "aeroway", "attraction", "historic"):
        if 주소.get(k) and 주소[k] not in 후보:
            후보.append(주소[k])
    작은 = next((주소[k] for k in ("village", "hamlet", "neighbourhood", "quarter", "suburb", "island") if 주소.get(k)), None)
    큰 = next((주소[k] for k in ("town", "city_district", "borough", "city", "county") if 주소.get(k)), None)
    동네 = " ".join(x for x in (큰, 작은) if x)
    if 동네 and 동네 not in 후보:
        후보.append(동네)
    return (후보[0] if 후보 else None), 후보, 결과.get("display_name") or ""


# ───────────────────────────────────────────── 묶기
def 묶기(gps항목: list[dict]) -> list[dict]:
    """시각순으로 보며, 가장 가까운 묶음 중심이 300m 안이면 그 묶음에(중심은 평균으로 갱신)."""
    묶음 = []
    for x in sorted(gps항목, key=정렬키):
        p = x["GPS"]
        가까운 = min(묶음, key=lambda g: 거리(g["중심"], p), default=None)
        if 가까운 and 거리(가까운["중심"], p) <= 묶음반경:
            가까운["항목"].append(x)
            n = len(가까운["항목"])
            가까운["중심"] = {"위도": (가까운["중심"]["위도"] * (n - 1) + p["위도"]) / n,
                         "경도": (가까운["중심"]["경도"] * (n - 1) + p["경도"]) / n}
        else:
            묶음.append({"중심": dict(p), "항목": [x]})
    return 묶음


def 비공개판정(항목들: list[dict], 첫날: int | None, 끝날: int | None, 가장가까운다른곳m: float | None) -> list[str]:
    """집·숙소일 수 있으면 이유 목록(비면 공개 후보). 기본을 숨김 쪽으로(빗나가도 공개되지 않게)."""
    이유 = []
    저녁, 아침, 밤새벽 = set(), set(), False
    일차들 = set()
    for x in 항목들:
        t = 시각읽기(x.get("촬영시각"))
        if x.get("일차") is not None:
            일차들.add(x["일차"])
        if t is None:
            continue
        if t.hour >= 밤시작 or t.hour < 새벽끝:
            밤새벽 = True
        if x.get("일차") is None:
            continue
        if t.hour >= 18:
            저녁.add(x["일차"])
        if t.hour < 9:
            아침.add(x["일차"])
    if any(a > e for a in 아침 for e in 저녁):
        이유.append("저녁 사진 다음 날 이후 아침 사진(숙소)")
    if 밤새벽:
        이유.append(f"밤 {밤시작}시 이후·아침 {새벽끝}시 이전 사진")
    if (일차들 & {첫날, 끝날}) and 가장가까운다른곳m is not None and 가장가까운다른곳m > 일정밖km * 1000:
        이유.append(f"첫날·마지막 날, 다른 장소와 {가장가까운다른곳m / 1000:.0f}km 떨어짐(출발 전·귀가 후 집일 수 있음)")
    return 이유


# ───────────────────────────────────────────── 그리기
class 캐시타일받기:
    """py-staticmaps 타일 받기 + 식별 UA + 30일 지난 캐시는 새로 + 받은 수 세기 + 받을 때마다 잠깐 쉼."""

    def __init__(self, staticmaps, UA: str):
        base = staticmaps.TileDownloader

        class _받기(base):
            def __init__(s):
                super().__init__()
                s.set_user_agent(UA)
                s.받음 = s.캐시 = s.실패 = 0

            def get(s, provider, cache_dir, zoom, x, y):
                f = s.cache_file_name(provider, cache_dir, zoom, x, y) if cache_dir else None
                if f and os.path.isfile(f):
                    if time.time() - os.path.getmtime(f) < 30 * 86400:
                        s.캐시 += 1
                        with open(f, "rb") as fh:
                            return fh.read()
                    os.remove(f)
                try:
                    data = super().get(provider, cache_dir, zoom, x, y)
                    s.받음 += 1
                    time.sleep(0.05)
                    return data
                except Exception:
                    s.실패 += 1
                    raise RuntimeError("타일 받기 실패")
        self.받기 = _받기()


def 지도그리기(staticmaps, 받기, 캐시폴더: Path, 경로들: list[tuple[list[dict], str]], 표시: list[tuple[dict, str, str]],
           범례: list[str], 파일: Path, 크기=(1200, 800)):
    """경로들: [(장소중심 목록, 색)], 표시: [(중심, 번호글, 색)], 범례: 줄 목록."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 크기
    ctx = staticmaps.Context()
    ctx.set_tile_provider(staticmaps.TileProvider("osm", url_pattern="https://tile.openstreetmap.org/$z/$x/$y.png",
                                                  attribution=None, max_zoom=19))
    ctx.set_tile_downloader(받기)
    ctx.set_cache_dir(str(캐시폴더 / "지도타일"))
    ll = lambda p: staticmaps.create_latlng(p["위도"], p["경도"])  # noqa: E731
    for 점들, 색 in 경로들:
        if len(점들) >= 2:
            ctx.add_object(staticmaps.Line([ll(p) for p in 점들], color=staticmaps.parse_color(색), width=4))
    모든점 = [p for p, _, _ in 표시]
    if not 모든점:
        return False
    lat = [p["위도"] for p in 모든점]
    lon = [p["경도"] for p in 모든점]
    import s2sphere
    rect = s2sphere.LatLngRect.from_point_pair(staticmaps.create_latlng(min(lat), min(lon)),
                                               staticmaps.create_latlng(max(lat), max(lon)))
    ctx.add_bounds(rect, extra_pixel_bounds=(70, 70, 70, 70))
    if len({(round(a, 3), round(b, 3)) for a, b in zip(lat, lon)}) == 1:
        ctx.set_zoom(14)  # 한 곳뿐이면 너무 확대하지 않음
    center, zoom = ctx.determine_center_zoom(W, H)
    if zoom is not None and zoom > 16:
        ctx.set_zoom(16)
        center, zoom = ctx.determine_center_zoom(W, H)
    그림 = ctx.render_pillow(W, H).convert("RGB")
    trans = staticmaps.Transformer(W, H, zoom, center, 256)
    글꼴경로 = 한글글꼴(True) or 한글글꼴()
    if not 글꼴경로:
        raise 도구오류("한글 글꼴을 찾지 못했어요(지도 번호·이름이 깨짐).")
    번호글꼴 = ImageFont.truetype(글꼴경로, 20)
    작은 = ImageFont.truetype(한글글꼴() or 글꼴경로, 15)
    범례글꼴 = ImageFont.truetype(한글글꼴() or 글꼴경로, 22)
    d = ImageDraw.Draw(그림, "RGBA")
    for p, 글, 색 in 표시:
        x, y = trans.ll2pixel(ll(p))
        r = 16 if len(글) <= 2 else 20
        d.ellipse((x - r, y - r, x + r, y + r), fill=색, outline="white", width=3)
        w = d.textlength(글, font=번호글꼴)
        d.text((x - w / 2, y - 12), 글, font=번호글꼴, fill="white")
    # 출처 표시(OSM 정책: 지도 위에 보이게)
    w = d.textlength(출처문구, font=작은)
    d.rectangle((W - w - 16, H - 26, W, H), fill=(255, 255, 255, 220))
    d.text((W - w - 8, H - 23), 출처문구, font=작은, fill=(30, 30, 30))
    # 범례(지도 아래 띠 — 지도 위 표시를 가리지 않게)
    줄높이 = 34
    띠 = Image.new("RGB", (W, 18 + 줄높이 * len(범례)), "white")
    dd = ImageDraw.Draw(띠)
    for k, 줄 in enumerate(범례):
        dd.text((16, 10 + k * 줄높이), 줄, font=범례글꼴, fill=(30, 30, 30))
    전체 = Image.new("RGB", (W, H + 띠.height), "white")
    전체.paste(그림, (0, 0))
    전체.paste(띠, (0, H))
    파일.parent.mkdir(parents=True, exist_ok=True)
    전체.save(파일, "PNG", optimize=True)
    return True


def 줄나누기(조각들: list[str], 최대: int = 46) -> list[str]:
    줄들, 현재 = [], ""
    for c in 조각들:
        if 현재 and len(현재) + len(c) + 3 > 최대:
            줄들.append(현재)
            현재 = "   " + c
        else:
            현재 = f"{현재} → {c}" if 현재.strip() else (현재 + c)
    if 현재:
        줄들.append(현재)
    return 줄들


# ───────────────────────────────────────────── 본문
def 공개근거확인(실, 장소ID: str, 답변id: str | None, 요청이름: str | None, 목록: list[dict]) -> dict:
    """--공개 를 허락하는 '사람의 답'을 확인. 둘 중 하나:
    ① --답변 <질문id>: 작업함/답변/<질문id>.json(서버만 사람 클릭으로 씀, Claude 는 Edit 금지)이 있고, 선택이 '공개'(숨김 아님)이며,
       그 질문 카드(작업함/질문/<질문id>.json)가 같은 여행이고, 카드에 보여 준 사진이 모두 이 장소 사진이며(장소ID 필드가 있으면 그것도 일치),
       답한 뒤에 카드가 바뀌지 않았을 것. (답변을 처리완료/로 옮기기 전에 실행)
    ② --요청 <요청 파일>: 화면 ⑤에서 사람이 숨김을 푼 '지도' 요청(서버가 씀)의 장소수정 항목에 이 장소ID·숨김 false·공개 true."""
    작업함 = 실.스튜디오 / "작업함"
    안전 = lambda s: bool(s) and not re.search(r'[\\/:*?"<>|\x00-\x1f]', s) and not s.startswith(".")  # noqa: E731
    if 답변id:
        if not 안전(답변id):
            raise 도구오류("--답변 에는 질문id 만 적어 주세요(경로 없이).")
        답파일 = 작업함 / "답변" / f"{답변id}.json"
        답 = 읽기_json(답파일)
        if not isinstance(답, dict):
            raise 도구오류(f"사람의 답이 없어요: 작업함/답변/{답변id}.json — 화면에서 질문 카드에 답한 뒤에만 공개할 수 있어요"
                         "(답변을 처리완료로 옮기기 전에 실행).", 코드=3)
        if 답.get("질문id") != 답변id:
            raise 도구오류("답변 파일의 질문id 가 맞지 않아요.", 코드=3)
        선택 = [str(s) for s in 답.get("선택") or []]
        if not 선택 or any("숨김" in s for s in 선택) or not any("공개" in s for s in 선택):
            raise 도구오류(f"사람의 답이 '공개'가 아니에요(선택: {선택 or '없음'}) — 숨김을 그대로 둬요.", 코드=3)
        q파일 = 작업함 / "질문" / f"{답변id}.json"
        q = 읽기_json(q파일)
        if not isinstance(q, dict):
            raise 도구오류(f"질문 카드가 없어요: 작업함/질문/{답변id}.json", 코드=3)
        if q.get("여행ID") and q["여행ID"] != 실.여행ID:
            raise 도구오류(f"다른 여행({q['여행ID']})의 질문이에요.", 코드=3)
        if q.get("장소ID") and q["장소ID"] != 장소ID:
            raise 도구오류(f"질문의 장소({q['장소ID']})와 --장소 {장소ID} 가 달라요.", 코드=3)
        사진장소 = {x.get("id"): x.get("장소ID") for x in 목록}
        보인곳 = {사진장소.get(i) for i in q.get("사진") or []}
        if not q.get("사진") or 보인곳 != {장소ID}:
            raise 도구오류(f"질문 카드에 보여 준 사진이 {장소ID} 의 사진이 아니에요({sorted(map(str, 보인곳))}) — "
                         "사람이 본 장소와 공개할 장소가 같아야 해요.", 코드=3)
        답시각 = 시각읽기(답.get("보낸시각"))
        if 답시각 and q파일.stat().st_mtime > 답시각.timestamp() + 2:
            raise 도구오류("답한 뒤에 질문 카드가 바뀌었어요 — 다시 물어 주세요.", 코드=3)
        return {"근거": "질문 답변", "질문id": 답변id, "선택": 선택, "답한시각": 답.get("보낸시각")}
    if 요청이름:
        이름 = Path(요청이름).name
        if not 안전(이름):
            raise 도구오류("--요청 에는 요청 파일 이름만 적어 주세요.")
        파일 = next((f for f in (작업함 / "요청" / 이름, 작업함 / "처리완료" / 이름) if f.is_file()), None)
        r = 읽기_json(파일) if 파일 else None
        if not isinstance(r, dict):
            raise 도구오류(f"요청 파일이 없어요: 작업함/요청/{이름}", 코드=3)
        if r.get("종류") != "지도" or (r.get("여행ID") and r["여행ID"] != 실.여행ID):
            raise 도구오류("이 여행의 '지도' 요청이 아니에요.", 코드=3)
        항목 = next((x for x in ((r.get("내용") or {}).get("장소수정") or []) if isinstance(x, dict) and x.get("장소ID") == 장소ID), None)
        if not 항목 or 항목.get("공개") is not True or 항목.get("숨김") is not False:
            raise 도구오류(f"화면 ⑤ 요청에 {장소ID} 의 숨김 해제(공개: true)가 없어요 — 숨김을 그대로 둬요.", 코드=3)
        return {"근거": "화면 ⑤ 숨김 해제", "요청id": r.get("id"), "요청파일": 이름, "보낸시각": r.get("보낸시각")}
    raise 도구오류("--공개 는 사람의 답이 있어야 해요: --답변 <질문id>(질문 카드) 또는 --요청 <요청 파일>(화면 ⑤ 숨김 해제).",
                 힌트="집·숙소 위치가 공개 글·지도에 나갈 수 있어 사람의 답 없이는 풀지 않아요.", 코드=3)


def 장소파일고치기(실, 고치기) -> dict:
    with 파일잠금(실.여행 / ".장소.lock", 이름="지도"):
        장소 = 읽기_json(실.여행 / "장소.json", {}) or {}
        고치기(장소)
        원자적_쓰기(실.여행 / "장소.json", 장소)
        return 장소


def 본문(실):
    인자 = 실.인자
    staticmaps = 필요("staticmaps")
    정보 = 실.정보()
    설정 = 설정읽기(실.스튜디오)
    UA = str(설정.get("지도_UserAgent") or 기본UA)
    캐시폴더 = 실.스튜디오 / "여행" / ".캐시"
    목록 = [x for x in 실.목록() if not x.get("원본없음")]
    요약 = {"정책": "Nominatim·OSM 타일 사용 정책을 지킴: 초당 1회 이하·결과 캐시·식별 UA·'© OpenStreetMap contributors' 표시·대량 조회 금지"}

    if 인자.장소:
        if 인자.숨김 and 인자.공개:
            raise 도구오류("--숨김 과 --공개 를 함께 쓸 수 없어요.")
        근거 = None
        if 인자.공개:  # 집·숙소 위치가 공개되는 방향 → 사람의 답(서버가 쓴 파일)이 있어야만
            근거 = 공개근거확인(실, 인자.장소, 인자.답변, 인자.요청, 목록)
        elif 인자.답변 or 인자.요청:
            raise 도구오류("--답변·--요청 은 --공개 와 함께 쓰는 거예요.")
        with 실.단계("장소 고치기") as 기록:
            def 고치기(장소):
                if 인자.장소 not in 장소:
                    raise 도구오류(f"장소.json 에 {인자.장소} 가 없어요.")
                p = 장소[인자.장소]
                if 인자.이름:
                    p["이름"] = 인자.이름
                if 인자.확인:
                    p["확인됨"] = True
                if 인자.숨김:
                    p.update({"숨김": True, "숨김출처": "사용자", "공개확인": False})
                    p.pop("공개근거", None)
                if 인자.공개:  # 위에서 사람의 답을 확인한 경우만
                    p.update({"숨김": False, "숨김출처": "사용자", "공개확인": True, "공개근거": 근거})
            장소 = 장소파일고치기(실, 고치기)
            기록["산출물"] = "장소.json"
            요약["고친장소"] = {인자.장소: 장소[인자.장소]}
        인자.지도만 = True

    if not 인자.지도만:
        with 실.단계("장소 묶기") as 기록:
            gps = [x for x in 목록 if isinstance(x.get("GPS"), dict) and x["GPS"].get("위도") is not None]
            묶음 = 묶기(gps)
            옛 = 읽기_json(실.여행 / "장소.json", {}) or {}
            쓰인 = {k for k in 옛}
            번호 = max([int(k[1:]) for k in 쓰인 if k[1:].isdigit()] or [0]) + 1
            배정, 새장소 = {}, {}
            for g in sorted(묶음, key=lambda g: 정렬키(g["항목"][0])):
                맞는 = min(((k, v) for k, v in 옛.items() if isinstance(v, dict) and v.get("중심")),
                         key=lambda kv: 거리(kv[1]["중심"], g["중심"]), default=None)
                if 맞는 and 거리(맞는[1]["중심"], g["중심"]) <= 묶음반경 and 맞는[0] not in 새장소:
                    pid = 맞는[0]
                else:
                    pid = f"L{번호:02d}"
                    번호 += 1
                새장소[pid] = g
                for x in g["항목"]:
                    배정[x["id"]] = (pid, "GPS")
            # GPS 없는 사진: 같은 날 앞뒤 GPS 사진 시각으로 추정
            날별 = defaultdict(list)
            for x in 목록:
                날별[x.get("일차")].append(x)
            for 일, xs in 날별.items():
                xs.sort(key=정렬키)
                for k, x in enumerate(xs):
                    if x["id"] in 배정 or x.get("촬영시각") is None:
                        continue
                    t = 시각읽기(x["촬영시각"])
                    앞 = next((y for y in reversed(xs[:k]) if y["id"] in 배정 and 배정[y["id"]][1] == "GPS"), None)
                    뒤 = next((y for y in xs[k + 1:] if y["id"] in 배정 and 배정[y["id"]][1] == "GPS"), None)
                    분 = lambda y: abs((시각읽기(y["촬영시각"]) - t).total_seconds()) / 60  # noqa: E731
                    if 앞 and 뒤 and 배정[앞["id"]][0] == 배정[뒤["id"]][0] and max(분(앞), 분(뒤)) <= 시간추정_양쪽:
                        배정[x["id"]] = (배정[앞["id"]][0], "시간추정")
                    else:
                        가까운 = min((y for y in (앞, 뒤) if y), key=분, default=None)
                        if 가까운 and 분(가까운) <= 시간추정_가까움:
                            배정[x["id"]] = (배정[가까운["id"]][0], "시간추정")
            # 비공개 판정에 쓸 것: 여행 첫날·마지막 날, 장소마다 가장 가까운 다른 장소까지 거리
            일차모두 = sorted({x["일차"] for x in 목록 if x.get("일차")})
            첫날, 끝날 = (일차모두[0], 일차모두[-1]) if 일차모두 else (None, None)
            가까운다른곳 = {pid: min((거리(g["중심"], h["중심"]) for q, h in 새장소.items() if q != pid), default=None)
                       for pid, g in 새장소.items()}
            기록["산출물"] = None
            실.알림(f"장소 {len(새장소)}곳으로 묶음 (GPS {len(gps)}개, 시간으로 추정 {sum(1 for v in 배정.values() if v[1] == '시간추정')}개)")

        with 실.단계("장소 이름 후보(Nominatim)") as 기록:
            찾기 = 장소이름찾기(캐시폴더, UA, 설정.get("지도_연락처"), 인자.오프라인, 실.로그)
            소속 = defaultdict(list)
            for i, (pid, _) in 배정.items():
                소속[pid].append(i)
            표 = {x["id"]: x for x in 목록}
            이름결과 = {}
            안보냄 = 0
            for pid, g in 새장소.items():
                항목들 = [표[i] for i in 소속[pid]]
                이유 = 비공개판정(항목들, 첫날, 끝날, 가까운다른곳.get(pid))
                옛것 = 옛.get(pid) or {}
                공개됨 = 사람이공개함(옛것)
                if (이유 or 옛것.get("숨김")) and not 공개됨:
                    # 집·숙소일 수 있는 곳은 좌표를 밖(Nominatim)에 보내지 않음 — 사람이 공개를 고른 뒤에만 조회
                    자리 = "숙소(추정)" if any("숙소" in r for r in 이유) else "비공개 장소(확인 필요)"
                    이름 = 옛것.get("이름") if 옛것.get("확인됨") else 자리
                    이름결과[pid] = (이름, 옛것.get("후보이름") or [이름], 옛것.get("주소") or "", 이유)
                    안보냄 += 1
                    continue
                if 옛것.get("확인됨") or (옛것.get("후보이름") and 옛것.get("주소")):
                    이름결과[pid] = (옛것.get("이름"), 옛것.get("후보이름") or [], 옛것.get("주소") or "", 이유)
                    continue
                c = g["중심"]
                이름, 후보, 주소 = 이름후보(찾기.찾기(c["위도"], c["경도"]))
                이름결과[pid] = (이름, 후보, 주소, 이유)
            요약["Nominatim"] = {"호출": 찾기.호출수, "캐시사용": 찾기.캐시사용, "UserAgent": UA,
                               "보내지않은비공개장소": 안보냄, "좌표자릿수": 4}
            기록["산출물"] = None

        with 실.단계("장소.json 저장") as 기록:
            def 고치기(장소):
                for pid, g in 새장소.items():
                    이름, 후보, 주소, 이유 = 이름결과[pid]
                    옛것 = 장소.get(pid) or {}
                    출처 = 옛것.get("숨김출처")
                    if 출처 == "사용자":                      # 사람이 정한 숨김·공개는 그대로
                        숨김 = bool(옛것.get("숨김"))
                    elif 이유 and not 사람이공개함(옛것):        # 기본 숨김(빗나가도 공개되지 않게)
                        숨김, 출처 = True, "자동"
                    elif 출처 == "자동":                      # 시계 보정 등으로 이유가 사라짐 → 자동 숨김만 풂
                        숨김, 출처 = False, None
                    else:
                        숨김 = bool(옛것.get("숨김"))
                    항목들 = [x for x in 목록 if 배정.get(x["id"], (None,))[0] == pid]
                    일차들 = sorted({x.get("일차") for x in 항목들 if x.get("일차")})
                    시각들 = sorted(str(x.get("촬영시각")) for x in 항목들 if x.get("촬영시각"))
                    새 = {
                        "이름": 옛것.get("이름") if 옛것.get("확인됨") else (이름 or "이름 모름"),
                        "확인됨": bool(옛것.get("확인됨")),
                        "중심": {"위도": round(g["중심"]["위도"], 6), "경도": round(g["중심"]["경도"], 6)},
                        "사진수": len(항목들),
                        "숨김": 숨김, "숨김출처": 출처, "공개확인": bool(옛것.get("공개확인")),
                        "후보이름": 후보, "주소": 주소, "숙소추정": bool(이유), "비공개이유": 이유,
                        "일차": 일차들, "첫시각": 시각들[0] if 시각들 else None, "끝시각": 시각들[-1] if 시각들 else None,
                    }
                    장소[pid] = {**옛것, **새}
                for pid, v in 장소.items():  # 이번에 사진이 없는 옛 장소는 지우지 않고 0장으로
                    if pid not in 새장소 and isinstance(v, dict):
                        v["사진수"] = 0
            장소 = 장소파일고치기(실, 고치기)
            고칠것 = {}
            for x in 목록:
                pid, 근거 = 배정.get(x["id"], (None, None))
                if x.get("장소ID") != pid or x.get("장소근거") != 근거:
                    고칠것[x["id"]] = {"장소ID": pid, "장소근거": 근거}
            요약["목록"] = 실.목록합치기(고칠것)
            기록["산출물"] = "장소.json"
        목록 = [x for x in 실.목록() if not x.get("원본없음")]
    else:
        장소 = 읽기_json(실.여행 / "장소.json", {}) or {}
        if not 장소:
            raise 도구오류("장소.json 이 아직 없어요. --지도만 없이 먼저 실행하세요.")

    with 실.단계("지도 그리기") as 기록:
        받기 = 캐시타일받기(staticmaps, UA).받기
        숨김표 = 숨긴장소표(장소, 정보)  # {장소ID: 이유} — 영상·발행패키지와 같은 규칙(_공통.py)
        폴더 = 실.여행 / "작업" / "지도"
        날별 = defaultdict(list)
        for x in sorted(목록, key=정렬키):
            if x.get("장소ID") in 장소 and x.get("일차"):
                날별[x["일차"]].append(x["장소ID"])
        만든, 빠진날 = [], []

        def 표시이름(pid):
            p = 장소[pid]
            return str(p.get("이름") or "이름 모름") + ("" if p.get("확인됨") else "(추정)")
        전체경로, 전체표시, 전체범례, 첫번호 = [], [], [], {}
        순번 = 0
        for 일 in sorted(날별):
            순서 = []
            for pid in 날별[일]:
                if pid in 숨김표:
                    continue
                if not 순서 or 순서[-1] != pid:
                    순서.append(pid)
            색 = 일차색[(일 - 1) % len(일차색)]
            if not 순서:
                빠진날.append(일)
                continue
            # 같은 장소가 하루에 두 번 나오면 번호를 함께 적음
            번호표 = defaultdict(list)
            for k, pid in enumerate(순서, 1):
                번호표[pid].append(str(k))
            표시 = [(장소[pid]["중심"], ",".join(번호표[pid]), 색) for pid in dict.fromkeys(순서)]
            범례 = [f"{일}일차 동선"] + 줄나누기([f"{k} {표시이름(pid)}" for k, pid in enumerate(순서, 1)])
            파일 = 폴더 / f"{일}일차.png"
            if 지도그리기(staticmaps, 받기, 캐시폴더, [([장소[p]["중심"] for p in 순서], 색)], 표시, 범례, 파일):
                만든.append(실.상대(파일))
            전체경로.append(([장소[p]["중심"] for p in 순서], 색))
            조각 = []
            for pid in 순서:
                순번 += 1
                if pid not in 첫번호:
                    첫번호[pid] = (순번, 색)
                조각.append(f"{순번} {표시이름(pid)}")
            전체범례 += 줄나누기([f"{일}일차: {조각[0]}"] + 조각[1:])
        if 첫번호:
            전체표시 = [(장소[pid]["중심"], str(n), 색) for pid, (n, 색) in 첫번호.items()]
            파일 = 폴더 / "전체.png"
            if 지도그리기(staticmaps, 받기, 캐시폴더, 전체경로, 전체표시, ["여행 전체 동선"] + 전체범례, 파일):
                만든.append(실.상대(파일))
        기록["산출물"] = 만든
        요약["타일"] = {"받음": 받기.받음, "캐시": 받기.캐시, "실패": 받기.실패}
        if 받기.실패:
            실.로그(f"지도 타일 {받기.실패}장을 받지 못함(빈칸으로 그려짐)", "경고")

    요약.update({
        "장소수": len(장소),
        "장소": {pid: {"이름": v.get("이름"), "확인됨": v.get("확인됨"), "사진수": v.get("사진수"), "숨김": v.get("숨김"),
                     "숙소추정": v.get("숙소추정"), "비공개이유": v.get("비공개이유") or None, "지도에서뺌": 숨김표.get(pid),
                     "후보이름": (v.get("후보이름") or [])[:3]} for pid, v in sorted(장소.items()) if isinstance(v, dict)},
        "장소모름": [x["id"] for x in 목록 if not x.get("장소ID")],
        "지도": 만든, "지도없는날": 빠진날,
        "다음할일": ["확인 안 된 장소 이름을 질문 카드로(사진 썸네일 포함, 3개 이하씩)",
                  "기본 숨김된 곳(비공개이유)은 질문 카드로 '숙소·집이에요(숨김 유지)' / '공개해도 돼요' — 공개를 고른 곳만 "
                  "--장소 Lxx --이름 … --확인 --공개",
                  "장소를 모르는 사진(GPS 없음·시간 추정 안 됨)은 콘택트 시트로 보고 묻기"],
    })
    return 실.끝(요약)


def main() -> int:
    ap = 인자틀("GPS 묶기 → 장소 이름 후보(Nominatim, 초당 1회·캐시) → 장소.json → 일자별 동선 지도 PNG",
              "예) python 도구/지도.py --여행 2026-09_제주\n"
              "정책: https://operations.osmfoundation.org/policies/nominatim/ , https://operations.osmfoundation.org/policies/tiles/")
    ap.add_argument("--지도만", action="store_true", help="장소.json 은 그대로 두고 지도만 다시 그리기")
    ap.add_argument("--오프라인", action="store_true", help="Nominatim 이름 조회 없이(캐시에 있는 것만) — 지도 타일도 캐시에 없으면 빈칸")
    ap.add_argument("--장소", help="고칠 장소ID(예: L03) — 화면에서 고친 이름·숨김 반영")
    ap.add_argument("--이름", help="--장소 의 새 이름")
    ap.add_argument("--확인", action="store_true", help="--장소 를 '확인됨'으로")
    ap.add_argument("--숨김", action="store_true", help="--장소 를 지도·글에서 숨기기(숙소·집)")
    ap.add_argument("--공개", "--보이기", dest="공개", action="store_true",
                    help="--장소 를 공개(기본 숨김을 풂). 사람의 답이 꼭 필요: --답변 또는 --요청 과 함께만 동작")
    ap.add_argument("--답변", metavar="질문id",
                    help="--공개 근거: 작업함/답변/<질문id>.json(사람이 화면에서 답함). 선택이 '공개'이고 그 카드의 사진이 이 장소여야 함")
    ap.add_argument("--요청", metavar="요청파일",
                    help="--공개 근거: 화면 ⑤에서 숨김을 푼 '지도' 요청 파일(작업함/요청/…json)의 장소수정 항목(공개: true)")
    return 실행틀("지도", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
