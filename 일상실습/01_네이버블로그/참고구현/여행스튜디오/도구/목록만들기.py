# -*- coding: utf-8 -*-
"""목록만들기.py — 원본 사진·영상을 훑어 목록.json 과 미리보기·썸네일을 만듭니다. (규약 2.2·4절)

하는 일
  1. 여행정보.json 의 원본폴더를 훑기(원본은 읽기만 — 고치거나 옮기지 않음)
  2. 사진 EXIF(촬영 시각·시간대·GPS·기기), 영상 생성 시각(UTC인지 현지인지 판별)·길이·위치 읽기
     시각을 못 읽으면 파일 이름 → 파일 수정 시각 순으로. 어떤 출처를 썼는지 '시각출처'에 남김
  3. 기기보정초(시계 오차)를 더해 촬영시각·일차 계산(하루경계 기본 04:00)
  4. HEIC 포함 미리보기 JPG(장변 1600)·썸네일(320) → 작업/미리보기, 작업/썸네일
  5. 목록.json 저장 — 다시 만들어도 같은 원본은 같은 id, '사용자결정'·점수·판정·장소는 그대로 둠
  Live Photo(사진과 이름이 같은 3초 남짓 MOV)는 사진만 남깁니다.

사용
  python 도구/목록만들기.py --여행 2026-09_제주
  python 도구/목록만들기.py --여행 2026-09_제주 --미리보기다시   (미리보기를 모두 새로)
마지막 줄 JSON: 사진·영상 수, 기기별 수, 시각출처별 수, 약한 시각 목록, 영상 시각 변환, 일차별 수, 다음 할 일
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import (도구오류, 기준날짜, 강한출처, 시각읽기, 시간대, 오프셋글, 인자틀, 일차계산,  # noqa: E402
                 실행틀, 필요)
import _사진 as 사진  # noqa: E402

카메라제조사 = ("canon", "nikon", "fujifilm", "panasonic", "olympus", "om digital", "ricoh", "pentax", "leica",
          "gopro", "dji", "insta360", "hasselblad", "sigma", "kodak", "casio")
파일명시각 = re.compile(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])[ _T-]?([01]\d|2[0-3])[-_.:h]?([0-5]\d)[-_.:m]?([0-5]\d)(\d{3})?")


def 카메라인가(제조사: str | None, 모델: str | None) -> bool:
    m, mo = (제조사 or "").lower(), (모델 or "").upper()
    if any(k in m for k in 카메라제조사):
        return True
    return m.startswith("sony") and mo.startswith(("ILCE", "DSC", "NEX", "ZV", "SLT", "ILME"))


def 파일명에서(이름: str):
    m = 파일명시각.search(이름)
    if not m:
        return None, None
    try:
        t = datetime(*(int(m.group(i)) for i in range(1, 7)))
    except ValueError:
        return None, None
    ms = int(m.group(7)) if m.group(7) else 0
    return t, ms


def 기간채움과점검(기간: dict, 날들: list) -> tuple[dict, str | None]:
    """사람이 적은 기간은 덮어쓰지 않음. 빈 칸만 사진 날짜로 채우되 시작>끝이 되면 채우지 않음.
    돌려주는 값: (채울 것, 사람에게 보일 문제 안내 또는 None). `날들`은 정렬된 date 목록."""
    def 읽기(v):
        try:
            return date.fromisoformat(str(v)[:10]) if v else None
        except ValueError:
            return None
    시작, 끝 = 읽기(기간.get("시작")), 읽기(기간.get("끝"))
    채움 = {}
    if 날들:
        if not 기간.get("시작") and (끝 is None or 날들[0] <= 끝):
            채움["시작"], 시작 = 날들[0].isoformat(), 날들[0]
        if not 기간.get("끝") and (시작 is None or 날들[-1] >= 시작):
            채움["끝"], 끝 = 날들[-1].isoformat(), 날들[-1]
    고치기 = "화면에서 ‘기간 고치기’로 여행 기간을 고친 뒤 ‘사진 목록 다시 만들어 달라기’를 눌러 주세요"
    문제 = None
    if 시작 and 끝 and 시작 > 끝:
        문제 = f"여행 기간의 시작({시작})이 끝({끝})보다 뒤예요 — {고치기}"
    elif 날들:
        사진 = f"{날들[0]}~{날들[-1]}"
        if 시작 and 시작 > 날들[-1]:
            문제 = f"여행 기간 시작({시작})이 사진 날짜({사진})보다 뒤예요 — {고치기}"
        elif 끝 and 끝 < 날들[0]:
            문제 = f"여행 기간 끝({끝})이 사진 날짜({사진})보다 앞이에요 — {고치기}"
    return 채움, 문제


def 영상메타(경로: Path) -> dict:
    av = 필요("av")
    결과 = {"길이": None, "태그": {}, "오류": None}
    try:
        with av.open(str(경로)) as c:
            태그 = {str(k).lower(): str(v) for k, v in (c.metadata or {}).items()}
            for s in c.streams:
                for k, v in (s.metadata or {}).items():
                    태그.setdefault(str(k).lower(), str(v))
            결과["태그"] = 태그
            if c.duration:
                결과["길이"] = round(c.duration / 1_000_000, 2)
            elif c.streams.video and c.streams.video[0].duration:
                s = c.streams.video[0]
                결과["길이"] = round(float(s.duration * s.time_base), 2)
            결과["소리"] = bool(c.streams.audio)
    except Exception as e:
        결과["오류"] = f"{type(e).__name__}: {e}"
    return 결과


def ISO6709(글: str | None):
    if not 글:
        return None
    m = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", 글.strip())
    if not m:
        return None
    위, 경 = float(m.group(1)), float(m.group(2))
    if abs(위) < 1e-9 and abs(경) < 1e-9:
        return None
    return {"위도": round(위, 6), "경도": round(경, 6)}


def 영상장면(경로: Path, 길이: float | None):
    """영상의 1초쯤 화면 한 장(PIL)."""
    av = 필요("av")
    사진.준비()
    with av.open(str(경로)) as c:
        s = c.streams.video[0]
        목표 = min(1.0, (길이 or 3) / 3)
        try:
            c.seek(int(목표 * 1_000_000))
        except Exception:
            pass
        for f in c.decode(s):
            im = f.to_image()
            각 = getattr(f, "rotation", 0) or 0
            if 각 in (90, -90, 180, 270, -270):
                im = im.rotate(각, expand=True)
            return im.convert("RGB")
    return None


def 미리보기만들기(항목: dict, 원본: Path, 여행: Path, 다시: bool) -> str:
    """'만듦' / '그대로' / '실패:…'"""
    큰 = 여행 / 항목["미리보기"]
    작은 = 여행 / 항목["썸네일"]
    try:
        기준 = 원본.stat().st_mtime
        if not 다시 and 큰.is_file() and 작은.is_file() and 큰.stat().st_mtime >= 기준 and 작은.stat().st_mtime >= 기준:
            return "그대로"
        if 항목["종류"] == "영상":
            im = 영상장면(원본, 항목.get("영상길이초"))
            if im is None:
                return "실패: 영상 화면을 읽지 못함"
            im.thumbnail((1600, 1600), 사진.Image.LANCZOS)
        else:
            im = 사진.열기(원본, 최대변=1600)
        큰.parent.mkdir(parents=True, exist_ok=True)
        작은.parent.mkdir(parents=True, exist_ok=True)
        im.save(큰, "JPEG", quality=88, optimize=True)
        t = im.copy()
        t.thumbnail((320, 320), 사진.Image.LANCZOS)
        t.save(작은, "JPEG", quality=82, optimize=True)
        return "만듦"
    except Exception as e:
        return f"실패: {type(e).__name__}: {e}"


def 본문(실):
    인자 = 실.인자
    정보 = 실.정보()
    tz = 시간대(정보)
    원본들 = [Path(p).expanduser() for p in (정보.get("원본폴더") or [])]
    if not 원본들:
        raise 도구오류("여행정보.json 에 원본폴더가 없어요.", 힌트="화면의 [새 여행 만들기]에서 사진 폴더를 고르세요.")
    for r in 원본들:
        if not r.is_dir():
            raise 도구오류(f"원본 폴더를 찾지 못했어요: {r}", 힌트="외장 디스크가 연결돼 있는지, 폴더를 옮기지 않았는지 확인하세요.")
        try:
            실.여행.resolve().relative_to(r.resolve())
            raise 도구오류("여행 폴더가 원본 폴더 안에 있어요. 원본을 건드리지 않게 다른 곳에 두세요.")
        except ValueError:
            pass
    보정표 = {str(k): int(v) for k, v in (정보.get("기기보정초") or {}).items()}

    # 1. 훑기 ─────────────────────────────────────────────
    with 실.단계("원본 훑기") as 기록:
        파일들, 건너뜀 = [], Counter()
        for 루트 in 원본들:
            for 폴더, 하위, 이름들 in os.walk(루트):
                하위[:] = sorted(d for d in 하위 if not d.startswith("."))
                for 이름 in sorted(이름들):
                    p = Path(폴더) / 이름
                    확 = p.suffix.lower()
                    if 이름.startswith("."):
                        continue
                    if 확 in 사진.사진확장자 or 확 in 사진.영상확장자:
                        파일들.append((루트, p))
                    elif 확 in 사진.RAW확장자:
                        건너뜀["RAW(같은 이름 JPEG 사용)" if any((p.with_suffix(x)).exists() for x in (".JPG", ".jpg", ".jpeg", ".JPEG")) else "RAW(아직 다루지 않음)"] += 1
                    else:
                        건너뜀[f"사진·영상 아님({확 or '확장자 없음'})"] += 1
        기록["산출물"] = None
        실.알림(f"원본 {len(파일들)}개 찾음 (사진·영상 아닌 파일 {sum(건너뜀.values())}개는 건너뜀)")
    if not 파일들:
        raise 도구오류("원본 폴더에 사진·영상이 없어요.", 자료={"건너뜀": dict(건너뜀)})

    # 2. 메타 읽기 ─────────────────────────────────────────
    with 실.단계("메타 읽기"):
        사진.준비()
        메타 = {}

        def 읽기(쌍):
            루트, p = 쌍
            if p.suffix.lower() in 사진.영상확장자:
                return p, {"종류": "영상", **영상메타(p)}
            return p, {"종류": "사진", **사진.exif읽기(p)}
        with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4))) as ex:
            for p, m in ex.map(읽기, 파일들):
                메타[p] = m
        루트표 = {p: r for r, p in 파일들}

        # 기기 이름: 원본 하위 폴더 이름(없으면 EXIF 제조사·모델)
        def 기기(p: Path, m: dict) -> str:
            rel = p.relative_to(루트표[p])
            if len(rel.parts) > 1:
                return rel.parts[0]
            mk, mo = m.get("제조사") or m.get("태그", {}).get("com.apple.quicktime.make"), m.get("모델") or m.get("태그", {}).get("com.apple.quicktime.model")
            return " ".join(x for x in (mk, mo) if x) or "기타"
        기기표 = {p: 기기(p, m) for p, m in 메타.items()}
        # 기기마다 사진의 제조사·모델 → 영상 시각 판별(폰=UTC, 카메라=현지)과 '모델' 채우기
        기기모델 = defaultdict(Counter)
        for p, m in 메타.items():
            if m["종류"] == "사진" and (m.get("제조사") or m.get("모델")):
                기기모델[기기표[p]][(m.get("제조사") or "", m.get("모델") or "")] += 1

        # Live Photo: 같은 폴더·같은 이름의 사진이 있고 3.5초 이하인 영상 → 사진만
        사진이름 = {(p.parent, p.stem.lower()) for p, m in 메타.items() if m["종류"] == "사진"}
        라이브 = [p for p, m in 메타.items() if m["종류"] == "영상" and (p.parent, p.stem.lower()) in 사진이름
                and (m.get("길이") or 99) <= 3.5]
        for p in 라이브:
            메타.pop(p)

    # 3. 시각 정하기 ────────────────────────────────────────
    def 시각정하기(p: Path, m: dict):
        """→ (기록시각 글, 시각출처, 기준시각 aware, 메모)"""
        if m["종류"] == "사진":
            if m.get("촬영"):
                naive = datetime.fromisoformat(m["촬영"])
                if m.get("오프셋"):
                    return m["촬영"], "EXIF+Offset", 시각읽기(m["촬영"] + m["오프셋"]), None
                if m.get("GPS시각"):  # GPS(UTC)와의 차이가 15분 단위면 그 시간대로(카메라 시계 오차와 섞이면 쓰지 않음)
                    차분 = (naive - m["GPS시각"].replace(tzinfo=None)).total_seconds() / 60
                    가까운 = round(차분 / 15) * 15
                    if abs(차분 - 가까운) <= 2 and abs(가까운) <= 14 * 60:
                        오프 = timezone(timedelta(minutes=가까운))
                        return m["촬영"], "EXIF+Offset", naive.replace(tzinfo=오프), "시간대는 GPS 시각으로 계산"
                return m["촬영"], "EXIF", naive.replace(tzinfo=tz), None
        else:
            태그 = m.get("태그") or {}
            애플 = 시각읽기(태그.get("com.apple.quicktime.creationdate"))
            utc = 시각읽기(태그.get("creation_time"))
            if 애플 is not None and 애플.tzinfo is not None:
                메모 = None
                if utc is not None and utc.tzinfo is not None and abs((애플 - utc).total_seconds()) > 120:
                    메모 = f"creation_time(UTC) {태그.get('creation_time')} 과 {abs((애플 - utc).total_seconds()) / 60:.0f}분 다름"
                return 태그["com.apple.quicktime.creationdate"], "영상현지", 애플, 메모
            if utc is not None and utc.year > 1971:
                제조사 = 태그.get("com.apple.quicktime.make") or 태그.get("make") or ""
                모델 = 태그.get("com.apple.quicktime.model") or 태그.get("model") or ""
                if not 제조사 and 기기모델.get(기기표[p]):
                    제조사, 모델 = 기기모델[기기표[p]].most_common(1)[0][0]
                오프셋태그 = 태그.get("samsung.android.utc_offset") or 태그.get("com.android.utc_offset")
                if 카메라인가(제조사, 모델) and not 오프셋태그:
                    # 카메라·액션캠은 creation_time 칸에 현지 시각을 넣는 경우가 많음
                    return 태그["creation_time"], "영상현지", utc.replace(tzinfo=None).replace(tzinfo=tz), "카메라 영상: 기록 시각을 현지 시각으로 봄"
                return 태그["creation_time"], "영상UTC", utc.astimezone(timezone.utc), None
        t, ms = 파일명에서(p.stem)
        if t is not None:
            if p.name.upper().startswith("PXL_"):  # 구글 픽셀 파일 이름은 UTC
                return t.isoformat(), "파일명", t.replace(tzinfo=timezone.utc), "픽셀 파일 이름(UTC)"
            return t.isoformat(), "파일명", t.replace(tzinfo=tz), ("카톡 등에서 받은 파일이면 '받은 시각'일 수 있음" if "kakao" in p.name.lower() else None)
        mt = datetime.fromtimestamp(p.stat().st_mtime).astimezone()
        return mt.replace(tzinfo=None).isoformat(timespec="seconds"), "파일수정시각", mt, "복사·내려받기 때 바뀌었을 수 있음"

    with 실.단계("시각·일차 계산"):
        이전 = {x.get("원본"): x for x in 실.목록(있어야=False)}
        계산 = {}
        for p, m in 메타.items():
            기록시각, 출처, 기준, 메모 = 시각정하기(p, m)
            dev = 기기표[p]
            보정 = 보정표.get(dev, 0)
            촬영 = (기준.astimezone(tz) + timedelta(seconds=보정)).replace(microsecond=0)
            순서 = 기준.timestamp() + 보정
            if m["종류"] == "사진" and m.get("초이하") and str(m["초이하"]).isdigit():
                순서 += int(m["초이하"]) / 10 ** len(str(m["초이하"]))
            elif 출처 == "파일명":
                _, ms = 파일명에서(p.stem)
                순서 += (ms or 0) / 1000
            계산[p] = {"기록시각": 기록시각, "시각출처": 출처, "보정초": 보정, "촬영시각": 오프셋글(촬영), "순서": 순서, "메모": 메모}
            옛 = 이전.get(p.as_posix())
            if 옛 and 옛.get("시각출처") == "사용자":  # 사람이 정한 시각은 그대로
                계산[p].update({k: 옛.get(k) for k in ("기록시각", "시각출처", "보정초", "촬영시각")})
                t = 시각읽기(옛.get("촬영시각"))
                계산[p]["순서"] = t.timestamp() if t else 순서
        # 기간: 비어 있을 때만 강한 출처 시각으로 채움(사람이 적은 값은 그대로)
        기간 = dict(정보.get("기간") or {})
        강한날 = sorted(d for d in (기준날짜(v["촬영시각"], 정보) for v in 계산.values() if v["시각출처"] in 강한출처) if d)
        모든날 = sorted(d for d in (기준날짜(v["촬영시각"], 정보) for v in 계산.values()) if d)
        날들 = 강한날 or 모든날
        # 2026-10-08 실측: 사람이 시작을 잘못 적었는데(사진보다 뒤) 끝만 자동으로 채워 시작>끝이 됐고, 사진 38장이 모두 '기간 밖'이 됐음
        # → 채워서 시작>끝이 되면 채우지 않고, 기간이 사진과 안 맞으면 구체적인 안내를 요약·다음할일에 남김
        채움, 기간문제 = 기간채움과점검(기간, 날들)
        if 채움:
            def 고치기(d):
                g = dict(d.get("기간") or {})
                # 잠근 뒤 다시 읽은 값으로 다시 판단(그 사이 사람이 화면에서 기간을 고쳤을 수 있음)
                다시채움, _ = 기간채움과점검(g, 날들)
                for k, v in 다시채움.items():
                    if not g.get(k):
                        g[k] = v
                d["기간"] = g
            정보 = 실.정보고치기(고치기)
            실.알림(f"여행 기간을 사진 시각으로 채움: {정보['기간']}")
        for v in 계산.values():
            v["일차"] = 일차계산(v["촬영시각"], 정보)

    # 4. id 정하기(같은 원본은 같은 id) ─────────────────────────
    이전id = {x.get("원본"): x.get("id") for x in 이전.values() if x.get("id")}
    쓰인 = [int(m.group(1)) for i in 이전id.values() if (m := re.fullmatch(r"p(\d+)", str(i)))]
    다음번호 = max(쓰인, default=0) + 1
    id표 = {}
    for p in sorted(메타, key=lambda q: (계산[q]["순서"], q.as_posix())):
        if p.as_posix() in 이전id:
            id표[p] = 이전id[p.as_posix()]
        else:
            id표[p] = f"p{다음번호:04d}"
            다음번호 += 1

    항목들 = {}
    for p, m in 메타.items():
        i, c = id표[p], 계산[p]
        dev = 기기표[p]
        if m["종류"] == "사진":
            모델 = " ".join(x for x in (m.get("제조사"), m.get("모델")) if x) or None
            gps = m.get("GPS")
        else:
            t = m.get("태그") or {}
            mk, mo = t.get("com.apple.quicktime.make") or t.get("make"), t.get("com.apple.quicktime.model") or t.get("model")
            if not (mk or mo) and 기기모델.get(dev):
                mk, mo = 기기모델[dev].most_common(1)[0][0]
            모델 = " ".join(x for x in (mk, mo) if x) or None
            gps = ISO6709(t.get("com.apple.quicktime.location.iso6709") or t.get("location") or t.get("location-eng"))
        항목들[p] = {
            "id": i, "원본": p.as_posix(), "종류": m["종류"], "기기": dev, "모델": 모델,
            "기록시각": c["기록시각"], "시각출처": c["시각출처"], "보정초": c["보정초"], "촬영시각": c["촬영시각"],
            "일차": c["일차"], "GPS": gps, "장소ID": None,
            "영상길이초": m.get("길이") if m["종류"] == "영상" else None,
            "미리보기": f"작업/미리보기/{i}.jpg", "썸네일": f"작업/썸네일/{i}.jpg",
            "점수": {"선명도": None, "선명도_묶음비": None, "눈감음": None, "연사묶음": None},
            "판정": {"제외후보": False, "사유": [], "대표후보": False},
            "사용자결정": "미정", "장면설명": "",
        }

    # 5. 미리보기·썸네일 ────────────────────────────────────
    with 실.단계("미리보기 만들기") as 기록:
        상태 = Counter()
        실패 = []
        with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 4))) as ex:
            결과들 = list(ex.map(lambda p: (p, 미리보기만들기(항목들[p], p, 실.여행, 인자.미리보기다시)), list(항목들)))
        for p, r in 결과들:
            상태[r if not r.startswith("실패") else "실패"] += 1
            if r.startswith("실패"):
                실패.append({"id": 항목들[p]["id"], "파일": p.name, "오류": r[4:].strip(": ")})
                실.로그(f"미리보기 실패 {p}: {r}", "경고")
        기록["산출물"] = ["작업/미리보기", "작업/썸네일"]
        실.알림(f"미리보기: 새로 {상태['만듦']} · 그대로 {상태['그대로']} · 실패 {상태['실패']}")

    # 6. 목록 저장(사용자결정·점수·판정·장소·장면설명은 지킴) ─────────────
    with 실.단계("목록 저장") as 기록:
        바꿀필드 = ("원본", "종류", "기기", "모델", "기록시각", "시각출처", "보정초", "촬영시각", "일차", "GPS",
                 "영상길이초", "미리보기", "썸네일")
        고칠것, 새것 = {}, []
        for p, x in 항목들.items():
            if p.as_posix() in 이전id:
                고칠것[x["id"]] = {k: x[k] for k in 바꿀필드}
                if 이전[p.as_posix()].get("원본없음"):
                    고칠것[x["id"]]["원본없음"] = False
            else:
                새것.append(x)
        지금원본 = {p.as_posix() for p in 항목들}
        사라짐 = [x for k, x in 이전.items() if k not in 지금원본 and x.get("id")]
        for x in 사라짐:  # 지우지 않고 표시만
            고칠것[x["id"]] = {"원본없음": True}
        결과 = 실.목록합치기(고칠것, 새것)
        기록["산출물"] = "목록.json"
        보존 = sum(1 for x in 이전.values() if (x.get("사용자결정") or "미정") != "미정")

    # 요약 ────────────────────────────────────────────
    전체 = list(항목들.values())
    약한 = []
    for p, x in 항목들.items():
        if x["시각출처"] in ("EXIF", "파일명", "파일수정시각") and not (x["시각출처"] == "EXIF" and x["기기"] in 보정표):
            약한.append({"id": x["id"], "파일": f"{x['기기']}/{p.name}", "출처": x["시각출처"], "메모": 계산[p]["메모"]})
    영상들 = [{"id": x["id"], "파일": f"{x['기기']}/{p.name}", "기록시각": x["기록시각"], "출처": x["시각출처"],
            "촬영시각": x["촬영시각"], "일차": x["일차"], **({"메모": 계산[p]["메모"]} if 계산[p]["메모"] else {})}
           for p, x in 항목들.items() if x["종류"] == "영상"]
    시계의심 = sorted({x["기기"] for x in 전체 if x["시각출처"] == "EXIF" and x["기기"] not in 보정표})
    기간밖 = [{"id": x["id"], "촬영시각": x["촬영시각"]} for x in 전체 if x["일차"] is None]
    다음 = []
    if 기간문제:
        다음.append(기간문제)
        실.알림(기간문제)
    if 시계의심:
        다음.append(f"{', '.join(시계의심)}: 시간대 정보가 없어 시계가 틀렸을 수 있어요 → 시계확인(python 도구/시계보정.py --여행 '{실.여행ID}' --쌍찾기)")
    if any(x["시각출처"] == "파일명" for x in 전체):
        다음.append("파일 이름 시각 사진은 '받은 시각'일 수 있어요(카톡 등) → 사진 내용으로 위치·순서를 확인하는 질문 카드")
    if 기간밖 and not 기간문제:
        다음.append(f"여행 기간 밖 시각 {len(기간밖)}개 → 시계·기간 확인")
    다음.append(f"python 도구/고르기후보.py --여행 '{실.여행ID}'")
    return 실.끝({
        "사진": sum(1 for x in 전체 if x["종류"] == "사진"), "영상": sum(1 for x in 전체 if x["종류"] == "영상"),
        "HEIC": sum(1 for p in 항목들 if p.suffix.lower() in (".heic", ".heif")),
        "기기별": dict(Counter(x["기기"] for x in 전체)),
        "시각출처별": dict(Counter(x["시각출처"] for x in 전체)),
        "약한시각": 약한[:40], "시계확인필요기기": 시계의심,
        "영상시각": 영상들,
        "기간": 정보.get("기간"), "기간문제": 기간문제, "일차별": {str(k): v for k, v in sorted(Counter(x["일차"] for x in 전체).items(), key=lambda kv: (kv[0] is None, kv[0] or 0))},
        "기간밖": 기간밖[:20],
        "LivePhoto영상제외": [p.name for p in 라이브], "건너뜀": dict(건너뜀),
        "미리보기": dict(상태), "미리보기실패": 실패[:20],
        "목록": 결과, "보존된사용자결정": 보존, "원본없음표시": len(사라짐),
        "다음할일": 다음,
    }, 성공=not 실패)


def main() -> int:
    ap = 인자틀("원본 사진·영상 → 목록.json + 미리보기·썸네일 (원본은 읽기만)",
              "예) python 도구/목록만들기.py --여행 2026-09_제주")
    ap.add_argument("--미리보기다시", action="store_true", help="이미 있는 미리보기·썸네일도 새로 만들기")
    return 실행틀("목록만들기", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
