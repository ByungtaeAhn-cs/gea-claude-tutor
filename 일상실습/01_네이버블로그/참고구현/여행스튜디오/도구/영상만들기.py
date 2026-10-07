# -*- coding: utf-8 -*-
"""영상만들기.py — 여행 '돌아보기' 영상(선택). FFmpeg 로 장면별 조각을 만든 뒤 이어 붙입니다. (규약 4절)

구성: 오프닝 제목 → 전체 동선 지도 → [일차 제목 카드 → 그날 지도 → 사진·영상 …] × 일차 → 끝 카드
  - 시간 배분(조사 04 5절): 목표 길이(기본 490초=8:10)에서 제목·지도·영상 클립을 빼고 남은 시간을 사진에 나눔.
    대표 사진은 일반 사진의 2배(약 6초 : 3초). 사진 한 장이 5초를 넘으면 '소재 부족' → 3~5분 제안 길이를 JSON 에.
    (--목표초 를 주지 않았는데 소재가 부족하면 제안 길이로 만들고 알려 줌. 8:10 이 꼭 필요하면 --목표초 490)
  - 사진: 천천히 확대·축소·이동(켄 번스), 세로 사진은 흐린 배경 채우기. 영상 클립은 앞부분 하이라이트(기본 8초까지)
  - 전환: 같은 장소 = 부드럽게(fade), 장소 바뀜 = 밀기(slideleft), 날 바뀜 = 검은 화면 페이드(fadeblack)
  - 글자는 Pillow 로 그림(Windows 맑은 고딕 / Mac Apple SD Gothic Neo) → Mac 기본 ffmpeg(글자 기능 없음)도 OK
  - 음악: --음악 <여행/<ID>/음악/ 안의 오디오 파일>(없으면 무음 트랙), 앞 2초 페이드 인·끝 3초 페이드 아웃. 영상 클립의 현장음은 겹쳐 넣음
  - 유튜브 챕터 문구: 작업/영상/챕터.txt (첫 줄 00:00, 챕터마다 10초 이상)
  - 안정성: 긴 필터 하나 대신 장면마다 짧은 조각 → 전환 조각 → 이어 붙이기(다시 만들 때 바뀐 장면만 새로)
결과: 작업/영상/돌아보기.mp4 (+ 챕터.txt, 장면표.json) / --미리보기: 작업/영상/돌아보기_미리보기.mp4 (약 30초, 640×360)
고른 사진: 화면에서 '사용'·'대표'로 고른 것(없으면 제외 후보가 아닌 것). 숨긴 장소(숙소 등) 사진은 빼고 만듦.

사용  python 도구/영상만들기.py --여행 2026-09_제주 --계획만            (렌더 없이 시간 배분·제안 길이만)
      python 도구/영상만들기.py --여행 2026-09_제주 --미리보기
      python 도구/영상만들기.py --여행 2026-09_제주 --목표초 4:00 --음악 bgm.mp3
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import (도구오류, 분초글, 원자적_쓰기, 인자틀, 읽기_json, 실행, 실행틀, 한글글꼴, 필요,  # noqa: E402
                 ffmpeg경로, 정렬키, 숨긴장소표)
import _사진 as 사진  # noqa: E402

요일 = "월화수목금토일"
기본목표 = 490
전환길이 = {"fade": 0.7, "slideleft": 0.7, "fadeblack": 1.0}
카드초 = {"오프닝": 4.0, "전체지도": 8.0, "일차제목": 3.5, "일차지도": 4.5, "끝": 4.5}  # 오프닝 챕터가 10초 이상 되게


def 초읽기(글) -> float:
    s = str(글).strip()
    m = re.fullmatch(r"(\d+):(\d{1,2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    try:
        return float(s)
    except ValueError:
        raise 도구오류(f"--목표초 는 490 또는 8:10 모양으로 알려 주세요: {글}")


# ───────────────────────────────────────────── 계획
def 장소표시(장소: dict, pid) -> str | None:
    p = 장소.get(pid) if pid else None
    if not isinstance(p, dict) or not p.get("확인됨") or p.get("숨김"):
        return None  # 확인 안 된 이름은 영상에 쓰지 않음(추측하지 않기)
    return str(p.get("이름") or "") or None


def 숨긴장소들(장소: dict, 정보: dict) -> set:
    """지도·발행패키지와 같은 규칙(_공통.숨긴장소표): 숨김·숨길장소 이름·비공개 추정(사람이 공개를 고르기 전)."""
    return set(숨긴장소표(장소, 정보))


def 소재고르기(실, 목록: list[dict], 장소: dict, 정보: dict, 숨김포함: bool):
    목록 = [x for x in 목록 if not x.get("원본없음")]
    결정됨 = any(x.get("사용자결정") in ("사용", "대표") for x in 목록)
    if 결정됨:
        고른 = [x for x in 목록 if x.get("사용자결정") in ("사용", "대표")]
        대표 = {x["id"] for x in 고른 if x.get("사용자결정") == "대표"}
        기준 = "화면에서 고른 사진(사용·대표)"
    else:
        고른 = [x for x in 목록 if x.get("사용자결정") != "제외" and not (x.get("판정") or {}).get("제외후보")]
        대표 = {x["id"] for x in 고른 if (x.get("판정") or {}).get("대표후보")}
        기준 = "아직 고르지 않음 → 제외 후보가 아닌 사진(대표 = 대표 후보)"
    숨김 = 숨긴장소들(장소, 정보)
    빠짐 = [x["id"] for x in 고른 if x.get("장소ID") in 숨김] if not 숨김포함 else []
    고른 = [x for x in 고른 if x["id"] not in 빠짐]
    일차없음 = [x["id"] for x in 고른 if not x.get("일차")]
    고른 = sorted((x for x in 고른 if x.get("일차")), key=정렬키)
    return 고른, 대표, 기준, 빠짐, 일차없음


def 장면목록(실, 고른, 대표, 장소, 정보, 클립초, 지도폴더) -> list[dict]:
    """시간을 정하기 전의 장면 목록(종류·자료). 사진 길이는 '배수'(일반 1, 대표 2)로 둠."""
    장면 = []
    시작, 끝 = (정보.get("기간") or {}).get("시작"), (정보.get("기간") or {}).get("끝")
    날글 = ""
    if 시작:
        a = date.fromisoformat(시작[:10])
        b = date.fromisoformat(끝[:10]) if 끝 else a
        날글 = f"{a.year}. {a.month}. {a.day}" + (f" – {b.month}. {b.day}" if b != a else "")
    사진수 = sum(1 for x in 고른 if x.get("종류") == "사진")
    영상수 = sum(1 for x in 고른 if x.get("종류") == "영상")
    첫대표 = next((x for x in 고른 if x["id"] in 대표 and x.get("종류") == "사진"), next((x for x in 고른 if x.get("종류") == "사진"), None))
    장면.append({"종류": "오프닝", "초": 카드초["오프닝"], "줄": [str(정보.get("이름") or 실.여행ID), 날글,
                                                           f"사진 {사진수}장 · 영상 {영상수}개"], "배경": 첫대표})
    if (지도폴더 / "전체.png").is_file():
        장면.append({"종류": "지도", "초": 카드초["전체지도"], "그림": 지도폴더 / "전체.png", "이름": "여행 전체 동선"})
    일차들 = sorted({x["일차"] for x in 고른})
    for n in 일차들:
        그날 = [x for x in 고른 if x["일차"] == n]
        이름들 = list(dict.fromkeys(filter(None, (장소표시(장소, x.get("장소ID")) for x in 그날))))
        d = date.fromisoformat(시작[:10]).fromordinal(date.fromisoformat(시작[:10]).toordinal() + n - 1) if 시작 else None
        날 = f"{d.month}월 {d.day}일 {요일[d.weekday()]}요일" if d else ""
        장면.append({"종류": "일차제목", "초": 카드초["일차제목"], "일차": n,
                   "줄": [f"{n}일차", 날, " · ".join(이름들[:4])],
                   "배경": next((x for x in 그날 if x["id"] in 대표 and x.get("종류") == "사진"),
                              next((x for x in 그날 if x.get("종류") == "사진"), None)),
                   "챕터": f"{n}일차" + (f" · {d.month}/{d.day}({요일[d.weekday()]})" if d else "") + (f" {' · '.join(이름들[:3])}" if 이름들 else "")})
        if (지도폴더 / f"{n}일차.png").is_file():
            장면.append({"종류": "지도", "초": 카드초["일차지도"], "그림": 지도폴더 / f"{n}일차.png", "일차": n})
        for x in 그날:
            if x.get("종류") == "영상":
                길이 = float(x.get("영상길이초") or 3)
                장면.append({"종류": "영상", "항목": x, "초": round(min(길이, 클립초), 2), "일차": n, "장소": x.get("장소ID")})
            else:
                장면.append({"종류": "사진", "항목": x, "배수": 2 if x["id"] in 대표 else 1, "일차": n, "장소": x.get("장소ID"),
                           "대표": x["id"] in 대표})
    크레딧 = []
    if any(s["종류"] == "지도" for s in 장면):
        크레딧.append("지도 © OpenStreetMap contributors")
    장면.append({"종류": "끝", "초": 카드초["끝"], "줄": [str(정보.get("이름") or 실.여행ID), "— 끝 —"], "크레딧": 크레딧,
               "배경": next((x for x in reversed(고른) if x.get("종류") == "사진"), None)})
    return 장면


def 전환정하기(장면: list[dict]) -> list[str]:
    """장면 i → i+1 사이 전환 이름. 날 바뀜 = fadeblack, 장소 바뀜 = slideleft(밀기), 같은 장소·카드 = fade."""
    결과 = []
    for a, b in zip(장면, 장면[1:]):
        if b["종류"] in ("일차제목", "끝") and a["종류"] != "오프닝":
            결과.append("fadeblack")
        elif a["종류"] in ("사진", "영상") and b["종류"] in ("사진", "영상"):
            같음 = a.get("장소") and a.get("장소") == b.get("장소")
            결과.append("fade" if 같음 else "slideleft")
        else:
            결과.append("fade")
    return 결과


def 시간배분(장면: list[dict], 전환: list[str], 목표: float) -> dict:
    고정 = sum(s["초"] for s in 장면 if s["종류"] != "사진")
    겹침 = sum(전환길이[t] for t in 전환)
    단위 = sum(s["배수"] for s in 장면 if s["종류"] == "사진")
    영상초 = sum(s["초"] for s in 장면 if s["종류"] == "영상")

    def 길이(d):
        return 고정 + 단위 * d - 겹침
    d = (목표 - 고정 + 겹침) / 단위 if 단위 else 0.0
    자연3초 = 길이(3.0)
    제안 = min(300, max(180, int(round(자연3초 / 10.0)) * 10))
    상태 = "적당" if 2.5 <= d <= 5.0 else ("소재부족" if d > 5.0 else "사진많음")
    return {"사진초": d, "대표초": 2 * d, "고정초": round(고정, 1), "영상클립초": round(영상초, 1), "전환겹침초": round(겹침, 1),
            "사진단위": 단위, "상태": 상태, "3초기준길이": round(자연3초, 1), "제안초": 제안, "길이함수": 길이}


# ───────────────────────────────────────────── 그림(캔버스) 만들기
def 글꼴(크기: int, 굵게=False):
    from PIL import ImageFont
    p = 한글글꼴(굵게) or 한글글꼴()
    if not p:
        raise 도구오류("한글 글꼴을 찾지 못했어요(제목이 네모로 깨짐).",
                     힌트="Windows: C:/Windows/Fonts/malgun.ttf / Mac: /System/Library/Fonts/AppleSDGothicNeo.ttc")
    return ImageFont.truetype(p, 크기)


def 배경채우기(im, W, H, 어둡게=0.55, 흐림=None):
    from PIL import ImageEnhance, ImageFilter
    배 = im.copy()
    s = max(W / 배.width, H / 배.height)
    배 = 배.resize((max(1, round(배.width * s)), max(1, round(배.height * s))), 사진.Image.LANCZOS)
    l, t = (배.width - W) // 2, (배.height - H) // 2
    배 = 배.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(흐림 or max(8, W // 45)))
    return ImageEnhance.Brightness(배).enhance(어둡게)


def 사진캔버스(원본: Path, 미리보기: Path, W, H):
    """세로·4:3 사진도 16:9 화면에: 가운데에 원본 비율 그대로 + 뒤는 같은 사진을 흐리게."""
    try:
        im = 사진.열기(원본, 최대변=max(W, H))
    except Exception:
        im = 사진.Image.open(미리보기).convert("RGB")
    캔 = 배경채우기(im, W, H)
    s = min(W / im.width, H / im.height)
    앞 = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), 사진.Image.LANCZOS)
    캔.paste(앞, ((W - 앞.width) // 2, (H - 앞.height) // 2))
    return 캔


def 지도캔버스(그림: Path, W, H):
    from PIL import Image
    im = Image.open(그림).convert("RGB")
    캔 = Image.new("RGB", (W, H), (236, 240, 244))
    s = min(W * 0.94 / im.width, H * 0.94 / im.height)
    앞 = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    캔.paste(앞, ((W - 앞.width) // 2, (H - 앞.height) // 2))
    return 캔


def 카드캔버스(줄: list[str], 배경: Path | None, W, H, 크레딧: list[str] | None = None):
    from PIL import Image, ImageDraw
    if 배경 is not None:
        try:
            캔 = 배경채우기(사진.Image.open(배경).convert("RGB"), W, H, 어둡게=0.42, 흐림=W // 30)
        except Exception:
            캔 = Image.new("RGB", (W, H), (18, 28, 44))
    else:
        캔 = Image.new("RGB", (W, H), (18, 28, 44))
    d = ImageDraw.Draw(캔)
    크기 = [int(H * 0.12), int(H * 0.05), int(H * 0.042)]
    글들 = [(t, 글꼴(크기[min(k, 2)], 굵게=(k == 0))) for k, t in enumerate(줄) if t]
    if 크레딧:
        글들 += [(t, 글꼴(int(H * 0.03))) for t in 크레딧]
    높이 = sum(f.size * 1.45 for _, f in 글들)
    y = (H - 높이) / 2
    for t, f in 글들:
        w = d.textlength(t, font=f)
        d.text(((W - w) / 2, y), t, font=f, fill=(255, 255, 255), stroke_width=max(1, f.size // 22), stroke_fill=(0, 0, 0))
        y += f.size * 1.45
    return 캔


# ───────────────────────────────────────────── FFmpeg 조각
class 렌더기:
    def __init__(self, 실, 폴더: Path, W: int, H: int, fps: int, 미리보기: bool, 동시: int):
        self.실, self.폴더, self.W, self.H, self.fps = 실, 폴더, W, H, fps
        self.ff = ffmpeg경로()
        self.미리보기 = 미리보기
        self.인코딩 = (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"] if 미리보기 else
                     ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "12M", "-bufsize", "24M",
                      "-profile:v", "high"])  # 켄 번스는 화면 전체가 움직여 용량이 커짐 → 12Mbps 상한(유튜브 1080p30 권장 8Mbps)
        self.인코딩 += ["-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2), "-video_track_timescale", "15360",
                      "-an", "-threads", str(max(2, (os.cpu_count() or 4) // max(1, 동시)))]
        self.동시 = 동시
        폴더.mkdir(parents=True, exist_ok=True)

    def 이름(self, 자료: dict) -> str:
        글 = json.dumps({**자료, "W": self.W, "H": self.H, "fps": self.fps, "enc": self.인코딩, "v": 3},
                       ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(글.encode("utf-8")).hexdigest()[:16]

    def ff실행(self, 명령: list[str], 설명: str):
        r = 실행([self.ff, "-y", "-hide_banner", "-loglevel", "error", "-nostdin"] + 명령, 시간제한=1800)
        if r.returncode != 0:
            raise 도구오류(f"FFmpeg 오류({설명}): {(r.stderr or '').strip()[-600:]}")

    def 장면조각(self, s: dict, k: int) -> dict:
        """장면 하나 → 앞(전환용)·가운데·뒤(전환용) 조각. 이미 있으면 다시 만들지 않음(재시도 때 시간 절약)."""
        F = self.fps
        N = max(2, round(s["길이"] * F))
        h, t = round(s["앞전환"] * F), round(s["뒤전환"] * F)
        if N - h - t < 2:
            N = h + t + 2
        자료 = {"종류": s["종류"], "N": N, "h": h, "t": t, "효과": s.get("효과"),
              "원천": str(s.get("원천")), "원천시각": os.path.getmtime(s["원천"]) if s.get("원천") and Path(s["원천"]).exists() else None,
              "줄": s.get("줄"), "크레딧": s.get("크레딧"), "배경": str(s.get("배경경로"))}
        이름 = self.이름(자료)
        출력 = {"앞": self.폴더 / f"{이름}_h.mp4" if h else None, "가운데": self.폴더 / f"{이름}_m.mp4",
              "뒤": self.폴더 / f"{이름}_t.mp4" if t else None}
        if all(p is None or p.is_file() for p in 출력.values()):
            return {**출력, "새로": False}
        W2, H2 = (self.W * 2, self.H * 2) if not self.미리보기 else (self.W, self.H)
        if s["종류"] == "영상":
            입력 = ["-ss", "0", "-t", f"{s['길이'] + 0.5:.3f}", "-i", str(s["원천"])]
            W, H = self.W, self.H
            시작 = (f"[0:v]fps={F},split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"gblur=sigma=25,eq=brightness=-0.12[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration={s['길이']:.3f},"
                  f"trim=end_frame={N},setpts=PTS-STARTPTS")
        else:
            캔버스 = self.폴더 / f"{이름}_c.jpg"
            if not 캔버스.is_file():
                if s["종류"] == "사진":
                    그림 = 사진캔버스(Path(s["원천"]), Path(s["미리보기경로"]), W2, H2)
                elif s["종류"] == "지도":
                    그림 = 지도캔버스(Path(s["원천"]), W2, H2)
                else:
                    그림 = 카드캔버스(s.get("줄") or [], s.get("배경경로"), W2, H2, s.get("크레딧"))
                그림.save(캔버스, "JPEG", quality=94)
            입력 = ["-i", str(캔버스)]
            효과 = s.get("효과") or "확대"
            m = max(N - 1, 1)
            z = {"확대": f"1+0.12*on/{m}", "축소": f"1.12-0.12*on/{m}", "이동": "1.10",
                 "살짝": f"1+0.04*on/{m}", "지도": f"1+0.06*on/{m}"}[효과]
            x = f"(iw-iw/zoom)*on/{m}" if 효과 == "이동" else "(iw-iw/zoom)/2"
            시작 = (f"[0:v]scale={W2}:{H2},zoompan=z='{z}':x='{x}':y='(ih-ih/zoom)/2':d={N}:s={self.W}x{self.H}:fps={F},"
                  f"setsar=1,format=yuv420p")
        갈래 = [("가운데", f"trim=start_frame={h}:end_frame={N - t},setpts=PTS-STARTPTS")]
        if h:
            갈래.insert(0, ("앞", f"trim=end_frame={h},setpts=PTS-STARTPTS"))
        if t:
            갈래.append(("뒤", f"trim=start_frame={N - t},setpts=PTS-STARTPTS"))
        필터 = 시작 + f",split={len(갈래)}" + "".join(f"[s{j}]" for j in range(len(갈래))) + ";" + \
            ";".join(f"[s{j}]{식}[o{j}]" for j, (_, 식) in enumerate(갈래))
        명령 = 입력 + ["-filter_complex", 필터]
        임시들 = []
        for j, (키, _) in enumerate(갈래):
            임시 = 출력[키].with_name(출력[키].stem + f".{os.getpid()}.tmp.mp4")
            임시들.append((임시, 출력[키]))
            명령 += ["-map", f"[o{j}]"] + self.인코딩 + [str(임시)]
        self.ff실행(명령, f"장면 {k + 1} {s['종류']}")
        for 임시, 최종 in 임시들:
            os.replace(임시, 최종)
        return {**출력, "새로": True}

    def 전환조각(self, 뒤: Path, 앞: Path, 종류: str, 초: float) -> Path:
        n = round(초 * self.fps)
        이름 = self.이름({"전환": 종류, "a": 뒤.name, "b": 앞.name, "n": n})
        출력 = self.폴더 / f"{이름}_x.mp4"
        if 출력.is_file():
            return 출력
        임시 = 출력.with_name(출력.stem + f".{os.getpid()}.tmp.mp4")
        self.ff실행(["-i", str(뒤), "-i", str(앞), "-filter_complex",
                    f"[0:v][1:v]xfade=transition={종류}:duration={n / self.fps:.4f}:offset=0,format=yuv420p,setsar=1[o]",
                    "-map", "[o]", "-frames:v", str(n)] + self.인코딩 + [str(임시)], f"전환 {종류}")
        os.replace(임시, 출력)
        return 출력


def ffprobe(경로: Path) -> dict:
    fp = ffmpeg경로("ffprobe")
    r = 실행([fp, "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,profile",
            "-of", "json", str(경로)])
    if r.returncode != 0:
        return {}
    d = json.loads(r.stdout or "{}")
    결과 = {"길이초": round(float((d.get("format") or {}).get("duration") or 0), 2),
          "크기MB": round(int((d.get("format") or {}).get("size") or 0) / 1048576, 1)}
    for s in d.get("streams") or []:
        if s.get("codec_type") == "video":
            결과.update({"영상코덱": s.get("codec_name"), "프로필": s.get("profile"), "해상도": f"{s.get('width')}x{s.get('height')}",
                       "fps": s.get("r_frame_rate")})
        elif s.get("codec_type") == "audio":
            결과["음성코덱"] = s.get("codec_name")
    return 결과


def 챕터만들기(장면: list[dict], 시작들: list[float], 전체: float) -> list[tuple[float, str]]:
    챕터 = [(0.0, "오프닝 · 여행 경로")]
    for s, t in zip(장면, 시작들):
        if s["종류"] == "일차제목":
            챕터.append((t, s["챕터"]))
    # 유튜브 규칙: 첫 줄 00:00, 3개 이상, 오름차순, 챕터마다 10초 이상 → 짧은 챕터는 앞(첫 것이면 뒤)과 합침
    합침 = True
    while 합침 and len(챕터) > 1:
        합침 = False
        for k in range(len(챕터)):
            끝 = 챕터[k + 1][0] if k + 1 < len(챕터) else 전체
            if 끝 - 챕터[k][0] < 10:
                if k == 0:
                    챕터[1] = (0.0, f"{챕터[0][1]} · {챕터[1][1]}")
                    챕터.pop(0)
                else:
                    챕터.pop(k)
                합침 = True
                break
    return 챕터


# ───────────────────────────────────────────── 본문
음악확장자 = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}


def 음악확인(실, 값: str) -> Path:
    """--음악 은 여행/<여행ID>/음악/ 폴더 안의 오디오 파일만(보안 재검수). 이름만 줘도 되고('bgm.mp3'),
    '음악/bgm.mp3' 처럼 여행 폴더 기준이어도 됨. 다른 곳·다른 종류면 멈추고 안내."""
    폴더 = (실.여행 / "음악").resolve()
    안내 = (f"음악 파일을 여행/{실.여행ID}/음악/ 폴더에 넣고 --음악 <파일 이름>으로 알려 주세요"
          f"(mp3·m4a·aac·wav·ogg·flac). YouTube 오디오 보관함의 '저작자 표시 불필요' 곡을 권해요.")
    v = Path(str(값).strip())
    후보 = v if v.is_absolute() else (실.여행 / v if v.parts and v.parts[0] == "음악" else 실.여행 / "음악" / v)
    try:
        실제 = 후보.resolve()
        실제.relative_to(폴더)
    except (ValueError, OSError):
        raise 도구오류(f"음악은 여행/{실.여행ID}/음악/ 폴더 안의 파일만 쓸 수 있어요: {값}", 힌트=안내)
    if 실제.suffix.lower() not in 음악확장자:
        raise 도구오류(f"오디오 파일이 아니에요({실제.suffix or '확장자 없음'}): {값}", 힌트=안내)
    if not 실제.is_file():
        raise 도구오류(f"음악 파일을 찾지 못했어요: 여행/{실.여행ID}/음악/{실제.name}", 힌트=안내)
    av = 필요("av")
    try:
        with av.open(str(실제)) as c:
            소리있음 = bool(c.streams.audio)
    except Exception as e:
        raise 도구오류(f"음악 파일을 열지 못했어요({type(e).__name__}): {실제.name}", 힌트=안내)
    if not 소리있음:
        raise 도구오류(f"소리가 들어 있지 않은 파일이에요: {실제.name}", 힌트=안내)
    return 실제


def 본문(실):
    인자 = 실.인자
    사진.준비()
    음악 = 음악확인(실, 인자.음악) if 인자.음악 else None   # 렌더 전에 먼저 확인(오래 걸린 뒤 실패하지 않게)
    정보 = 실.정보()
    장소 = 읽기_json(실.여행 / "장소.json", {}) or {}
    목록 = 실.목록()
    폴더 = 실.여행 / "작업" / "영상"
    목표명시 = 인자.목표초 is not None
    목표 = 초읽기(인자.목표초) if 목표명시 else float(기본목표)
    요약 = {}

    with 실.단계("장면 계획") as 기록:
        고른, 대표, 기준, 빠짐, 일차없음 = 소재고르기(실, 목록, 장소, 정보, 인자.숨긴장소포함)
        if not 고른:
            raise 도구오류("영상에 넣을 사진이 없어요(화면에서 '사용'·'대표'로 고르거나 목록·고르기를 먼저).")
        장면 = 장면목록(실, 고른, 대표, 장소, 정보, 인자.클립초, 실.여행 / "작업" / "지도")
        if 인자.미리보기:  # 약 30초: 제목·지도 + 일차마다 2장(영상 있으면 1개 포함) + 끝
            고름, 그날수 = [], {}
            for s in 장면:
                if s["종류"] in ("사진", "영상"):
                    n = s["일차"]
                    if 그날수.get(n, 0) >= 2:
                        continue
                    그날수[n] = 그날수.get(n, 0) + 1
                고름.append(s)
            장면 = 고름
            for s in 장면:
                s["초"] = {"오프닝": 2.5, "지도": 2.5, "일차제목": 2.0, "끝": 2.5, "영상": 3.0}.get(s["종류"], s.get("초"))
        전환 = 전환정하기(장면)
        if 인자.미리보기:
            전환초 = {k: 0.5 for k in 전환길이}
            단위 = sum(s.get("배수", 0) for s in 장면 if s["종류"] == "사진")
            고정 = sum(s["초"] for s in 장면 if s["종류"] != "사진")
            d = max(1.5, (30 - 고정 + 0.5 * len(전환)) / max(단위, 1))
            배분 = {"사진초": d, "대표초": 2 * d, "상태": "미리보기", "제안초": None}
        else:
            전환초 = dict(전환길이)
            배분 = 시간배분(장면, 전환, 목표)
            if 배분["상태"] == "소재부족" and not 목표명시:
                요약["목표바꿈"] = (f"소재가 적어 8:10({기본목표}초)을 채우면 사진 한 장이 {배분['사진초']:.1f}초 — 지루해요. "
                               f"제안 길이 {분초글(배분['제안초'])}로 만들었어요(8:10이 꼭 필요하면 --목표초 490).")
                목표 = float(배분["제안초"])
                배분 = 시간배분(장면, 전환, 목표)
            d = 배분["사진초"]
            if d > 7.0:
                요약.setdefault("경고", []).append(f"사진 한 장 {d:.1f}초는 너무 길어 7초로 줄였어요 → 영상이 목표보다 짧아요.")
                d = 7.0
            if d < 2.0:
                요약.setdefault("경고", []).append(f"사진이 많아 한 장 {d:.1f}초 — 2초로 맞추고 길어져요. 사진을 더 고르거나 목표를 늘리세요.")
                d = 2.0
        효과들 = ["확대", "축소", "이동"]
        사진번호 = 0
        for k, s in enumerate(장면):
            s["앞전환"] = 전환초[전환[k - 1]] if k > 0 else 0.0
            s["뒤전환"] = 전환초[전환[k]] if k < len(전환) else 0.0
            if s["종류"] == "사진":
                s["길이"] = d * s["배수"]
                s["효과"] = 효과들[사진번호 % 3]
                사진번호 += 1
                s["원천"] = s["항목"]["원본"]
                s["미리보기경로"] = 실.여행 / s["항목"]["미리보기"]
            elif s["종류"] == "영상":
                s["길이"] = max(s["초"], s["앞전환"] + s["뒤전환"] + 0.6)
                s["원천"] = s["항목"]["원본"]
            else:
                s["길이"] = s["초"]
                s["효과"] = "지도" if s["종류"] == "지도" else "살짝"
                s["원천"] = str(s["그림"]) if s.get("그림") else None
                배경 = s.get("배경")
                s["배경경로"] = (실.여행 / 배경["미리보기"]) if 배경 else None
        시작들, t = [], 0.0
        for k, s in enumerate(장면):
            시작들.append(t)
            t += s["길이"] - s["뒤전환"]
        예상 = t
        표 = [{"번호": k + 1, "종류": s["종류"], "id": (s.get("항목") or {}).get("id"), "대표": s.get("대표", False),
              "길이": round(s["길이"], 2), "시작": round(시작들[k], 2), "전환(다음)": 전환[k] if k < len(전환) else None,
              "효과": s.get("효과"), "글": " / ".join(x for x in (s.get("줄") or []) if x) or None,
              "장소": s.get("장소")} for k, s in enumerate(장면)]
        요약["계획"] = {"기준": 기준, "사진": sum(1 for s in 장면 if s["종류"] == "사진"),
                      "대표사진": sum(1 for s in 장면 if s.get("대표")), "영상클립": sum(1 for s in 장면 if s["종류"] == "영상"),
                      "장면수": len(장면), "전환": {k: 전환.count(k) for k in set(전환)},
                      "목표초": None if 인자.미리보기 else round(목표, 1), "예상길이초": round(예상, 1), "예상길이": 분초글(예상),
                      "사진한장초": round(d, 2), "대표한장초": round(2 * d, 2), "배분상태": 배분["상태"],
                      "숨긴장소사진뺌": len(빠짐), "일차없어뺌": 일차없음}
        if not 인자.미리보기:
            요약["계획"].update({"3초기준길이": 배분["3초기준길이"], "제안초": 배분["제안초"], "제안": 분초글(배분["제안초"]),
                              "소재": ("소재가 적어요 — 3~5분을 권해요" if 배분["상태"] == "소재부족"
                                     else "사진이 많아요 — 더 고르거나 길게" if 배분["상태"] == "사진많음" else "알맞아요")})
        확인안됨 = sorted({pid for x in 고른 if (pid := x.get("장소ID")) and not (장소.get(pid) or {}).get("확인됨")})
        if 확인안됨:
            요약["확인안된장소"] = {pid: (장소.get(pid) or {}).get("이름") for pid in 확인안됨}
            요약.setdefault("경고", []).append("확인 안 된 장소 이름은 제목 카드에 넣지 않았어요(질문 카드로 확인 후 다시 만들기)")
        if not 인자.미리보기:
            원자적_쓰기(폴더 / "장면표.json", {"만든시각": time.strftime("%Y-%m-%dT%H:%M:%S"), "장면": 표})
        기록["산출물"] = None if 인자.미리보기 else "작업/영상/장면표.json"
    if 인자.계획만:
        요약["장면표"] = 표[:12] + ([{"…": f"{len(표) - 12}개 더"}] if len(표) > 12 else [])
        return 실.끝(요약)

    W, H = (640, 360) if 인자.미리보기 else ((1280, 720) if 인자.해상도 == 720 else (1920, 1080))
    fps = 24 if 인자.미리보기 else 인자.fps
    동시 = max(1, 인자.동시 or min(4, max(1, (os.cpu_count() or 4) // 4)))
    r = 렌더기(실, 폴더 / "_장면", W, H, fps, 인자.미리보기, 동시)
    시간 = {}
    렌더시작 = time.time() - 2

    with 실.단계("장면 조각 만들기") as 기록:
        t0 = time.monotonic()
        완료 = [0]

        def 하나(k):
            결과 = r.장면조각(장면[k], k)
            완료[0] += 1
            if 완료[0] % max(1, len(장면) // 10) == 0 or 완료[0] == len(장면):
                실.알림(f"장면 {완료[0]}/{len(장면)} 만듦")
            return 결과
        with ThreadPoolExecutor(max_workers=동시) as ex:
            조각들 = list(ex.map(하나, range(len(장면))))
        시간["장면초"] = round(time.monotonic() - t0, 1)
        새로 = sum(1 for c in 조각들 if c["새로"])
        기록["산출물"] = "작업/영상/_장면"
        기록["메시지"] = f"새로 {새로} · 재사용 {len(조각들) - 새로}"

    with 실.단계("전환 조각") as 기록:
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=동시) as ex:
            전환조각들 = list(ex.map(lambda k: r.전환조각(조각들[k]["뒤"], 조각들[k + 1]["앞"], 전환[k], 장면[k]["뒤전환"]),
                                range(len(전환))))
        시간["전환초"] = round(time.monotonic() - t0, 1)
        기록["산출물"] = "작업/영상/_장면"

    이름 = "돌아보기_미리보기.mp4" if 인자.미리보기 else "돌아보기.mp4"
    최종 = 폴더 / 이름
    with 실.단계("이어 붙이기") as 기록:
        t0 = time.monotonic()
        목록글 = []
        for k, c in enumerate(조각들):
            목록글.append(f"file '{c['가운데'].name}'")
            if k < len(전환조각들):
                목록글.append(f"file '{전환조각들[k].name}'")
        목록파일 = r.폴더 / f"이어붙이기_{'미리보기' if 인자.미리보기 else '전체'}.txt"
        목록파일.write_text("\n".join(목록글) + "\n", encoding="utf-8")
        영상만 = r.폴더 / f"_영상만_{'p' if 인자.미리보기 else 'f'}.mp4"
        r.ff실행(["-f", "concat", "-safe", "0", "-i", str(목록파일), "-c", "copy", str(영상만)], "이어 붙이기")
        시간["이어붙이기초"] = round(time.monotonic() - t0, 1)
        기록["산출물"] = None

    with 실.단계("음악·소리") as 기록:
        t0 = time.monotonic()
        길이 = ffprobe(영상만).get("길이초") or 예상
        입력, 필터, 섞을 = ["-i", str(영상만)], [], []
        if 음악:
            입력 += ["-stream_loop", "-1", "-i", str(음악)]
            n = 입력.count("-i") - 1
            필터.append(f"[{n}:a]atrim=0:{길이:.3f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=2,"
                      f"afade=t=out:st={max(0, 길이 - 3):.3f}:d=3,volume=0.8[m]")
            섞을.append("[m]")
        if not 인자.현장음끄기:
            av = 필요("av")
            for k, s in enumerate(장면):
                if s["종류"] != "영상":
                    continue
                try:
                    with av.open(str(s["원천"])) as c:
                        소리 = bool(c.streams.audio)
                except Exception:
                    소리 = False
                if not 소리:
                    continue
                입력 += ["-t", f"{s['길이']:.3f}", "-i", str(s["원천"])]
                n = 입력.count("-i") - 1
                ms = int(시작들[k] * 1000)
                필터.append(f"[{n}:a]asetpts=PTS-STARTPTS,afade=t=in:d=0.3,afade=t=out:st={max(0, s['길이'] - 0.4):.3f}:d=0.4,"
                          f"adelay={ms}|{ms}[c{k}]")
                섞을.append(f"[c{k}]")
        if not 섞을:
            입력 += ["-f", "lavfi", "-t", f"{길이:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            n = 입력.count("-i") - 1
            섞을.append(f"[{n}:a]")
        필터.append("".join(섞을) + f"amix=inputs={len(섞을)}:duration=longest:normalize=0,apad,atrim=0:{길이:.3f}[a]")
        임시 = 최종.with_name(f".{최종.stem}.{os.getpid()}.tmp.mp4")
        r.ff실행(입력 + ["-filter_complex", ";".join(필터), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(임시)], "음악·소리")
        os.replace(임시, 최종)
        시간["소리초"] = round(time.monotonic() - t0, 1)
        기록["산출물"] = 실.상대(최종)

    with 실.단계("확인·챕터") as 기록:
        확인 = ffprobe(최종)
        요약["결과"] = {"파일": 실.상대(최종), **확인, "음악": 음악.name if 음악 else "없음(무음 트랙)"}
        if not 인자.미리보기:
            챕터 = 챕터만들기(장면, 시작들, 확인.get("길이초") or 예상)
            글 = "\n".join(f"{분초글(t)} {이름}" for t, 이름 in 챕터) + "\n"
            원자적_쓰기(폴더 / "챕터.txt", 글=글)
            요약["챕터"] = 글.strip().splitlines()
            if len(챕터) < 3:
                요약.setdefault("경고", []).append("챕터가 3개보다 적어 유튜브가 챕터로 인식하지 않아요(일차가 적음).")
            기록["산출물"] = ["작업/영상/챕터.txt", 실.상대(최종)]
    # 장면 조각은 '다시 만들 때 바뀐 장면만' 새로 만들려고 남겨 둠. 이번 결과에 쓰이지 않은 옛 조각(설정이 바뀐 것)은 치움
    쓰임 = {목록파일.name, 영상만.name}
    for c in 조각들:
        쓰임 |= {Path(v).name for k, v in c.items() if k in ("앞", "가운데", "뒤") and v}
        쓰임 |= {Path(v).name.rsplit("_", 1)[0] + "_c.jpg" for k, v in c.items() if k == "가운데" and v}
    쓰임 |= {x.name for x in 전환조각들}
    다른쪽 = "_영상만_f.mp4" if 인자.미리보기 else "_영상만_p.mp4"
    치움 = 0
    for f in r.폴더.iterdir():
        if f.is_file() and f.name not in 쓰임 and f.name != 다른쪽 and not f.name.startswith("이어붙이기_"):
            if 인자.장면지우기 or f.stat().st_mtime < 렌더시작:
                try:
                    f.unlink()
                    치움 += 1
                except OSError:
                    pass
    if 인자.장면지우기:
        for f in list(r.폴더.iterdir()):
            try:
                f.unlink()
            except OSError:
                pass
    요약["장면캐시"] = {"폴더": 실.상대(r.폴더), "MB": round(sum(f.stat().st_size for f in r.폴더.glob("*") if f.is_file()) / 1048576, 1),
                    "치운옛조각": 치움, "안내": "다시 만들 때 바뀐 장면만 새로 만들려고 남겨 둠. 지우려면 --장면지우기"}
    시간["합계초"] = round(sum(시간.values()), 1)
    요약["렌더시간"] = 시간
    요약["다음할일"] = ["화면 [영상]에서 재생해 확인 → 전체 렌더는 --미리보기 없이",
                    "YouTube 업로드는 사람이 Studio에서(챕터.txt를 설명란에), 음악은 오디오 보관함 곡 권장"] if 인자.미리보기 else \
                   ["YouTube 업로드는 사람이 Studio에서. 설명란에 챕터.txt 붙여 넣기, 사진·음악 출처 표기"]
    return 실.끝(요약)


def main() -> int:
    ap = 인자틀("여행 돌아보기 영상(FFmpeg): 대표 길게·나머지 짧게, 일차 제목·지도·전환·음악·챕터",
              "예) python 도구/영상만들기.py --여행 2026-09_제주 --계획만\n"
              "    python 도구/영상만들기.py --여행 2026-09_제주 --미리보기\n"
              "    python 도구/영상만들기.py --여행 2026-09_제주 --목표초 4:00 --음악 bgm.mp3")
    ap.add_argument("--목표초", help="목표 길이(초 또는 분:초, 기본 490=8:10). 소재가 적으면 --계획만 으로 제안 길이를 먼저 보세요")
    ap.add_argument("--음악", help="배경 음악: 여행/<여행ID>/음악/ 폴더 안의 mp3·m4a·aac·wav·ogg·flac 파일 이름(예: bgm.mp3). 없으면 무음 트랙")
    ap.add_argument("--미리보기", action="store_true", help="약 30초·640×360 빠른 미리보기")
    ap.add_argument("--계획만", action="store_true", help="렌더하지 않고 시간 배분·제안 길이·장면표만")
    ap.add_argument("--클립초", type=float, default=8.0, help="영상 클립에서 쓸 앞부분 길이(기본 8초)")
    ap.add_argument("--해상도", type=int, choices=[720, 1080], default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--동시", type=int, help="동시에 만들 장면 수(기본: CPU 코어 ÷ 4, 최대 4)")
    ap.add_argument("--숨긴장소포함", action="store_true", help="숨긴 장소(숙소 등) 사진도 넣기(기본은 뺌)")
    ap.add_argument("--현장음끄기", action="store_true", help="영상 클립의 현장 소리를 넣지 않음")
    ap.add_argument("--장면지우기", action="store_true", help="다 만든 뒤 장면 조각(작업/영상/_장면)을 지움(디스크 절약, 다음엔 처음부터)")
    return 실행틀("영상만들기", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
