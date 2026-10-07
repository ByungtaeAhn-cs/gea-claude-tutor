# -*- coding: utf-8 -*-
"""여행 스튜디오 서버 — 화면(서버/화면/)과 /api 를 제공합니다. (규약 v2 5절)

- Python 표준 라이브러리만 씁니다(설치할 것 없음). Windows·Mac 공용.
- 내 컴퓨터 안에서만 열립니다: http://127.0.0.1:8765 (다른 컴퓨터에서는 접속 불가)
- 화면 ↔ Claude 는 '작업함' 폴더의 파일로 이야기합니다(규약 3절).
- 서버가 직접 고치는 데이터: 사진 '사용자결정', 글 '승인', 고른 구성안(편목록), 설정. 나머지는 요청 파일로 Claude에게.
- 사진 묶음·발행 작업은 '공용/발행서버.py'를 가져다 씁니다(서버/발행연동.py).
- 중요한 일은 로그/YYYY-MM-DD.log 에 남깁니다.

실행:  python 서버/server.py          (보통은 '스튜디오실행.pyw'를 더블클릭)
옵션:  --포트 8765
       --폴더 <여행스튜디오 폴더>   데이터(여행/, 작업함/, 로그/)를 다른 곳에서 읽기(시험용)
       --딥링크끄기 / --브라우저끄기  Claude 앱·브라우저(Chrome 또는 Edge)를 실제로 열지 않음(시험용)
"""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

서버폴더 = Path(__file__).resolve().parent
화면폴더 = 서버폴더 / "화면"
기본스튜디오 = 서버폴더.parent
sys.path.insert(0, str(서버폴더))
import 발행연동  # noqa: E402  (같은 폴더)

요청종류 = ["목록만들기", "시계확인", "고르기", "구성안", "지도", "꿀팁인터뷰",
          "글쓰기", "수정요청", "임시저장", "재시도", "영상", "자유요청"]
결정값 = ["미정", "사용", "대표", "제외"]
편ID무늬 = re.compile(r"^[0-9A-Za-z가-힣_\-]{1,40}$")
파일종류 = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".bmp": "image/bmp",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
}
기본사용자설정 = {"블로그ID": "", "브라우저": "chrome", "자동예약발행": False,   # 단체 블로그 블로그설정.json 과 같은 키
              "편사이간격분": 10, "예약최소여유분": 15, "중단판정분": 10}
설정범위 = {"편사이간격분": (1, 1440), "예약최소여유분": (10, 1440), "중단판정분": (7, 120)}   # 숫자 설정의 허용 범위(분). 중단판정 최소 7분은 공용 모듈과 같음
옛설정키 = {"최소간격초": ("편사이간격분", 60), "중단판정초": ("중단판정분", 60)}    # 옛 이름(초) → 새 이름(분)
음악확장자 = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}  # 도구/영상만들기.py 와 같은 목록
브라우저들 = ("chrome", "edge", "default")   # 네이버에 로그인해 둔 '내 브라우저'(블로그 도우미 확장을 설치한 곳). 공용 open_in_browser 값
예약경고 = ("네이버 약관은 허락 없는 자동화 게시를 금지하며, 아이디 보호조치·검색 누락 위험이 있습니다. "
         "켜도 '승인됨'인 글만 예약 발행하고, 한 계정에 하루 여러 편을 자동으로 몰지 않습니다.")


class 서버설정:
    스튜디오: Path = 기본스튜디오
    포트: int = 8765
    딥링크열기: bool = True
    브라우저열기: bool = True
    화면키: str = secrets.token_urlsafe(32)   # 화면(index.html)에만 심어 주는 열쇠(X-Studio-Key 머리) — 파일에 남기지 않음(검수 M1)
    파일키: str = secrets.token_urlsafe(32)   # 쿠키 열쇠 — 머리를 못 붙이는 그림·영상·미리보기 틀의 '읽기'만(검수 재검수 N2)
    시험확인: str | None = None               # 시험용(--시험확인 예|아니오, 임시 폴더의 --폴더 와만): 데스크탑 확인 창 대신 이 답


화면키쿠키 = "studio_file_key"  # 값은 파일키(화면키와 다름) — localhost 쿠키는 포트를 가리지 않으므로 읽기 전용으로만
# 화면(사람)만 하는 동작은 화면 열쇠가 있어야 함. Claude 도우미(작업함.py)가 쓰는 두 주소만 예외(예약 발행은 빼고)
도우미주소 = {"/api/발행작업", "/api/발행작업/다시"}
화면CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
         "media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; "
         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# 미리보기(공용 템플릿 — 안의 작은 스크립트를 그대로 둠, 글꼴은 이 PC 글꼴만 — 검수 L9). fetch 는 막음
미리보기CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
           "font-src 'self' data:; img-src 'self' data: blob:; media-src 'self' blob:; "
           "connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
# /파일/ 에서 바로 보여 줄 형식(그 밖은 내려받기 + sandbox — 여행 폴더의 html·svg 가 화면 권한으로 돌지 않게, 검수 L3)
바로보기형식 = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".mp4", ".m4v", ".mov", ".webm",
             ".mp3", ".m4a", ".wav", ".json", ".txt", ".md", ".log"}


class 요청오류(Exception):
    def __init__(self, 상태: int, 메시지: str, **덧붙임):  # 상태 = HTTP 상태 번호, 덧붙임의 코드 = 오류 이름
        super().__init__(메시지)
        self.상태, self.메시지, self.덧붙임 = 상태, 메시지, 덧붙임


# ---------------------------------------------------------------- 폴더·파일 도우미

def 여행루트() -> Path:
    return 서버설정.스튜디오 / "여행"


def 작업함(이름: str = "") -> Path:
    p = 서버설정.스튜디오 / "작업함"
    return p / 이름 if 이름 else p


def 로그폴더() -> Path:
    return 서버설정.스튜디오 / "로그"


def 폴더준비():
    for 이름 in ("요청", "질문", "답변", "처리완료"):
        작업함(이름).mkdir(parents=True, exist_ok=True)
    여행루트().mkdir(parents=True, exist_ok=True)
    로그폴더().mkdir(parents=True, exist_ok=True)


def 지금() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def 시각읽기(글) -> datetime | None:
    if not 글 or not isinstance(글, str):
        return None
    try:
        t = datetime.fromisoformat(글.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def _사용중(e: BaseException) -> bool:
    """Windows: 다른 프로그램이 파일을 잠깐 열고 있거나(공유 위반) 막 지워지는 중이면 PermissionError(5·32·33).
    → '사용 중'으로 보고 짧게 기다렸다 다시 함(도구/_공통.py 와 같은 규칙)."""
    return isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32, 33)


def _파일읽기(경로: Path, 번수: int = 12):
    """JSON 읽기. '사용 중'이면 백오프로 다시. 없으면 FileNotFoundError, 끝까지 사용 중이면 그 오류."""
    for 번 in range(번수):
        try:
            with open(경로, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            raise
        except OSError as e:
            if not _사용중(e) or 번 == 번수 - 1:
                raise
            time.sleep(0.02 * (번 + 1))


def 읽기_json(경로: Path, 기본=None):
    """화면에 보여 줄 것을 읽을 때: 없거나·깨졌거나·계속 사용 중이면 기본값(오류를 내지 않음)."""
    try:
        return _파일읽기(경로)
    except (OSError, ValueError):
        return 기본


def 고칠_json(경로: Path, 기본=None, 깨지면_새로: bool = False):
    """읽고-고치고-쓰기(잠금 안에서)용: 없으면 기본값. 계속 사용 중이거나 깨진 파일이면 **오류를 냄** →
    잠깐 못 읽었다고 빈 값으로 덮어써서 기록이 사라지는 일을 막음.
    깨지면_새로=True(상태.json 처럼 다시 만들어도 되는 파일)면 깨진 파일을 '<이름>.깨짐'으로 남기고 기본값."""
    try:
        return _파일읽기(경로)
    except FileNotFoundError:
        return 기본
    except ValueError:
        if 깨지면_새로:
            try:
                shutil.copy2(경로, 경로.with_name(경로.name + ".깨짐"))
            except OSError:
                pass
            return 기본
        raise 요청오류(409, f"{경로.name} 파일이 깨져 있어요. Claude에게 '{경로.name} 고쳐줘'라고 부탁해 주세요.")
    except OSError:
        raise 요청오류(503, f"{경로.name} 파일을 다른 프로그램이 쓰고 있어요. 잠시 뒤 다시 눌러 주세요.")


def 원자적_쓰기(경로: Path, 데이터):
    """임시 파일에 다 쓴 뒤 한 번에 바꿔 끼웁니다 → 읽는 쪽이 반쯤 쓰인 파일을 보는 일이 없음."""
    경로.parent.mkdir(parents=True, exist_ok=True)
    글 = json.dumps(데이터, ensure_ascii=False, indent=2)
    임시 = 경로.with_name(f".{경로.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(임시, "w", encoding="utf-8", newline="\n") as f:
        f.write(글)
        f.flush()
        os.fsync(f.fileno())
    for 번 in range(40):  # Windows: 다른 프로그램이 잠깐 열고 있으면 바꿔 끼우기가 실패 → 백오프로 다시
        try:
            os.replace(임시, 경로)
            return
        except OSError as e:
            if not _사용중(e):
                break
            time.sleep(0.05 * (번 + 1))
    try:
        임시.unlink()
    except OSError:
        pass
    raise 요청오류(503, f"{경로.name} 파일을 다른 프로그램이 쓰고 있어요. 잠시 뒤 다시 눌러 주세요.")


class 파일잠금:
    """여러 프로그램(서버·도구 스크립트·Claude 도우미)이 같은 파일을 동시에 고치지 않게 하는 잠금 파일.
    도구/_공통.py 와 같은 규칙: O_EXCL 로 만들고, '사용 중'(PermissionError)도 '이미 잠김'처럼 기다리며,
    오래된(죽은 프로그램이 남긴) 잠금은 치움."""

    def __init__(self, 경로: Path, 기다림=10.0, 오래됨=30.0, 실패시오류=True):
        self.경로, self.기다림, self.오래됨, self.실패시오류 = 경로, 기다림, 오래됨, 실패시오류
        self.얻음 = False

    def __enter__(self):
        끝 = time.monotonic() + self.기다림
        self.경로.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.경로, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, f"{os.getpid()} 여행스튜디오 서버".encode("utf-8"))
                finally:
                    os.close(fd)
                self.얻음 = True
                return self
            except (FileExistsError, PermissionError):  # Windows: 막 지워지는 중인 잠금 파일은 PermissionError
                try:
                    if time.time() - self.경로.stat().st_mtime > self.오래됨:
                        self.경로.unlink()  # 프로그램이 죽어서 남은 잠금
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass
                if time.monotonic() > 끝:
                    if self.실패시오류:
                        raise 요청오류(503, "다른 작업이 같은 파일을 고치는 중이에요. 잠시 뒤 다시 눌러 주세요.")
                    return self
                time.sleep(random.uniform(0.005, 0.03))  # 짧고 고르지 않게 — 여러 프로그램이 번갈아 잡게

    def __exit__(self, *_):
        if not self.얻음:
            return
        for 번 in range(20):  # 잠금 파일을 남기면 다른 프로그램이 30초 기다리므로 꼭 지움
            try:
                self.경로.unlink()
                return
            except FileNotFoundError:
                return
            except OSError as e:
                if not _사용중(e):
                    return
                time.sleep(0.02 * (번 + 1))


_스레드잠금 = threading.Lock()      # 짧게 쓰는 잠금(캐시·파일 이름 정하기)
_쓰기잠금 = threading.Lock()        # 데이터 파일 고치기(서버 안 여러 스레드끼리)
_로그잠금 = threading.Lock()
_미리보기잠금 = threading.Lock()
_미리보기캐시: dict[str, tuple[float, str]] = {}  # 배치 파일 → (원본 수정 시각, 미리보기 HTML) — 서버 메모리에만
_목록캐시: dict[str, tuple[int, int, object]] = {}
_요청캐시: dict[str, dict] = {}     # 요청 id → {여행ID, 종류} (요청 파일은 바뀌지 않으므로 기억해 둠)


# ---------------------------------------------------------------- 로그(규약 1절 로그/YYYY-MM-DD.log)

def 기록(메시지: str, 여행ID: str | None = None, 수준: str = "정보") -> str | None:
    """로그/오늘.log 에 한 줄 쓰고 '로그/날짜.log#L줄번호' 를 돌려줌. 실패해도 서버는 계속."""
    try:
        한줄 = " ".join(str(메시지).split())[:2000]
        날짜 = f"{datetime.now():%Y-%m-%d}"
        줄 = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{수준}] [서버]{f' [{여행ID}]' if 여행ID else ''} {한줄}\n"
        파일 = 로그폴더() / f"{날짜}.log"
        with _로그잠금, 파일잠금(로그폴더() / ".로그.lock", 기다림=30, 오래됨=60, 실패시오류=False) as 잠금:
            if not 잠금.얻음:  # 잠금 없이 쓰면 다른 프로그램과 같은 자리에 덧써 글자가 깨짐 → 이 줄은 버림
                sys.stderr.write(f"로그 잠금을 얻지 못해 한 줄을 쓰지 않음: {한줄[:200]}\n")
                return None
            줄수 = 0
            if 파일.is_file():
                with open(파일, "rb") as f:
                    줄수 = sum(1 for _ in f)
            with open(파일, "a", encoding="utf-8", newline="\n") as f:
                f.write(줄)
        return f"로그/{날짜}.log#L{줄수 + 1}"
    except Exception:
        return None


def 로그보기(날짜, 줄=None, 범위=30) -> dict:
    날짜 = (날짜 or datetime.now().strftime("%Y-%m-%d")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", 날짜):
        raise 요청오류(400, "날짜는 2026-10-07 모양으로 알려 주세요")
    파일 = 로그폴더() / f"{날짜}.log"
    날짜들 = sorted((f.stem for f in 로그폴더().glob("*.log") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.stem)), reverse=True)[:30]
    if not 파일.is_file():
        return {"날짜": 날짜, "파일": f"로그/{날짜}.log", "있음": False, "전체줄수": 0, "줄": [], "마지막오류줄": None, "날짜들": 날짜들}
    줄들 = 파일.read_text(encoding="utf-8", errors="replace").splitlines()
    오류줄 = [i + 1 for i, s in enumerate(줄들) if "[오류]" in s]
    try:
        n = int(줄) if 줄 not in (None, "") else None
    except ValueError:
        raise 요청오류(400, "줄은 숫자로 알려 주세요")
    if n:
        시작, 끝 = max(1, n - 범위), min(len(줄들), n + 범위)
    else:
        시작, 끝 = max(1, len(줄들) - 199), len(줄들)
    return {"날짜": 날짜, "파일": f"로그/{날짜}.log", "있음": True, "전체줄수": len(줄들),
            "줄": [{"번호": i, "글": 줄들[i - 1], "오류": "[오류]" in 줄들[i - 1]} for i in range(시작, 끝 + 1)],
            "강조줄": n, "마지막오류줄": 오류줄[-1] if 오류줄 else None, "날짜들": 날짜들}


# ---------------------------------------------------------------- 여행·편

def 여행폴더(여행ID, 있어야=True) -> Path:
    if not isinstance(여행ID, str) or not 여행ID.strip():
        raise 요청오류(400, "여행ID가 필요해요")
    if re.search(r'[\\/:*?"<>|\x00-\x1f]', 여행ID) or 여행ID.startswith(".") or len(여행ID) > 100:
        raise 요청오류(400, "여행ID가 올바르지 않아요")
    루트 = 여행루트().resolve()
    p = (루트 / 여행ID).resolve()
    if p.parent != 루트:
        raise 요청오류(403, "여행 폴더 밖은 열 수 없어요")
    if 있어야 and not p.is_dir():
        raise 요청오류(404, f"'{여행ID}' 여행을 찾지 못했어요")
    return p


def 편확인(편ID) -> str:
    if not isinstance(편ID, str) or not 편ID무늬.fullmatch(편ID):
        raise 요청오류(400, "편ID는 공백·특수문자 없이 적어 주세요(예: 1일차, 하이라이트)")
    return 편ID


def 편값(질의: dict) -> str:
    """?편=1일차 (v2) 또는 ?일차=1 (v1 호환)."""
    if 질의.get("편"):
        return 편확인(질의["편"])
    if 질의.get("일차"):
        if not str(질의["일차"]).isdigit():
            raise 요청오류(400, "일차는 숫자로 알려 주세요")
        return f"{int(질의['일차'])}일차"
    raise 요청오류(400, "어느 편인지 알려 주세요(편=1일차)")


def 안쪽인가(경로: Path, 기준: Path) -> bool:
    try:
        경로.resolve().relative_to(기준.resolve())
        return True
    except ValueError:
        return False


def 목록항목(데이터) -> list:
    """목록.json 이 [항목…] 이든 {"항목": […]} 이든 항목 목록을 돌려줍니다."""
    if isinstance(데이터, list):
        return 데이터
    if isinstance(데이터, dict):
        for 키 in ("항목", "목록", "사진", "items"):
            if isinstance(데이터.get(키), list):
                return 데이터[키]
    return []


def 목록읽기(p: Path):
    """수정 시각이 같으면 다시 읽지 않습니다(2초마다 묻는 화면이 많아서)."""
    f = p / "목록.json"
    try:
        st = f.stat()
    except OSError:
        return None
    키 = str(f)
    with _스레드잠금:
        c = _목록캐시.get(키)
        if c and c[0] == st.st_mtime_ns and c[1] == st.st_size:
            return c[2]
    데이터 = 읽기_json(f)
    if 데이터 is None:  # 잠깐 사용 중이거나 쓰는 중 → 예전 것이라도 보여 줌
        with _스레드잠금:
            c = _목록캐시.get(키)
        return c[2] if c else None
    with _스레드잠금:
        _목록캐시[키] = (st.st_mtime_ns, st.st_size, 데이터)
    return 데이터


def 수정시각(*경로들: Path) -> float | None:
    값 = []
    for 경로 in 경로들:
        try:
            값.append(경로.stat().st_mtime)
        except OSError:
            pass
    return max(값) if 값 else None


def 상대경로(경로: Path, 기준: Path) -> str:
    return 경로.resolve().relative_to(기준.resolve()).as_posix()


def 편목록읽기(p: Path) -> list[dict]:
    d = 읽기_json(p / "원고" / "편목록.json")
    if isinstance(d, dict):
        d = d.get("편") or d.get("편목록") or []
    return [x for x in (d or []) if isinstance(x, dict) and isinstance(x.get("편ID"), str) and 편ID무늬.fullmatch(x["편ID"])]


def _자연순(글: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", 글)]


def 편파일들(p: Path, 폴더: str, 머리: str) -> dict[str, Path]:
    """원고/배치_<편ID>.json, 발행/패키지_<편ID>.json 을 편ID 별로. 편목록 순서 → 이름 순."""
    결과: dict[str, Path] = {}
    for 곳 in (p / 폴더, p):
        if not 곳.is_dir():
            continue
        for f in 곳.glob(f"{머리}_*.json"):
            편 = f.stem[len(머리) + 1:]
            if 편ID무늬.fullmatch(편) and 편 not in 결과:
                결과[편] = f
    순서 = {x["편ID"]: i for i, x in enumerate(편목록읽기(p))}
    return dict(sorted(결과.items(), key=lambda kv: (순서.get(kv[0], 10_000), _자연순(kv[0]))))


def 영상결과(p: Path) -> list[str]:
    """돌아보기 영상(도구/영상만들기.py 결과: 작업/영상/돌아보기.mp4, 미리보기는 돌아보기_미리보기.mp4)."""
    곳 = p / "작업" / "영상"
    return [상대경로(f, p) for f in sorted(곳.glob("*.mp4"))] if 곳.is_dir() else []


def AI이미지있음(배치: dict) -> bool:
    """AI로 만들거나 바꾼 이미지가 글에 있는가 — 블록의 "AI이미지": true, 또는 AI 삽화 폴더의 그림.
    (네이버 'AI 활용 설정'은 AI로 만든 이미지·영상·오디오가 대상. 직접 찍은 사진만 있으면 끔이 기본)"""
    for b in 배치.get("블록") or []:
        if not isinstance(b, dict):
            continue
        if b.get("AI이미지") is True:
            return True
        if any("AI삽화" in str(x) for x in [b.get("이미지"), *(b.get("사진") or [])] if x):
            return True
    return False


_글머리 = ("제목", "카테고리", "태그", "공개", "AI활용표시")
_글블록 = ("종류", "글", "출처", "장소", "목록", "역할", "방식", "대표", "이미지", "영상", "제목")


def 글내용지문(d: dict) -> str:
    """배치와 그 배치로 만든 패키지가 '같은 글'인지 — 공용 content_fingerprint(사람이 읽는 글 내용만, 업로드 경로·나눈 묶음 경계 뺌)."""
    return 발행연동.모듈(서버설정.스튜디오).content_fingerprint(d)


def 글요약(d: dict, 여행ID: str, 편: str, 예약시각: str | None = None) -> str:
    """확인 창에 보여 줄 요약: 제목·카테고리·공개·블록 수·사진 수·(예약 시각)·본문 앞부분."""
    블록 = [b for b in d.get("블록") or [] if isinstance(b, dict)]
    사진 = sum(len(b.get("사진")) if isinstance(b.get("사진"), list) else (1 if b.get("사진") else 0) for b in 블록)
    영상 = sum(1 for b in 블록 if b.get("종류") == "영상")
    앞 = " ".join(str(b.get("글") or "") for b in 블록 if b.get("종류") in ("본문", "소제목"))[:160]
    줄 = [f"여행: {여행ID} · 글: {편}", f"제목: {d.get('제목') or '(없음)'}",
         f"카테고리: {d.get('카테고리') or '-'} · 공개: {d.get('공개') or '-'} · AI 활용 설정: {'켬' if d.get('AI활용표시') is True else '끔'}",
         f"블록 {len(블록)}개 · 사진 {사진}장" + (f" · 영상 {영상}개" if 영상 else "")]
    if 예약시각:
        줄.append(f"예약 시각: {예약시각}  (이 시각에 네이버에 공개돼요)")
    if 앞:
        줄.append(f"본문 앞부분: {앞}…")
    return "\n".join(줄)


def 승인확인(data: dict | None, 편: str, 경로: Path | None = None, fresh: bool = False) -> tuple[bool, str]:
    """공용 ApprovalStore.verify 로 확인 → (유효, '' | 승인 안 함 | 승인 뒤 바뀜 | 파일 바뀜 | 무효 | 공용 모듈 없음).
    경로(패키지 파일)를 주면 load_package 로 읽어 업로드 파일 바이트(파일지문)까지 확인 — 재검수 N1."""
    if 경로 is not None:
        try:
            m = 발행연동.모듈(서버설정.스튜디오)
            pkg = m.load_package(경로)
            data = pkg.data
        except (OSError, ValueError, AttributeError):
            return False, "무효"
    if not isinstance(data, dict):
        return False, "승인 안 함"
    a = data.get("승인")
    if not isinstance(a, dict) or a.get("상태") != "승인됨":
        return False, "승인 안 함"
    try:
        api = 공용api()
        저장소 = api.approvals
    except (요청오류, AttributeError):
        return False, "공용 모듈 없음"
    if 경로 is not None:
        ok, 왜 = 저장소.verify(pkg, fresh=fresh)
    else:
        from types import SimpleNamespace
        ok, 왜 = 저장소.verify(SimpleNamespace(data=data, 편ID=편, path=None), require_files=False)
    if ok:
        return True, ""
    if "파일지문" in 왜 or "파일과 지금" in 왜:
        return False, "파일 바뀜"
    return False, "승인 뒤 바뀜" if "바뀌었" in 왜 else "무효"


def 패키지승인옮기기(패키지: Path, 편: str) -> bool:
    """패키지를 다시 만들어 승인 칸이 사라졌어도, 같은 경로의 예전 승인(등록부)과 글 지문·파일지문이 같으면 그 승인을 옮김
    (발행API.md 5.4 — 새로 서명하지 않음. 사람이 [승인 취소]한 것은 등록부에서 지워져 옮길 수 없음)."""
    try:
        m = 발행연동.모듈(서버설정.스튜디오)
        저장소 = 공용api().approvals
        pkg = m.load_package(패키지)
        if 승인확인(None, 편, 패키지)[0]:
            return True
        지문 = m.content_fingerprint(pkg.data)
        파일 = m.files_fingerprint(m.upload_file_hashes(pkg, fresh=True))
        등록부 = 읽기_json(저장소.reg_path, {}) or {}
        후보 = [(서명, r) for 서명, r in 등록부.items() if isinstance(r, dict) and r.get("파일") == str(Path(패키지).resolve())
              and r.get("편ID") == pkg.편ID and r.get("지문") == 지문 and r.get("파일지문") == 파일]
        if not 후보:
            return False
        서명, r = max(후보, key=lambda x: str(x[1].get("시각") or ""))
        data = 고칠_json(패키지)
        if not isinstance(data, dict):
            return False
        data["승인"] = {"상태": "승인됨", "승인자": r.get("승인자") or "", "시각": r.get("시각"), "지문": 지문,
                      "파일지문": 파일, "파일수": len(r.get("파일해시") or []), "서명": 서명}
        원자적_쓰기(패키지, data)
        ok = 승인확인(None, 편, 패키지)[0]
        if ok:
            기록(f"패키지를 다시 만들었지만 글·파일이 승인 때와 같아 예전 승인을 옮김: {편}")
        return ok
    except Exception as e:  # 옮기기는 덤 — 안 되면 사람이 [패키지 승인]
        sys.stderr.write(f"패키지 승인 옮기기 실패: {e!r}\n")
        return False


def 편상태들(p: Path) -> list[dict]:
    편목록 = 편목록읽기(p)
    배치들 = 편파일들(p, "원고", "배치")
    패키지들 = 편파일들(p, "발행", "패키지")
    ids = [x["편ID"] for x in 편목록] + [k for k in 배치들 if k not in {x["편ID"] for x in 편목록}]
    제목안 = {x["편ID"]: x.get("제목안") or x.get("제목") or "" for x in 편목록}
    결과 = []
    for 편 in ids:
        배치 = 읽기_json(배치들[편], {}) if 편 in 배치들 else None
        승인 = (배치 or {}).get("승인") if isinstance((배치 or {}).get("승인"), dict) else {}
        승인됨, 승인이유 = 승인확인(배치, 편) if isinstance(배치, dict) else (False, "")
        패 = 패키지들.get(편)
        결과.append({
            "편ID": 편, "제목": (배치 or {}).get("제목") or 제목안.get(편, ""), "제목안": 제목안.get(편, ""),
            "배치있음": 배치 is not None, "블록수": len((배치 or {}).get("블록") or []),
            "승인": "승인됨" if 승인됨 else ("미승인" if 배치 is not None else None),
            "승인시각": 승인.get("시각") or "" if 승인됨 else "",
            "승인후바뀜": 승인이유 == "승인 뒤 바뀜",
            # '승인됨'이라고 적혀 있지만 서버 서명이 없거나 틀림(예전 승인·다른 프로그램이 적음) → 무효
            "승인무효": 승인이유 == "무효",
            "패키지있음": 패 is not None,
            "패키지오래됨": bool(패 and 편 in 배치들 and (수정시각(패) or 0) < (수정시각(배치들[편]) or 0)),
            "AI활용표시": (배치 or {}).get("AI활용표시") if 배치 is not None else None,
            "AI이미지": AI이미지있음(배치 or {}),
            "AI표기문구": any(isinstance(b, dict) and b.get("역할") == "AI표기" for b in (배치 or {}).get("블록") or []),
        })
    return 결과


def 여행요약(p: Path) -> dict:
    정보 = 읽기_json(p / "여행정보.json", {}) or {}
    목록 = 목록읽기(p)
    항목 = 목록항목(목록) if 목록 is not None else []
    사진 = [x for x in 항목 if isinstance(x, dict) and x.get("종류") != "영상"]
    영상 = [x for x in 항목 if isinstance(x, dict) and x.get("종류") == "영상"]
    기기 = {x.get("기기") for x in 항목 if isinstance(x, dict) and x.get("기기")}
    결정 = Counter((x.get("사용자결정") or "미정") for x in 항목 if isinstance(x, dict))
    편들 = 편상태들(p)
    구성안 = (p / "원고" / "구성안.json").is_file()
    if not 목록:
        단계 = 0
    elif any(x["배치있음"] for x in 편들):
        단계 = 3
    elif 구성안:
        단계 = 2
    else:
        단계 = 1

    def 순위(x):  # 카드 머리 사진 3장: 대표 → 사용 → 대표 후보 → 아무거나
        d = x.get("사용자결정") or "미정"
        return (0 if d == "대표" else 1 if d == "사용" else 2 if (x.get("판정") or {}).get("대표후보") else 3)
    썸네일 = [x.get("썸네일") for x in sorted((x for x in 사진 if x.get("썸네일") and x.get("사용자결정") != "제외"), key=순위)][:3]

    기간 = 정보.get("기간") or {}
    if not (기간.get("시작") and 기간.get("끝")):
        날짜들 = sorted(str(x.get("촬영시각"))[:10] for x in 항목 if isinstance(x, dict) and x.get("촬영시각"))
        if 날짜들:
            기간 = {"시작": 기간.get("시작") or 날짜들[0], "끝": 기간.get("끝") or 날짜들[-1]}
    이력 = 이력읽기(p)
    return {
        "여행ID": p.name, "이름": 정보.get("이름") or p.name, "기간": 기간,
        "원본폴더": 정보.get("원본폴더") or [], "컨셉": 정보.get("컨셉") or "",
        "선택한구성안": 정보.get("선택한구성안") if isinstance(정보.get("선택한구성안"), int) and not isinstance(정보.get("선택한구성안"), bool) else None,
        "목록있음": 목록 is not None, "사진수": len(사진), "영상수": len(영상), "기기수": len(기기),
        "결정": {k: 결정.get(k, 0) for k in 결정값},
        "구성안있음": 구성안, "편들": 편들, "영상결과": 영상결과(p), "영상챕터": "작업/영상/챕터.txt" if (p / "작업" / "영상" / "챕터.txt").is_file() else None,
        "단계": 단계, "썸네일": 썸네일,
        "실패작업수": sum(1 for x in 이력 if x.get("상태") in ("실패", "멈춤") and x.get("발행상태") != "취소"),  # 사람이 취소한 발행은 빼고
    }


def 여행목록() -> dict:
    결과 = []
    if 여행루트().is_dir():
        for p in sorted(여행루트().iterdir(), reverse=True):
            if p.is_dir() and not p.name.startswith("."):
                try:
                    결과.append(여행요약(p))
                except Exception:  # 한 여행이 깨져도 나머지는 보이게
                    traceback.print_exc()
                    결과.append({"여행ID": p.name, "이름": p.name, "오류": "여행 정보를 읽지 못했어요"})
    return {"여행": 결과, "스튜디오폴더": str(서버설정.스튜디오)}


def 파이썬실행파일() -> str:
    """콘솔 없는 pythonw 로 서버가 떠 있어도 자식 프로그램은 출력이 되는 python 으로 실행."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        exe = exe.with_name("python.exe")
    return str(exe)


def 창없이() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


_폴더선택코드 = r'''
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    sys.exit(3)
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)   # 브라우저 뒤에 숨지 않게 맨 앞으로
root.update()
root.lift()
root.focus_force()
경로 = filedialog.askdirectory(parent=root, title=sys.argv[1], mustexist=True)
root.destroy()
print(경로 or "")
'''


def 폴더고르기(제목: str) -> str | None:
    """내 PC의 폴더 선택 창(tkinter). 서버 스레드에서 창을 띄우면 Mac에서 멈추므로 별도 프로그램으로 띄웁니다."""
    try:
        r = subprocess.run([파이썬실행파일(), "-c", _폴더선택코드, 제목], capture_output=True,
                           text=True, encoding="utf-8", timeout=900, **창없이())
    except subprocess.TimeoutExpired:
        return None
    if r.returncode == 3 and sys.platform == "darwin":  # tkinter 가 없는 Mac 파이썬 → 기본 창
        글 = 제목.replace('"', "'")
        r = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{글}")'],
                           capture_output=True, text=True, encoding="utf-8", timeout=900)
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip() or None


def 새여행(데이터: dict) -> dict:
    이름 = str(데이터.get("이름") or "").strip()
    if not 이름:
        raise 요청오류(400, "여행 이름을 적어 주세요")
    if len(이름) > 60:
        raise 요청오류(400, "여행 이름은 60자 안으로 적어 주세요")
    시작 = str(데이터.get("시작일") or "").strip()
    if 시작 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", 시작):
        raise 요청오류(400, "시작일은 2026-09-26 모양으로 적어 주세요")
    폴더 = 데이터.get("원본폴더")
    if not 폴더:
        폴더 = 폴더고르기(f"'{이름}' 사진·영상이 들어 있는 폴더를 골라 주세요 (원본은 읽기만 해요)")
        if not 폴더:
            return {"취소": True, "안내": "폴더를 고르지 않아서 여행을 만들지 않았어요."}
    원본 = Path(str(폴더)).expanduser()
    if not 원본.is_dir():
        raise 요청오류(400, f"폴더를 찾지 못했어요: {폴더}")
    원본 = 원본.resolve()
    if 안쪽인가(원본, 서버설정.스튜디오):
        raise 요청오류(400, "여행스튜디오 폴더 안이 아닌, 사진을 모아 둔 원래 폴더를 골라 주세요")

    앞 = 시작[:7] if 시작 else datetime.now().strftime("%Y-%m")
    몸 = re.sub(r'[\\/:*?"<>|\s]+', "_", 이름).strip("._ ")[:30] or "여행"
    with _스레드잠금:
        여행ID, n = f"{앞}_{몸}", 2
        while (여행루트() / 여행ID).exists():
            여행ID, n = f"{앞}_{몸}-{n}", n + 1
        p = 여행폴더(여행ID, 있어야=False)
        for 하위 in ("작업", "원고", "발행"):
            (p / 하위).mkdir(parents=True, exist_ok=True)
    오프셋 = datetime.now().astimezone().strftime("%z")
    정보 = {
        "여행ID": 여행ID, "이름": 이름, "원본폴더": [원본.as_posix()],
        "기간": {"시작": 시작 or None, "끝": None},
        "시간대": f"{오프셋[:3]}:{오프셋[3:]}" if 오프셋 else "+09:00",
        "하루경계": "04:00", "기기보정초": {}, "컨셉": "", "선택한구성안": None, "숨길장소": ["숙소", "집"],
    }
    원자적_쓰기(p / "여행정보.json", 정보)
    기록(f"새 여행을 만들었어요: {이름}", 여행ID)
    return {"성공": True, "여행ID": 여행ID, "여행정보": 정보}


# ---------------------------------------------------------------- 목록·장소·결정·구성안·승인

def 목록주기(여행ID) -> dict:
    p = 여행폴더(여행ID)
    목록 = 목록읽기(p)
    return {"여행ID": p.name, "여행정보": 읽기_json(p / "여행정보.json", {}) or {},
            "목록있음": 목록 is not None, "항목": 목록항목(목록) if 목록 is not None else [],
            "수정시각": 수정시각(p / "목록.json")}


def 장소주기(여행ID) -> dict:
    p = 여행폴더(여행ID)
    지도 = []
    for 곳 in (p / "작업" / "지도", p / "지도"):
        if 곳.is_dir():
            for f in sorted(곳.glob("*.png"), key=lambda f: _자연순(f.stem)):
                m = re.search(r"(\d+)일차", f.stem)
                지도.append({"일차": int(m.group(1)) if m else None, "이름": f.stem, "경로": 상대경로(f, p)})
    return {"여행ID": p.name, "장소": 읽기_json(p / "장소.json", {}) or {}, "장소있음": (p / "장소.json").is_file(),
            "지도이미지": 지도, "수정시각": 수정시각(p / "장소.json")}


def 결정바꾸기(데이터: dict) -> dict:
    p = 여행폴더(데이터.get("여행") or 데이터.get("여행ID"))
    바꿀것 = 데이터.get("결정목록")
    if 바꿀것 is None:
        바꿀것 = [{"id": 데이터.get("id"), "결정": 데이터.get("결정")}]
    if not isinstance(바꿀것, list) or not 바꿀것 or len(바꿀것) > 5000:
        raise 요청오류(400, "바꿀 사진이 없어요")
    표 = {}
    for x in 바꿀것:
        if not isinstance(x, dict) or not isinstance(x.get("id"), str) or x.get("결정") not in 결정값:
            raise 요청오류(400, f"결정은 {', '.join(결정값)} 중 하나여야 해요")
        표[x["id"]] = x["결정"]
    f = p / "목록.json"
    with _쓰기잠금, 파일잠금(p / ".목록.lock"):
        if not f.is_file():
            raise 요청오류(404, "아직 사진 목록이 없어요")
        목록 = 고칠_json(f)
        if 목록 is None:
            raise 요청오류(404, "아직 사진 목록이 없어요")
        바뀜 = 0
        for 항목 in 목록항목(목록):
            if isinstance(항목, dict) and 항목.get("id") in 표:
                항목["사용자결정"] = 표[항목["id"]]
                바뀜 += 1
        if not 바뀜:
            raise 요청오류(404, "목록에서 그 사진을 찾지 못했어요")
        원자적_쓰기(f, 목록)
    if len(표) == 1:
        (k, v), = 표.items()
        기록(f"사진 결정: {k} → {v}", p.name)
    else:
        기록(f"사진 결정 {len(표)}장: " + ", ".join(f"{k}={v}" for k, v in list(표.items())[:20]), p.name)
    return {"성공": True, "바뀜": 바뀜, "수정시각": 수정시각(f)}


def 구성안선택(데이터: dict) -> dict:
    """사용자가 고른 안 → 원고/편목록.json(그 안의 '편' 배열) + 여행정보.선택한구성안 (규약 2.3)."""
    p = 여행폴더(데이터.get("여행ID") or 데이터.get("여행"))
    번호 = 데이터.get("번호")
    if not isinstance(번호, int) or isinstance(번호, bool):
        raise 요청오류(400, "안 번호는 정수예요")
    구성안 = 읽기_json(p / "원고" / "구성안.json")
    if not isinstance(구성안, dict):
        raise 요청오류(404, "아직 구성안이 없어요")
    def 안번호(a, i):  # 화면과 같은 규칙: 정수 '번호'가 없으면 순서(1부터)
        n = a.get("번호")
        return n if isinstance(n, int) and not isinstance(n, bool) else i
    안 = next((a for i, a in enumerate(구성안.get("안") or [], 1) if isinstance(a, dict) and 안번호(a, i) == 번호), None)
    if not 안:
        raise 요청오류(404, f"{번호}번 안을 찾지 못했어요")
    편 = [x for x in (안.get("편") or []) if isinstance(x, dict)]
    if not 편 or any(not isinstance(x.get("편ID"), str) or not 편ID무늬.fullmatch(x["편ID"]) for x in 편):
        raise 요청오류(409, "이 안의 편 목록(편ID)이 올바르지 않아요. Claude에게 구성안을 다시 부탁해 주세요.")
    with _쓰기잠금, 파일잠금(p / ".여행정보.lock"):
        원자적_쓰기(p / "원고" / "편목록.json", 편)
        정보 = 고칠_json(p / "여행정보.json", {})
        정보["선택한구성안"] = 번호
        원자적_쓰기(p / "여행정보.json", 정보)
    기록(f"구성안 {번호}번 '{안.get('이름', '')}'을 골랐어요: 편 {len(편)}개 ({', '.join(x['편ID'] for x in 편)})", p.name)
    return {"성공": True, "편목록": 편}


def 승인바꾸기(데이터: dict) -> dict:
    p = 여행폴더(데이터.get("여행ID") or 데이터.get("여행"))
    편 = 편확인(데이터.get("편ID") or 데이터.get("편"))
    승인 = 데이터.get("승인", True) is not False
    파일 = 편파일들(p, "원고", "배치").get(편)
    if not 파일:
        raise 요청오류(404, f"'{편}' 글(배치 파일)이 아직 없어요")
    패키지 = 편파일들(p, "발행", "패키지").get(편)
    저장소 = 공용api().approvals  # 공용 ApprovalStore — 서버만 아는 키로 서명·등록(검수 M3)
    같은패키지 = False
    if 승인:  # 사람이 화면에서 누른 것 + 컴퓨터의 확인 창(공용 confirm_approval)에서 마우스로 한 번 더 — 재검수 N2
        미리 = 고칠_json(파일)
        if not isinstance(미리, dict):
            raise 요청오류(409, "글 파일을 읽지 못했어요(Claude가 고치는 중일 수 있어요)")
        패미리 = 고칠_json(패키지) if 패키지 else None
        같은패키지 = isinstance(패미리, dict) and 글내용지문(패미리) == 글내용지문(미리)
        # 같은 글의 패키지가 있으면 그것(올라갈 사진·지도·영상 파일 수까지)을 보여 주고 함께 승인
        예, 이유 = 공용확인("승인", [패키지 if 같은패키지 else 파일])
        if not 예:
            기록(f"글 승인 취소(데스크탑 확인: {이유 or '아니오'}): {편}", p.name)
            raise 요청오류(403, f"컴퓨터의 확인 창에서 승인하지 않았어요({이유 or '아니오를 누름'}).", 코드="데스크탑확인")
    with _쓰기잠금, 파일잠금(p / ".원고.lock"):
        배치 = 고칠_json(파일)
        if not isinstance(배치, dict):
            raise 요청오류(409, "글 파일을 읽지 못했어요(Claude가 고치는 중일 수 있어요)")
        if 승인:
            저장소.approve(파일, approver="사용자(여행 스튜디오 화면)")
        else:
            저장소.revoke(파일)
        배치 = 고칠_json(파일)
        if 패키지:  # 같은 글의 패키지면 패키지 경로로도 approve(그 파일들이 묶임 — 배치 승인 복사는 무효). 아니면 승인 거둠
            패 = 고칠_json(패키지)
            if isinstance(패, dict):
                if 승인 and 같은패키지 and 글내용지문(패) == 글내용지문(배치):
                    저장소.approve(패키지, approver="사용자(여행 스튜디오 화면)")
                else:
                    저장소.revoke(패키지)
    기록(f"글 {'승인' if 승인 else '승인 취소'}: {편} '{배치.get('제목', '')}'", p.name)
    return {"성공": True, "승인": 배치["승인"]}


def 패키지승인(데이터: dict) -> dict:
    """⑦ [패키지 승인]: 글은 승인했는데 패키지를 그 뒤에 만든 경우. 같은 글(글 지문)일 때만, 공용 확인 창 → approve(패키지)."""
    p = 여행폴더(데이터.get("여행ID") or 데이터.get("여행"))
    편 = 편확인(데이터.get("편ID") or 데이터.get("편"))
    배치파일 = 편파일들(p, "원고", "배치").get(편)
    패키지 = 편파일들(p, "발행", "패키지").get(편)
    if not 배치파일 or not 패키지:
        raise 요청오류(404, "글이나 발행 패키지가 아직 없어요")
    배치, 패 = 고칠_json(배치파일), 고칠_json(패키지)
    if not 승인확인(배치, 편)[0]:
        raise 요청오류(409, "먼저 글 화면에서 [이 글 승인]을 눌러 주세요.", 코드="글미승인")
    if not isinstance(패, dict) or 글내용지문(패) != 글내용지문(배치):
        raise 요청오류(409, "발행 패키지의 내용이 승인한 글과 달라요. [발행 패키지 다시 만들어 달라기]를 눌러 주세요.", 코드="패키지_오래됨")
    예, 이유 = 공용확인("승인", [패키지])
    if not 예:
        raise 요청오류(403, f"컴퓨터의 확인 창에서 승인하지 않았어요({이유 or '취소를 누름'}).", 코드="데스크탑확인")
    with _쓰기잠금, 파일잠금(p / ".원고.lock"):
        rec = 공용api().approvals.approve(패키지, approver="사용자(여행 스튜디오 화면, 패키지)")
    기록(f"패키지 승인(올라갈 파일 {rec.get('파일수')}개 묶음): {편}", p.name)
    return {"성공": True, "승인": rec}


def AI표시바꾸기(데이터: dict) -> dict:
    """화면 ⑥ 체크박스 → 배치의 AI활용표시. 사람이 화면에서 바꾼 것이라 승인은 그대로 둠(지문만 새로)."""
    p = 여행폴더(데이터.get("여행ID") or 데이터.get("여행"))
    편 = 편확인(데이터.get("편ID") or 데이터.get("편"))
    켬 = 데이터.get("켬")
    if not isinstance(켬, bool):
        raise 요청오류(400, "켬은 true 또는 false 예요")
    파일 = 편파일들(p, "원고", "배치").get(편)
    if not 파일:
        raise 요청오류(404, f"'{편}' 글(배치 파일)이 아직 없어요")
    패키지 = 편파일들(p, "발행", "패키지").get(편)
    with _쓰기잠금, 파일잠금(p / ".원고.lock"):
        배치 = 고칠_json(파일)
        if not isinstance(배치, dict):
            raise 요청오류(409, "글 파일을 읽지 못했어요(Claude가 고치는 중일 수 있어요)")
        패 = 고칠_json(패키지) if 패키지 else None
        같은패키지 = isinstance(패, dict) and 글내용지문(패) == 글내용지문(배치)
        배치["AI활용표시"] = 켬
        원자적_쓰기(파일, 배치)
        if 같은패키지:  # 같은 글의 패키지면 표시만 맞춤. 공용 승인 지문에는 AI활용표시가 없어 승인은 그대로 유효
            패["AI활용표시"] = 켬
            원자적_쓰기(패키지, 패)
    기록(f"네이버 'AI 활용 설정' {'켬' if 켬 else '끔'}: {편} '{배치.get('제목', '')}'", p.name)
    return {"성공": True, "AI활용표시": 켬}


# ---------------------------------------------------------------- 데스크탑 확인 창(보안 검수 M3)

_확인창코드 = r'''
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
    import tkinter as tk
except Exception:
    sys.exit(3)
제목, 글, 예글 = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "예")
try:
    root = tk.Tk()
except Exception:
    sys.exit(3)
답 = {"예": False}
root.title(제목)
root.attributes("-topmost", True)
t = tk.Text(root, width=72, height=min(24, max(6, 글.count("\n") + 3)), wrap="word", font=("Malgun Gothic", 10))
t.insert("1.0", 글)
t.configure(state="disabled")
t.pack(padx=12, pady=(12, 6), fill="both", expand=True)
줄 = tk.Frame(root)
줄.pack(pady=(0, 12))
# [예]는 키보드 초점을 받지 않고(takefocus=0) 마우스 버튼을 그 위에서 뗄 때만 — Enter·Space·Tab 으로는 못 누름
예 = tk.Button(줄, text=예글, width=22, takefocus=0)
아니오 = tk.Button(줄, text="아니오(취소)", width=12, command=root.destroy)
def 놓음(e):
    if 0 <= e.x < e.widget.winfo_width() and 0 <= e.y < e.widget.winfo_height():
        답["예"] = True
        root.destroy()
예.bind("<ButtonRelease-1>", 놓음)
예.pack(side="left", padx=6)
아니오.pack(side="left", padx=6)
root.protocol("WM_DELETE_WINDOW", root.destroy)
root.bind("<Escape>", lambda _e: root.destroy())
아니오.focus_set()
root.update()
root.lift()
root.focus_force()
root.mainloop()
print("예" if 답["예"] else "아니오")
'''


_공용확인코드 = r'''
import importlib.util, json, sys
sys.stdout.reconfigure(encoding="utf-8")
spec = importlib.util.spec_from_file_location("공용_발행서버", sys.argv[1])
m = importlib.util.module_from_spec(spec); sys.modules["공용_발행서버"] = m; spec.loader.exec_module(m)
종류, 경로들, 시각 = sys.argv[2], json.loads(sys.argv[3]), (sys.argv[4] or None)
try:
    pkgs = [m.load_package(x) for x in 경로들]
    답 = m.confirm_approval(pkgs[0]) if 종류 == "승인" else m.confirm_reserve_job(pkgs, 시각)
except RuntimeError:
    sys.exit(3)
print("예" if 답 else "아니오")
'''


def 공용확인(종류: str, 경로들: list[Path], 시각: str | None = None, 기다림: int = 300) -> tuple[bool, str]:
    """공용 confirm_approval·confirm_reserve_job(마우스로 확인 단추) — 재검수 N2. 별도 프로그램으로 띄움(서버 스레드 tkinter 는 Mac 에서 멈춤).
    창을 못 띄우면 허락하지 않은 것으로 봄. --시험확인(임시 폴더의 시험 서버)일 때만 창 없이 그 답."""
    if 서버설정.시험확인 in ("예", "아니오"):
        기록(f"[시험] 공용 확인 창({종류}) 대신 '{서버설정.시험확인}'")
        return 서버설정.시험확인 == "예", "" if 서버설정.시험확인 == "예" else "시험: 아니오"
    모듈 = 발행연동.모듈경로()
    if not 모듈:
        return False, "공용 발행 모듈이 없음"
    try:
        r = subprocess.run([파이썬실행파일(), "-c", _공용확인코드, 모듈, 종류, json.dumps([str(x) for x in 경로들], ensure_ascii=False), 시각 or ""],
                           capture_output=True, text=True, encoding="utf-8", timeout=기다림, **창없이())
    except subprocess.TimeoutExpired:
        return False, "확인 창에서 답이 없음"
    except OSError as e:
        return False, f"확인 창을 띄우지 못함: {e}"
    if r.returncode != 0:
        return False, "확인 창을 띄우지 못함"
    답 = (r.stdout or "").strip().splitlines()[-1:] or [""]
    return 답[0] == "예", "" if 답[0] == "예" else "취소를 누름"


def 데스크탑확인(제목: str, 글: str, 기다림: int = 180, 예글: str = "예") -> tuple[bool, str]:
    """내 PC 화면에 확인 창을 띄워 사람이 [예]를 눌렀는지. 브라우저 밖의 창이라 화면 자동화·Claude 가 대신 누르기 어려움.
    창을 못 띄우면 허락하지 않은 것으로 봄(fail-closed)."""
    if 서버설정.시험확인 in ("예", "아니오"):
        기록(f"[시험] 데스크탑 확인 창 대신 '{서버설정.시험확인}': {제목}")
        return 서버설정.시험확인 == "예", "" if 서버설정.시험확인 == "예" else "시험: 아니오"
    try:
        r = subprocess.run([파이썬실행파일(), "-c", _확인창코드, 제목, 글, 예글], capture_output=True,
                           text=True, encoding="utf-8", timeout=기다림, **창없이())
    except subprocess.TimeoutExpired:
        return False, "확인 창에서 답이 없음"
    except OSError as e:
        return False, f"확인 창을 띄우지 못함: {e}"
    if r.returncode == 3 and sys.platform == "darwin":  # tkinter 없는 Mac 파이썬 → 기본 대화상자
        q = lambda t: t.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
        try:
            r = subprocess.run(["osascript", "-e", f'display dialog "{q(글)}" with title "{q(제목)}" '
                                f'buttons {{"아니오", "예"}} default button "아니오" with icon caution giving up after {기다림}'],
                               capture_output=True, text=True, encoding="utf-8", timeout=기다림 + 10)
        except (OSError, subprocess.TimeoutExpired):
            return False, "확인 창을 띄우지 못함"
        return ("button returned:예" in (r.stdout or "")), ""
    if r.returncode != 0:
        return False, "확인 창을 띄우지 못함"
    답 = (r.stdout or "").strip().splitlines()[-1:] or [""]
    return 답[0] == "예", "" if 답[0] == "예" else "아니오를 누름"


# ---------------------------------------------------------------- 설정(자동 예약 발행 — 규약 9절)

def 설정파일() -> Path:
    return 서버설정.스튜디오 / "설정.json"


def 설정이름바꾸기(d: dict) -> tuple[dict, bool]:
    """옛 이름(최소간격초·중단판정초, 초 단위)이 있으면 새 이름(분)으로 옮김. 새 이름이 이미 있으면 새 이름을 씀."""
    d, 바뀜 = dict(d), False
    for 옛, (새, 나눔) in 옛설정키.items():
        if 옛 in d:
            v = d.pop(옛)
            바뀜 = True
            if 새 not in d and isinstance(v, (int, float)) and not isinstance(v, bool):
                d[새] = max(1, round(v / 나눔))
    return d, 바뀜


def 사용자설정() -> dict:
    """화면이 쓰는 설정 항목(기본값 포함, 모양이 틀린 값은 기본값). 파일의 다른 항목은 여기서 보이지 않을 뿐 지우지 않음."""
    d = 읽기_json(설정파일(), {})
    if not isinstance(d, dict):
        d = {}
    d, _ = 설정이름바꾸기(d)
    결과 = dict(기본사용자설정)
    for k, 기본 in 기본사용자설정.items():
        v = d.get(k)
        if k in 설정범위:
            lo, hi = 설정범위[k]
            if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
                결과[k] = v
        elif isinstance(v, type(기본)):
            결과[k] = v
    if 결과["브라우저"] not in 브라우저들:
        결과["브라우저"] = 기본사용자설정["브라우저"]
    if 결과["자동예약발행"] and not 자동예약허락():  # 사람이 화면에서 켠 기록이 없으면 꺼진 것으로(검수 M3)
        결과["자동예약발행"] = False
    return 결과


def 자동예약허락() -> bool:
    try:
        a = 발행연동.api(서버설정.스튜디오, 서버설정.포트, _공용설정, 발행사건)
        return bool(a and a.approvals.auto_reserve_allowed()[0])
    except Exception:
        return False


def 설정옮겨적기() -> bool:
    """서버를 켤 때 한 번: 설정.json 에 옛 이름이 있으면 새 이름으로 고쳐 저장(모르는 키는 그대로)."""
    파일 = 설정파일()
    if not 파일.is_file():
        return False
    try:
        with _쓰기잠금, 파일잠금(서버설정.스튜디오 / ".설정.lock"):
            원래 = 고칠_json(파일, {})
            if not isinstance(원래, dict):
                return False
            새것, 바뀜 = 설정이름바꾸기(원래)
            if 바뀜:
                원자적_쓰기(파일, 새것)
    except Exception as e:  # 설정 옮기기 때문에 서버가 안 켜지면 안 됨(읽을 때도 옮겨 읽음)
        sys.stderr.write(f"설정.json 옛 이름 옮기기 실패: {e!r}\n")
        return False
    if 바뀜:
        기록("설정.json 의 옛 이름(최소간격초·중단판정초)을 새 이름(편사이간격분·중단판정분)으로 옮겼어요")
    return 바뀜


def 설정바꾸기(데이터: dict) -> dict:
    """바꾼 항목만 합쳐서 저장(모르는 키 보존 — 다른 프로그램·단체 블로그 설정과 함께 써도 안전)."""
    고칠것: dict = {}
    허락바꿈 = False
    if "자동예약발행" in 데이터:
        켜기 = 데이터["자동예약발행"] is True
        if 켜기 and 데이터.get("위험확인") is not True:
            raise 요청오류(400, "자동 예약 발행을 켜려면 경고를 읽고 확인해 주세요", 경고=예약경고)
        if 켜기 and not 사용자설정().get("자동예약발행"):
            예, 이유 = 데스크탑확인("여행 스튜디오 — 자동 예약 발행 켜기",
                               "승인한 글을 블로그 도우미가 네이버에 예약 발행하게 할까요?\n\n" + 예약경고 +
                               "\n\n직접 켠 것이 맞으면 [예]를 누르세요.")
            if not 예:
                기록(f"자동 예약 발행 켜기 취소(데스크탑 확인: {이유 or '아니오'})")
                raise 요청오류(403, f"컴퓨터의 확인 창에서 허락하지 않아 켜지 않았어요({이유 or '아니오를 누름'}).", 코드="데스크탑확인")
        고칠것["자동예약발행"] = 켜기
        허락바꿈 = 켜기
    if "브라우저" in 데이터:
        if 데이터["브라우저"] not in 브라우저들:
            raise 요청오류(400, "브라우저는 chrome(Chrome), edge(Edge), default(기본 브라우저) 중 하나예요")
        고칠것["브라우저"] = 데이터["브라우저"]
    if "블로그ID" in 데이터:
        아이디 = str(데이터["블로그ID"] or "").strip()
        if 아이디 and not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", 아이디):
            raise 요청오류(400, "블로그 아이디는 영문·숫자로 적어 주세요(blog.naver.com/ 뒤의 부분)")
        고칠것["블로그ID"] = 아이디
    for k, (lo, hi) in 설정범위.items():
        if k in 데이터:
            v = 데이터[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise 요청오류(400, f"{k}은(는) {lo}~{hi} 사이의 정수(분)로 적어 주세요")
            고칠것[k] = v
    if "자동예약발행" in 고칠것:  # 공용 모듈: 설정 글자만으로는 안 켜짐 — 사람이 켠 서명 기록(자동예약허락.json)이 있어야
        저장소 = 공용api().approvals
        if 허락바꿈:
            저장소.allow_auto_reserve("여행 스튜디오 화면(데스크탑 확인)")
        else:
            저장소.disallow_auto_reserve()
    if 고칠것:
        with _쓰기잠금, 파일잠금(서버설정.스튜디오 / ".설정.lock"):
            원래 = 고칠_json(설정파일(), {})
            if not isinstance(원래, dict):
                raise 요청오류(409, "설정.json 모양이 달라요({…} 이어야 함). Claude에게 '설정.json 고쳐줘'라고 부탁해 주세요.")
            원래, _ = 설정이름바꾸기(원래)
            원래.update(고칠것)  # 바꾼 항목만 덮어씀
            원자적_쓰기(설정파일(), 원래)
        for k, v in 고칠것.items():
            기록(f"설정: {k} = {'(없음)' if v == '' else ('켬' if v is True else '끔' if v is False else v)}")
    return {"성공": True, "설정": 사용자설정(), "경고": 예약경고}


# ---------------------------------------------------------------- 작업함(상태·질문·답변·요청)

def 안전한파일이름(이름) -> str:
    if not isinstance(이름, str) or not 이름 or 이름.startswith(".") or len(이름) > 150 \
            or re.search(r'[\\/:*?"<>|\x00-\x1f]', 이름):
        raise 요청오류(400, "이름이 올바르지 않아요")
    return 이름


def 처리안된파일(폴더: Path) -> list[Path]:
    완료 = {f.name for f in 작업함("처리완료").glob("*.json")}
    if not 폴더.is_dir():
        return []
    return sorted(f for f in 폴더.glob("*.json") if not f.name.startswith(".") and f.name not in 완료)


# ---- 알림(상태.json "알림"·"지난알림"): 항목은 글자 또는 {"글","시각","키"} — 키가 같은 새 알림이 오면 옛것은 지난 알림으로

def _알림항목(x) -> dict | None:
    if isinstance(x, str):
        return {"글": x, "시각": None, "키": None}
    if isinstance(x, dict) and isinstance(x.get("글"), str):
        return {"글": x["글"], "시각": x.get("시각"), "키": x.get("키"), "해결": x.get("해결")}
    return None


def 알림id(x: dict) -> str:
    return hashlib.sha1(f"{x.get('시각')}|{x.get('글')}".encode("utf-8")).hexdigest()[:10]


def _자동해결(x: dict, 연결수: int, 작업시작: dict) -> str | None:
    """조건이 풀리면 저절로 지난 알림으로: 확장 연결 필요 → 확장이 연결됨, 패키지 만듦 → 그 편 임시저장 작업 시작.
    하루 지난 알림도 지난 것으로."""
    키 = str(x.get("키") or "")
    if 키 == "확장연결필요" and 연결수 > 0:
        return "확장이 연결됨"
    t = 시각읽기(x.get("시각"))
    if 키.startswith("패키지:") and t:
        시작 = 시각읽기(작업시작.get(키[len("패키지:"):]))
        if 시작 and 시작 >= t:
            return "임시저장 작업을 시작함"
    if t and (datetime.now().astimezone() - t).total_seconds() > 86400:
        return "하루가 지남"
    return None


def 알림나누기(상태: dict) -> tuple[list, list]:
    연결수, 작업시작 = 0, {}
    if 상태.get("알림"):
        try:
            a = 발행연동.api(서버설정.스튜디오, 서버설정.포트, _공용설정, 발행사건)
            if a:
                연결수 = len((a.pairing.connections() or {}).get("연결") or [])
                for j in a.jobs.list():  # 편마다 마지막 작업을 만든 시각
                    작업시작[f"{j.get('여행ID')}/{j.get('편ID')}"] = j.get("만든시각")
        except Exception:
            pass
    지금것, 지난것 = [], []
    for x in 상태.get("알림") or []:
        y = _알림항목(x)
        if not y:
            continue
        y["id"] = 알림id(y)
        왜 = _자동해결(y, 연결수, 작업시작)
        if 왜:
            y["해결"] = 왜
            지난것.append(y)
        else:
            지금것.append(y)
    for x in 상태.get("지난알림") or []:
        y = _알림항목(x)
        if y:
            y["id"] = 알림id(y)
            지난것.append(y)
    return 지금것[-20:], 지난것[-30:]


def 알림바꾸기(데이터: dict) -> dict:
    """화면의 [지우기]·[모두 지우기]: 알림을 지우지 않고 '지난 알림'으로 옮김."""
    동작 = 데이터.get("동작")
    if 동작 not in ("지우기", "모두지우기"):
        raise 요청오류(400, "동작은 지우기 또는 모두지우기예요")
    옮김 = 0
    with _쓰기잠금, 파일잠금(작업함(".상태.lock"), 기다림=5, 오래됨=15):
        상태 = 고칠_json(작업함("상태.json"), {}, 깨지면_새로=True)
        if not isinstance(상태, dict):
            상태 = {}
        남김, 지난 = [], list(상태.get("지난알림") or [])
        for x in 상태.get("알림") or []:
            y = _알림항목(x)
            if y and (동작 == "모두지우기" or 알림id(y) == 데이터.get("id")):
                지난.append({**y, "해결": "사람이 지움", "해결시각": 지금()})
                옮김 += 1
            else:
                남김.append(x)
        상태["알림"], 상태["지난알림"] = 남김, 지난[-30:]
        if 옮김:
            원자적_쓰기(작업함("상태.json"), 상태)
    return {"성공": True, "옮김": 옮김}


def 진행중인가(x: dict) -> bool:
    상태 = x.get("상태")
    if 상태:
        return 상태 == "진행중"
    # v1 모양(상태 없음): 완료·멈춤 단계가 아니고 100% 전이면 진행 중으로 봄
    return str(x.get("단계", "")) not in ("완료", "끝", "멈춤", "실패") and not (
        isinstance(x.get("퍼센트"), (int, float)) and x["퍼센트"] >= 100)


def _발행멈춤거르기(멈춤: list) -> list:
    """'작업이 멈췄어요' 띠에서 뺄 발행 작업(n…): 사람이 취소한 것, 다시 시도해 이미 진행·완료된 것,
    그 글을 뒤에 다른 작업으로 임시저장한 것(실패를 넘어감), 작업 파일이 없어진 것. Claude 작업(t…)은 그대로."""
    if not any(str(x.get("작업ID") or "").startswith("n") for x in 멈춤):
        return 멈춤
    try:
        a = 발행연동.api(서버설정.스튜디오, 서버설정.포트, _공용설정, 발행사건)
        m = 발행연동.모듈(서버설정.스튜디오)
        작업들 = a.jobs.list() if a else []
    except Exception:
        return 멈춤
    표 = {j.get("작업ID"): j for j in 작업들}
    저장끝 = {}
    for j in 작업들:
        if j.get("상태") in m.FINISHED_OK:
            k = (j.get("여행ID"), j.get("편ID"))
            저장끝[k] = max(저장끝.get(k, ""), j.get("끝") or "")

    def 지난것(x) -> bool:
        if not str(x.get("작업ID") or "").startswith("n"):
            return False
        j = 표.get(x.get("작업ID"))
        if not j:  # 작업 파일이 없어진 발행 작업(다시 할 수 없음)
            return True
        if j.get("상태") != "실패":  # 취소(사람이 정함)·다시 시도 중·끝남
            return True
        return 저장끝.get((j.get("여행ID"), j.get("편ID")), "") > (j.get("끝") or "")
    return [x for x in 멈춤 if not 지난것(x)]


def 상태주기(여행ID=None) -> dict:
    상태 = 읽기_json(작업함("상태.json"), {}) or {}
    if not isinstance(상태, dict):
        상태 = {}
    지금시각 = datetime.now().astimezone()
    신호 = 시각읽기((상태.get("연결") or {}).get("마지막신호"))
    신호초 = (지금시각 - 신호).total_seconds() if 신호 else None
    진행 = [x for x in (상태.get("진행") or []) if isinstance(x, dict)]
    최근진행, 멈춤 = [], []
    for x in 진행:
        t = 시각읽기(x.get("갱신"))
        if not t:
            continue
        경과 = (지금시각 - t).total_seconds()
        if 경과 <= 600 and 진행중인가(x):
            최근진행.append(x)
        if 경과 <= 86400 and (x.get("상태") in ("실패", "멈춤") or (not x.get("상태") and x.get("단계") in ("실패", "멈춤"))):
            멈춤.append(x)
    최근진행.sort(key=lambda x: x.get("갱신") or "", reverse=True)
    멈춤 = _발행멈춤거르기(멈춤)
    멈춤.sort(key=lambda x: x.get("갱신") or "", reverse=True)
    if 신호초 is not None and -5 <= 신호초 <= 10:
        판정 = "연결됨"
    elif 최근진행:
        판정 = "작업중"
    else:
        판정 = "끊김"

    대기 = []
    for f in 처리안된파일(작업함("요청")):
        d = 읽기_json(f, {}) or {}
        대기.append({"파일": f.name, "id": d.get("id"), "종류": d.get("종류"), "여행ID": d.get("여행ID"),
                   "내용": d.get("내용") if isinstance(d.get("내용"), dict) else {}, "보낸시각": d.get("보낸시각")})
    기다리는질문 = sum(1 for q in 질문들() if q["상태"] == "기다림")
    지금알림, 지난알림 = 알림나누기(상태)
    공용 = _공용확인["결과"]
    결과 = {
        "연결": {"판정": 판정, "마지막신호": (상태.get("연결") or {}).get("마지막신호"),
               "신호초": round(신호초, 1) if 신호초 is not None else None,
               "작업": 최근진행[0] if 최근진행 else None},
        "진행": 진행, "멈춤": 멈춤[:5],
        "알림": 지금알림, "지난알림": 지난알림,
        "대기요청": 대기, "대기요청수": len(대기), "기다리는질문": 기다리는질문,
        "서버시각": 지금(), "설정": 사용자설정(),
    }
    if 서버설정.시험확인:
        결과["시험확인"] = 서버설정.시험확인
    if 공용 and 공용.get("갱신필요"):
        결과["공용"] = {"갱신필요": True, "바뀐것": 공용["바뀐것"]}
    if 여행ID:
        try:
            p = 여행폴더(여행ID)
            결과["파일시각"] = {
                "정보": 수정시각(p / "여행정보.json"),
                "목록": 수정시각(p / "목록.json"),
                "장소": 수정시각(p / "장소.json"),
                "지도": 수정시각(*(p / "작업" / "지도").glob("*.png")) if (p / "작업" / "지도").is_dir() else None,
                "구성안": 수정시각(p / "원고" / "구성안.json", p / "원고" / "편목록.json"),
                "배치": 수정시각(*편파일들(p, "원고", "배치").values()),
                "패키지": 수정시각(*편파일들(p, "발행", "패키지").values()),
                "영상": 수정시각(*(p / x for x in 영상결과(p))),
                "이력": 수정시각(p / "작업이력.json"),
            }
        except 요청오류:
            결과["파일시각"] = None
    return 결과


def 요청찾기(요청id) -> dict | None:
    """질문의 '관련요청' id 로 요청 파일을 찾아 여행ID·종류를 알아냅니다."""
    if not isinstance(요청id, str) or not 요청id:
        return None
    if 요청id in _요청캐시:
        return _요청캐시[요청id]
    m = re.fullmatch(r"r_(\d{8}-\d{6}-\d{3})_[0-9a-f]+", 요청id)
    무늬 = f"{m.group(1)}_*.json" if m else "*.json"  # 요청 파일 이름은 '<시각>_<종류>.json'
    for 폴더 in (작업함("요청"), 작업함("처리완료")):
        if not 폴더.is_dir():
            continue
        for f in 폴더.glob(무늬):
            d = 읽기_json(f)
            if isinstance(d, dict) and d.get("id") == 요청id:
                with _스레드잠금:
                    _요청캐시[요청id] = {"여행ID": d.get("여행ID"), "종류": d.get("종류")}
                return _요청캐시[요청id]
    return None


def 질문들(여행ID=None) -> list[dict]:
    폴더 = 작업함("질문")
    if not 폴더.is_dir():
        return []
    결과 = []
    for f in 폴더.glob("*.json"):
        if f.name.startswith("."):
            continue
        q = 읽기_json(f)
        if not isinstance(q, dict):
            continue  # Claude 가 쓰는 중이면 다음 번에
        qid = str(q.get("id") or f.stem)
        답 = None
        if (작업함("처리완료") / f"{qid}.json").is_file():
            상태, 답 = "처리됨", 읽기_json(작업함("처리완료") / f"{qid}.json")
        elif (작업함("답변") / f"{qid}.json").is_file():
            상태, 답 = "답함", 읽기_json(작업함("답변") / f"{qid}.json")
        else:
            상태 = "기다림"
        요청 = 요청찾기(q.get("관련요청")) or {}
        결과.append({**q, "id": qid, "파일": f.name, "상태": 상태, "답변": 답,
                   "여행ID": q.get("여행ID") or 요청.get("여행ID"), "관련종류": 요청.get("종류"),
                   "_시각": q.get("보낸시각") or datetime.fromtimestamp(f.stat().st_mtime).astimezone().isoformat()})
    if 여행ID:
        결과 = [q for q in 결과 if not q["여행ID"] or q["여행ID"] == 여행ID]
    결과.sort(key=lambda q: q["_시각"])
    return 결과


def 질문주기(여행ID=None) -> dict:
    목록 = 질문들(여행ID)
    목록캐시: dict[str, dict] = {}  # 사진 id → 썸네일·기기·시각(질문 카드에 사진을 보여 주려고)
    for q in 목록:
        ids = q.get("사진") or []
        tid = q.get("여행ID") or 여행ID
        if not ids or not tid:
            q["사진정보"] = []
            continue
        if tid not in 목록캐시:
            try:
                목록캐시[tid] = {x.get("id"): x for x in 목록항목(목록읽기(여행폴더(tid))) if isinstance(x, dict)}
            except 요청오류:
                목록캐시[tid] = {}
        표 = 목록캐시[tid]
        q["사진정보"] = [{"id": i, "썸네일": (표.get(i) or {}).get("썸네일"), "미리보기": (표.get(i) or {}).get("미리보기"),
                       "기기": (표.get(i) or {}).get("기기"), "촬영시각": (표.get(i) or {}).get("촬영시각"),
                       "장면설명": (표.get(i) or {}).get("장면설명")} for i in ids if isinstance(i, str)]
    for q in 목록:
        q.pop("_시각", None)
    return {"질문": 목록, "기다리는수": sum(1 for q in 목록 if q["상태"] == "기다림")}


def 답변저장(데이터: dict) -> dict:
    qid = 안전한파일이름(데이터.get("질문id"))
    q = 읽기_json(작업함("질문") / f"{qid}.json")
    if not isinstance(q, dict):
        raise 요청오류(404, "그 질문을 찾지 못했어요")
    if (작업함("처리완료") / f"{qid}.json").exists():
        raise 요청오류(409, "이미 Claude가 처리한 질문이에요")
    선택 = 데이터.get("선택") or []
    if isinstance(선택, str):
        선택 = [선택]
    if not isinstance(선택, list):
        raise 요청오류(400, "선택은 목록이어야 해요")
    선택 = [str(x) for x in 선택][:50]
    if q.get("선택지"):
        선택 = [x for x in 선택 if x in q["선택지"]]
    if not q.get("여러개선택"):
        선택 = 선택[:1]
    입력 = str(데이터.get("입력") or "").strip()[:4000]
    if not 선택 and not 입력:
        raise 요청오류(400, "답을 고르거나 적어 주세요")
    답 = {"질문id": qid, "선택": 선택, "입력": 입력, "보낸시각": 지금()}
    원자적_쓰기(작업함("답변") / f"{qid}.json", 답)
    기록(f"질문에 답함: {q.get('제목', qid)} → {', '.join(선택) or ''} {입력[:80]}", q.get("여행ID"))
    return {"성공": True, "답변": 답}


def 요청만들기(데이터: dict) -> dict:
    종류 = 데이터.get("종류")
    if 종류 not in 요청종류:
        raise 요청오류(400, f"모르는 요청 종류예요: {종류}")
    여행ID = 데이터.get("여행ID") or 데이터.get("여행")
    if 여행ID:
        여행ID = 여행폴더(여행ID).name
    elif 종류 != "자유요청":
        raise 요청오류(400, "어느 여행인지 알려 주세요(여행ID)")
    내용 = 데이터.get("내용") or {}
    if not isinstance(내용, dict):
        raise 요청오류(400, "내용은 {…} 모양이어야 해요")
    if 내용.get("편ID") is not None:
        편확인(내용["편ID"])
    if 종류 in ("글쓰기", "수정요청", "임시저장") and not 내용.get("편ID"):
        raise 요청오류(400, "어느 편인지 알려 주세요(편ID)")
    if 종류 == "재시도" and not (isinstance(내용.get("작업ID"), str) and 내용["작업ID"]):
        raise 요청오류(400, "다시 할 작업ID를 알려 주세요")
    if 종류 == "영상" and 내용.get("음악파일") is not None:  # 여행/<ID>/음악/ 안의 오디오 파일 이름만(도구 영상만들기.py 와 같은 규칙)
        이름 = 내용["음악파일"]
        if not isinstance(이름, str) or not re.fullmatch(r"[^\\/:*?\"<>|\x00-\x1f]{1,120}", 이름) or 이름.startswith(".") \
                or Path(이름).suffix.lower() not in 음악확장자:
            raise 요청오류(400, f"음악은 여행/{여행ID}/음악/ 폴더에 넣은 오디오 파일(mp3·m4a·aac·wav·ogg·flac)의 이름만 적어 주세요")
    # 같은 요청을 두 번 누른 경우: 아직 처리 전인 똑같은 요청이 있으면 새로 만들지 않음
    for f in 처리안된파일(작업함("요청")):
        d = 읽기_json(f) or {}
        if d.get("종류") == 종류 and d.get("여행ID") == 여행ID and d.get("내용") == 내용:
            return {"성공": True, "중복": True, "id": d.get("id"), "파일": f.name}
    with _스레드잠금:
        while True:
            시각 = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
            파일 = 작업함("요청") / f"{시각}_{종류}.json"
            if not 파일.exists():
                break
            time.sleep(0.002)
        요청 = {"id": f"r_{시각}_{secrets.token_hex(2)}", "종류": 종류, "여행ID": 여행ID,
              "내용": 내용, "보낸시각": 지금()}
        원자적_쓰기(파일, 요청)
    덧 = " ".join(f"{k}={v}" for k, v in 내용.items() if k in ("편ID", "작업ID", "처음부터", "블록번호"))
    기록(f"요청 보냄: {종류} {덧} ({요청['id']})", 여행ID)
    return {"성공": True, "id": 요청["id"], "파일": 파일.name}


def 폴더열기(데이터: dict) -> dict:
    """화면 ⑧ [음악 폴더 열기]: 여행/<ID>/음악/ 을(없으면 만들고) 내 PC 파일 탐색기로 엶. 다른 폴더는 안 엶."""
    p = 여행폴더(데이터.get("여행ID") or 데이터.get("여행"))
    if 데이터.get("폴더") != "음악":
        raise 요청오류(400, "열 수 있는 폴더는 '음악'뿐이에요")
    폴더 = p / "음악"
    폴더.mkdir(exist_ok=True)
    결과 = {"성공": True, "폴더": f"여행/{p.name}/음악/", "열림": False}
    if not 서버설정.브라우저열기:  # 시험 모드(--브라우저끄기): 실제로 열지 않음
        결과["시험모드"] = True
        return 결과
    try:
        if os.name == "nt":
            os.startfile(str(폴더))  # noqa: S606 — 내 PC 의 정해진 폴더
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(폴더)])
        else:
            subprocess.Popen(["xdg-open", str(폴더)])
        결과["열림"] = True
    except OSError as e:
        결과["이유"] = f"폴더를 열지 못했어요: {e}"
    return 결과


def 꿀팁노트() -> dict:
    f = 서버설정.스튜디오 / "꿀팁노트.md"
    try:
        글 = f.read_text(encoding="utf-8-sig")
    except OSError:
        글 = ""
    항목 = [줄[2:].strip() for 줄 in 글.splitlines() if 줄.startswith(("- ", "* ")) and 줄[2:].strip()]
    return {"있음": f.is_file(), "항목": 항목, "글": 글}


# ---------------------------------------------------------------- 작업 이력(규약 2.6) — 서버는 읽기만

def 이력읽기(p: Path) -> list[dict]:
    d = 읽기_json(p / "작업이력.json", [])
    if isinstance(d, dict):
        d = d.get("이력") or []
    return [x for x in (d or []) if isinstance(x, dict) and x.get("작업ID")]


def 표시상태(x: dict) -> str:
    상태 = x.get("상태") or "진행중"
    if 상태 == "성공":
        return "재시도 완료" if (x.get("재시도횟수") or 0) > 0 else "성공"
    if 상태 in ("실패", "멈춤") and str(x.get("재시도") or "").startswith("불가"):
        return "재시도 불가"
    return 상태


def 이력주기(여행ID) -> dict:
    p = 여행폴더(여행ID)
    이력 = 이력읽기(p)
    재시도중 = {(r.get("내용") or {}).get("작업ID") for r in 상태주기()["대기요청"] if r.get("종류") == "재시도"}
    for x in 이력:
        x["표시상태"] = 표시상태(x)
        x["재시도요청중"] = x["작업ID"] in 재시도중
    이력.sort(key=lambda x: str(x.get("시작") or ""), reverse=True)
    return {"여행ID": p.name, "이력": 이력, "요약": dict(Counter(x["표시상태"] for x in 이력))}


# ---------------------------------------------------------------- Claude 연결(딥링크)

def claude연결() -> dict:
    문구 = "여행 스튜디오 연결해줘"
    폴더 = str(서버설정.스튜디오)
    주소 = f"claude://code/new?q={quote(문구, safe='')}&folder={quote(폴더, safe='')}"
    안내 = f"Claude 앱의 Code 탭에서 이 폴더를 열고 '{문구}'라고 입력하세요."
    결과 = {"주소": 주소, "폴더": 폴더, "문구": 문구, "안내": 안내, "열림": False}
    if not 서버설정.딥링크열기:
        결과["시험모드"] = True
        return 결과
    try:
        if os.name == "nt":
            import winreg
            try:  # Claude 앱이 claude:// 주소를 등록했는지 먼저 확인(없으면 '앱 찾기' 창이 뜨므로)
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "claude"))
            except OSError:
                결과["이유"] = "이 컴퓨터에서 claude:// 주소를 여는 앱을 찾지 못했어요(Claude 데스크탑 앱 설치 확인)."
                return 결과
            os.startfile(주소)  # type: ignore[attr-defined]
        else:
            명령 = ["open", 주소] if sys.platform == "darwin" else ["xdg-open", 주소]
            if subprocess.run(명령, capture_output=True, timeout=15).returncode != 0:
                결과["이유"] = "Claude 앱을 열지 못했어요."
                return 결과
        결과["열림"] = True
        기록("Claude 연결하기: Claude 앱 열기 요청")
    except Exception as e:  # 딥링크가 안 되는 환경 → 화면이 명령 백업을 안내
        결과["이유"] = f"Claude 앱을 열지 못했어요: {e}"
    return 결과


# ---------------------------------------------------------------- 미리보기

def 미리보기(여행ID, 편ID, 보기="pc") -> str:
    p = 여행폴더(여행ID)
    배치파일 = 편파일들(p, "원고", "배치").get(편ID)
    if not 배치파일:
        raise 요청오류(404, f"'{편ID}' 글(배치 파일)이 아직 없어요")
    도구 = 발행연동.공용파일(서버설정.스튜디오, "미리보기.py")
    if 도구:
        # 미리보기 도구는 배치 폴더(원고/) 안에만 쓸 수 있음(공용 미리보기.py 보안 제한). 그런데 원고/ 는 Claude 가 쓸 수 있는 곳 →
        # 매번 이름을 알 수 없는 임시 파일에 만들고 바로 읽은 뒤 지우고, 내용은 서버 메모리에만 둠(거기 심어 둔 html 을 내주지 않음)
        원본시각 = 수정시각(배치파일, p / "목록.json", 도구, 도구.with_name("템플릿.html")) or 0
        열쇠 = str(배치파일.resolve())
        with _미리보기잠금:
            캐시 = _미리보기캐시.get(열쇠)
            if not 캐시 or 캐시[0] != 원본시각:
                출력 = 배치파일.with_name(f".미리보기_{secrets.token_hex(8)}.html")
                명령 = [파이썬실행파일(), str(도구), str(배치파일), "--출력", str(출력)]
                if (p / "목록.json").is_file():
                    명령 += ["--목록", str(p / "목록.json")]
                try:
                    r = subprocess.run(명령, capture_output=True, text=True, encoding="utf-8", timeout=120, **창없이())
                    if r.returncode != 0:
                        기록(f"미리보기 도구 오류({편ID}): {(r.stderr or '')[-400:]}", p.name, "오류")
                    elif 출력.is_file():
                        _미리보기캐시[열쇠] = (원본시각, 출력.read_text(encoding="utf-8"))
                except (OSError, subprocess.TimeoutExpired) as e:
                    기록(f"미리보기 도구 실행 실패({편ID}): {e}", p.name, "오류")
                finally:
                    출력.unlink(missing_ok=True)
            캐시 = _미리보기캐시.get(열쇠)
        if 캐시:
            글 = _미리보기주소(캐시[1], 배치파일.parent, p)
            if 보기 == "모바일":
                글 = 글.replace("</body>", "<script>document.getElementById('mo')&&document.getElementById('mo').click()</script></body>", 1)
            return 글
    return 간단미리보기(p, 배치파일, 보기)


def _미리보기주소(글: str, 출력폴더: Path, p: Path) -> str:
    """미리보기 도구가 만든 상대 주소(../여행/<ID>/작업/미리보기/p0001.jpg)를 /파일/<ID>/… 로. 여행 폴더 밖은 지움."""
    def 바꾸기(m):
        속성, 값 = m.group(1), m.group(2)
        if not 값 or 값.startswith("#"):
            return m.group(0)
        if 값.startswith("//") or re.match(r"^[a-z][a-z0-9+.\-]*:", 값, re.I):  # 다른 출처·스킴
            # 참고자료 링크(http·https)만 그대로, 그림은 data:image 만. javascript: 등은 지움
            if (속성 == "href" and re.match(r"^https?://", 값, re.I)) or (속성 != "href" and 값.lower().startswith("data:image/")):
                return m.group(0)
            return f'{속성}=""'
        if 값.startswith("/"):
            return m.group(0) if 값.startswith(("/파일/", "/%ED%8C%8C%EC%9D%BC/")) else f'{속성}=""'
        try:
            실제 = (출력폴더 / unquote(값)).resolve()
        except (OSError, ValueError):
            return f'{속성}=""'
        if not 안쪽인가(실제, p):
            return f'{속성}=""'
        return f'{속성}="{quote("/파일/" + p.name + "/" + 상대경로(실제, p))}"'
    return re.sub(r'\b(src|href|poster)="([^"]*)"', 바꾸기, 글)


def 간단미리보기(p: Path, 배치파일: Path, 보기: str) -> str:
    """공용 미리보기 도구가 없을 때 쓰는 간단한 대체 화면(모양 참고용)."""
    import html as H
    d = 읽기_json(배치파일, {}) or {}
    표 = {x.get("id"): x for x in 목록항목(목록읽기(p)) if isinstance(x, dict)}

    def 주소(ref):
        if isinstance(ref, dict):
            ref = ref.get("파일") or ref.get("경로") or ref.get("id") or ""
        ref = str(ref or "")
        항목 = 표.get(ref)
        경로 = (항목 or {}).get("미리보기") or (항목 or {}).get("썸네일") or ("" if 항목 else ref)
        return quote(f"/파일/{p.name}/{경로}") if 경로 else ""

    def 그림(ref, alt=""):
        u = 주소(ref)
        return f'<img src="{H.escape(u)}" alt="{H.escape(alt)}" loading="lazy">' if u else \
            f'<div class="없음">사진을 찾지 못함: {H.escape(str(ref))}</div>'

    def 글(t):
        return H.escape(str(t or "")).replace("\n", "<br>")

    조각 = []
    for b in d.get("블록") or []:
        k, 설명 = b.get("종류"), b.get("설명") or ""
        캡션 = f"<figcaption>{글(설명)}</figcaption>" if 설명 else ""
        if k == "본문":
            조각.append(f"<p>{글(b.get('글'))}</p>")
        elif k == "소제목":
            조각.append(f'<h2 class="소제목">{글(b.get("글"))}</h2>')
        elif k == "사진":
            조각.append(f"<figure>{''.join(그림(r, 설명) for r in (b.get('사진') or []))}{캡션}</figure>")
        elif k == "그룹사진":
            칸 = "슬라이드" if b.get("방식") == "슬라이드" else "콜라주"
            조각.append(f'<figure><div class="{칸}">{"".join(그림(r, 설명) for r in (b.get("사진") or []))}</div>{캡션}</figure>')
        elif k == "영상":
            u = 주소(b.get("영상"))
            속 = f'<img src="{H.escape(u)}" alt="영상">' if u else ""
            조각.append(f'<figure><div class="영상">{속}<span>▶ 영상</span></div>{캡션}</figure>')
        elif k == "지도":
            u = quote(f"/파일/{p.name}/{b.get('이미지') or ''}")
            조각.append(f'<figure><img src="{H.escape(u)}" alt="지도"><figcaption>© OpenStreetMap contributors</figcaption></figure>')
        elif k == "장소":
            조각.append('<div class="장소들">' + "".join(f"<div>📍 {글(x)}</div>" for x in (b.get("장소") or [])) + "</div>")
        elif k == "인용구":
            조각.append(f'<blockquote>{글(b.get("글"))}</blockquote>')
        elif k == "꿀팁":
            조각.append(f'<div class="꿀팁"><b>꿀팁</b> {글(b.get("글"))}</div>')
        elif k == "참고자료":
            조각.append('<div class="참고"><b>참고자료</b><ul>' + "".join(f"<li>{글(x)}</li>" for x in (b.get("목록") or [])) + "</ul></div>")
        elif k == "구분선":
            조각.append("<hr>")
        else:
            조각.append(f"<p>{글(b.get('글'))}</p>")
    태그 = " ".join(f"#{H.escape(str(t))}" for t in (d.get("태그") or []))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>미리보기</title>
<style>
body{{margin:0;background:#f2f3f5;font-family:'Nanum Gothic','Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#333}}
.띠{{background:#fff4c2;padding:8px 16px;font-size:13px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.띠 button{{font:inherit;padding:4px 12px;border:1px solid #c9b45a;background:#fff;border-radius:14px}}
.띠 button[aria-pressed=true]{{background:#333;color:#fff}}
.글틀{{background:#fff;max-width:700px;margin:24px auto;padding:32px 36px;font-size:15px;line-height:1.8}}
body.모바일 .글틀{{max-width:375px;padding:20px 16px}}
h1{{font-size:26px;font-weight:400}} .소제목{{font-size:20px}} figure{{margin:1.5em 0;text-align:center}}
img{{max-width:100%}} figcaption{{font-size:13px;color:#999}}
.콜라주{{display:grid;grid-template-columns:repeat(3,1fr);gap:3px}} .콜라주 img{{aspect-ratio:1;object-fit:cover;width:100%}}
.슬라이드{{display:flex;overflow-x:auto;gap:4px}} .슬라이드 img{{max-height:360px}}
blockquote{{text-align:center;font-size:18px;color:#555}} .꿀팁{{background:#fffbea;border:1px solid #f6e05e;padding:12px;border-radius:6px}}
.장소들,.참고{{border:1px solid #e5e5e5;padding:8px 12px}} .없음{{border:2px solid #f5a3a3;padding:16px;font-size:13px}}
.영상{{position:relative}} .영상 span{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-size:24px;text-shadow:0 0 8px #000}}
</style></head><body class="{'모바일' if 보기 == '모바일' else ''}">
<div class="띠" role="note"><strong>모양 참고용 — 실제 네이버 화면과 다를 수 있음</strong> (간단 미리보기: 공용 미리보기 도구를 찾지 못함)
<button type="button" id="pc" aria-pressed="{str(보기 != '모바일').lower()}">PC</button>
<button type="button" id="mo" aria-pressed="{str(보기 == '모바일').lower()}">모바일(375px)</button></div>
<article class="글틀"><div style="color:#03c75a;font-size:13px">{H.escape(str(d.get('카테고리') or ''))}</div>
<h1>{H.escape(str(d.get('제목') or ''))}</h1>{''.join(조각)}<p style="color:#555;font-size:13px">{태그}</p></article>
<script>
const pc=document.getElementById('pc'),mo=document.getElementById('mo');
function 보기(m){{document.body.classList.toggle('모바일',m);pc.setAttribute('aria-pressed',String(!m));mo.setAttribute('aria-pressed',String(m));}}
pc.onclick=()=>보기(false);mo.onclick=()=>보기(true);
</script></body></html>"""


# ---------------------------------------------------------------- 발행 연동(규약 8절) — 공용 PublishAPI 에 맡김

def _공용설정() -> dict:
    """공용 PublishAPI 의 settings 콜백: 설정.json 의 공통 키를 그대로 넘김(블로그ID·브라우저·자동예약발행·
    편사이간격분·예약최소여유분·중단판정분). 옛 키(최소간격초·중단판정초)도 같은 값으로 함께 넘김 —
    공용 모듈 v2(normalize_settings)는 새 키를 읽고 옛 키도 받으므로, 옛 모듈과 함께 써도 같은 값이 됨."""
    s = 사용자설정()
    return {**s, "최소간격초": s["편사이간격분"] * 60, "중단판정초": s["중단판정분"] * 60}


_발행상태표 = {"대기": "진행중", "채우는중": "진행중", "임시저장완료": "성공", "예약발행완료": "성공",
            "실패": "실패", "취소": "멈춤"}
_단계상태표 = {"진행": "진행중", "완료": "완료", "주의": "완료", "사람": "완료", "건너뜀": "건너뜀", "실패": "실패"}


def 발행사건(종류: str, 작업: dict):
    """공용 모듈이 작업을 만들거나 확장이 보고할 때마다 불림 → 로그·작업이력.json·상태.json 에 옮겨 적기(규약 2.6)."""
    try:
        여행ID = 작업.get("여행ID")
        작업ID = 작업.get("작업ID")
        실패 = 작업.get("실패") or {}
        줄 = 기록(f"[발행] {종류}: {작업ID} {작업.get('편ID') or ''} {작업.get('모드') or ''} 상태={작업.get('상태')}"
                f" 단계={작업.get('현재단계') or '-'}" + (f" 실패({실패.get('코드')}): {실패.get('메시지')}" if 실패 else ""),
                여행ID, "오류" if 작업.get("상태") == "실패" else "정보")
        if 여행ID:
            p = 여행폴더(여행ID)
            with 파일잠금(p / ".작업이력.lock", 기다림=5):
                이력 = 고칠_json(p / "작업이력.json", [])
                if not isinstance(이력, list):
                    이력 = []
                항목 = next((x for x in 이력 if isinstance(x, dict) and x.get("작업ID") == 작업ID), None)
                if 항목 is None:
                    항목 = {"작업ID": 작업ID}
                    이력.append(항목)
                단계 = []
                for s in 작업.get("단계") or []:
                    d = {"이름": s.get("이름"), "상태": _단계상태표.get(s.get("상태"), s.get("상태")), "시각": s.get("시각")}
                    if s.get("메시지"):
                        d["메시지"] = s["메시지"]
                    if s.get("주의"):
                        d["주의"] = s["주의"]
                    if s.get("상태") == "실패":
                        d["오류"] = f"{s.get('코드') or ''} {s.get('메시지') or ''}".strip()
                        d["로그"] = 줄
                    단계.append(d)
                항목.update({"종류": f"네이버 {작업.get('모드') or '임시저장'}", "출처": "발행", "편ID": 작업.get("편ID"),
                           "상태": _발행상태표.get(작업.get("상태"), "진행중"), "발행상태": 작업.get("상태"),
                           "단계": 단계, "재시도": "가능", "재시도횟수": 작업.get("재시도횟수") or 0,
                           "시작": 작업.get("만든시각"), "끝": 작업.get("끝") or ""})
                원자적_쓰기(p / "작업이력.json", 이력)
        # 위쪽 연결 표시·자동 멈춤 띠(상태.json 진행)
        진행상태 = {"진행중": "진행중", "성공": "완료", "실패": "실패", "멈춤": "멈춤"}[_발행상태표.get(작업.get("상태"), "진행중")]
        메시지 = {"대기": "네이버 화면에서 확장 대기 중", "채우는중": f"블로그 도우미가 채우는 중: {작업.get('현재단계') or ''}",
                "임시저장완료": "네이버 임시저장 끝", "예약발행완료": "네이버 예약 발행 끝", "취소": "발행 작업 취소",
                "실패": f"{실패.get('단계', '')} 단계에서 멈춤: {실패.get('메시지', '')}"}.get(작업.get("상태"), "")
        with 파일잠금(작업함(".상태.lock"), 기다림=5, 오래됨=15, 실패시오류=False):
            상태 = 고칠_json(작업함("상태.json"), {}, 깨지면_새로=True)
            if not isinstance(상태, dict):
                상태 = {}
            상태.setdefault("연결", {"마지막신호": None})
            진행 = [x for x in (상태.get("진행") or []) if isinstance(x, dict) and x.get("작업ID") != 작업ID]
            진행.append({"요청id": None, "작업ID": 작업ID, "단계": 작업.get("현재단계") or 작업.get("상태"),
                       "메시지": 메시지[:200], "퍼센트": None, "상태": 진행상태, "갱신": 지금()})
            상태["진행"] = 진행[-20:]
            상태.setdefault("알림", [])
            if 작업.get("상태") in ("임시저장완료", "예약발행완료"):
                키 = f"발행:{여행ID}/{작업.get('편ID')}"
                옛것 = [x for x in 상태["알림"] if isinstance(x, dict) and x.get("키") == 키]
                상태["알림"] = [x for x in 상태["알림"] if not (isinstance(x, dict) and x.get("키") == 키)]
                상태["알림"] = (상태["알림"] + [{"글": f"'{작업.get('제목') or 작업.get('편ID')}' {메시지} — 네이버에서 모바일 화면을 확인하고 발행해 주세요",
                                             "시각": 지금(), "키": 키}])[-20:]
                상태["지난알림"] = (list(상태.get("지난알림") or []) + [{**x, "해결": "같은 글의 새 알림"} for x in 옛것])[-30:]
            원자적_쓰기(작업함("상태.json"), 상태)
    except Exception as e:  # 기록 때문에 발행 작업이 멈추면 안 됨
        try:
            sys.stderr.write(f"발행사건 기록 실패: {e!r}\n")
        except Exception:
            pass


_공용확인 = {"결과": None}


def 공용가져오기모듈():
    """스튜디오 폴더(코드 쪽)의 공용가져오기.py 를 함수로 씀(원본 찾기·비교·복사가 한 곳에)."""
    import importlib.util
    파일 = 기본스튜디오 / "공용가져오기.py"
    if not 파일.is_file():
        return None
    spec = importlib.util.spec_from_file_location("스튜디오_공용가져오기", 파일)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def 공용비교() -> dict | None:
    """{"갱신필요","바뀐것","원본"} — 스튜디오 공용/ 이 원본(교재의 참고구현/공용)과 다르면 갱신필요."""
    try:
        g = 공용가져오기모듈()
        if g is None:
            return None
        원본, _ = g.원본찾기()
        if 원본 is None:
            결과 = {"갱신필요": False, "바뀐것": [], "원본": None}
        else:
            차이 = g.비교(원본)
            결과 = {"갱신필요": bool(차이["복사"]), "바뀐것": 차이["복사"], "원본": str(원본)}
    except Exception as e:  # 비교를 못 해도 서버는 계속
        기록(f"공용 파일 비교 실패: {e!r}", 수준="오류")
        결과 = None
    _공용확인["결과"] = 결과
    if 결과 and 결과["갱신필요"]:
        기록(f"공용 파일에 새 판이 있어요(바뀐 것: {', '.join(결과['바뀐것'])}) — 화면의 [공용 파일 갱신]으로 가져오세요")
    return 결과


def 공용갱신(_데이터: dict) -> dict:
    """화면 [공용 파일 갱신](사람). 교재의 공용 폴더에서 복사 → 서버를 끄지 않고 새 모듈을 씀."""
    g = 공용가져오기모듈()
    if g is None:
        raise 요청오류(404, "공용가져오기.py 가 없어요")
    원본, 찾아본곳 = g.원본찾기()
    if 원본 is None:
        raise 요청오류(404, "교재의 공용 폴더를 찾지 못했어요. 'python 공용가져오기.py --원본 <교재 폴더>/일상실습/01_네이버블로그/참고구현/공용' 을 직접 실행해 주세요.")
    with _쓰기잠금:
        결과 = g.복사(원본)
        발행연동.다시불러오기()
    기록(f"공용 파일 갱신(사람이 화면에서): 복사 {', '.join(결과['복사']) or '없음'} ← {원본}")
    공용비교()
    return {"성공": True, "복사": 결과["복사"], "원본": str(원본), "공용모듈": 발행연동.모듈경로() if 발행연동.모듈(서버설정.스튜디오) else None}


def 공용api():
    a = 발행연동.api(서버설정.스튜디오, 서버설정.포트, _공용설정, 발행사건)
    if a is None:
        raise 요청오류(503, "공용 발행 모듈(공용/발행서버.py v2)을 찾지 못했어요. 'python 공용가져오기.py'로 복사해 주세요.", 코드="준비중")
    return a


def _공용오류(e) -> 요청오류:
    """공용 모듈의 ApiError → 화면용 오류(코드 유지)."""
    return 요청오류(getattr(e, "status", 400), getattr(e, "message", str(e)), 코드=getattr(e, "code", "잘못된_요청"),
                  **(getattr(e, "extra", {}) or {}))


def _패키지찾기(여행ID: str, 편: str):
    a = 공용api()
    m = 발행연동.모듈(서버설정.스튜디오)
    pkg, err = m.find_package(a.source.packages(), {"여행": [여행ID], "편": [편]})
    if err:
        raise 요청오류(err[0], err[2], 코드=err[1])
    return pkg


def 글쓰기열기(데이터: dict | None = None) -> dict:
    """설정한 브라우저(chrome·edge·기본)로 네이버 글쓰기 화면 열기(규약 8절 2, 공용 open_in_browser)."""
    m = 발행연동.모듈(서버설정.스튜디오)
    s = 사용자설정()
    브라우저 = (데이터 or {}).get("브라우저") if (데이터 or {}).get("브라우저") in 브라우저들 else s.get("브라우저")
    if not s.get("블로그ID"):
        return {"열림": False, "이유": "블로그 아이디를 설정에 적으면 글쓰기 화면을 자동으로 열어요", "브라우저": 브라우저}
    if m is None or not hasattr(m, "write_url"):
        raise 요청오류(503, "공용 발행 모듈을 찾지 못했어요(공용가져오기.py)", 코드="준비중")
    주소 = m.write_url(s["블로그ID"])
    if not 서버설정.브라우저열기:
        return {"열림": False, "시험모드": True, "주소": 주소, "브라우저": 브라우저}
    try:
        무엇 = m.open_in_browser(주소, 발행연동.브라우저값.get(브라우저, "default"))
    except Exception as e:
        기록(f"글쓰기 화면을 열지 못함({브라우저}): {e!r}", 수준="오류")
        return {"열림": False, "이유": f"브라우저를 열지 못했어요: {e}", "주소": 주소, "브라우저": 브라우저}
    기록(f"네이버 글쓰기 화면 열기 → {브라우저} ({무엇})")
    return {"열림": True, "주소": 주소, "브라우저": 브라우저, "실행": 무엇}


def 발행작업만들기(데이터: dict) -> dict:
    """화면 ⑦ [네이버 임시저장]: 공용 jobs.create → 설정한 브라우저로 글쓰기 화면 열기(규약 8절 1·2)."""
    p = 여행폴더(데이터.get("여행ID") or 데이터.get("여행"))
    편 = 편확인(데이터.get("편ID") or 데이터.get("편"))
    모드 = 데이터.get("모드") or "임시저장"
    상태 = next((x for x in 편상태들(p) if x["편ID"] == 편), None)
    if not 상태 or not 상태["패키지있음"]:
        raise 요청오류(409, "발행 패키지가 아직 없어요. [발행 패키지 만들어 달라기]를 먼저 눌러 주세요.", 코드="패키지_없음")
    if 모드 == "예약발행":  # 화면에서 사람이 + 서명된 승인 + 승인한 글과 내용이 같은 패키지(수정 시각보다 엄격)
        _예약준비(p, 편, 데이터)
    elif 상태["패키지오래됨"]:
        raise 요청오류(409, "글을 고친 뒤 발행 패키지를 다시 만들지 않았어요. [발행 패키지 다시 만들어 달라기]를 눌러 주세요.", 코드="패키지_오래됨")
    # 같은 편을 이미 임시저장했거나 실패한 작업이 있으면, 사람이 확인(새로=true)했을 때만 새 작업(네이버에 같은 글이 둘 생기지 않게)
    with _발행작업잠금:
        return _발행작업만들기(p, 편, 모드, 데이터, 상태)


_발행작업잠금 = threading.Lock()


def _예약준비(p: Path, 편: str, 데이터: dict) -> None:
    """예약 발행 작업은 ① 화면에서 사람이 누른 요청 ② 서버가 서명한 승인(그 뒤 안 바뀜) ③ 승인한 글과 내용이 같은 패키지일 때만.
    ③의 패키지에 승인이 아직 없으면(승인 뒤 패키지를 만듦) 배치의 승인을 붙여 줌(내용이 같으니 같은 서명이 맞음)."""
    if not 데이터.get("_화면"):
        raise 요청오류(403, "예약 발행은 화면 ⑦에서 사람이 눌러야 해요(Claude·도우미는 예약 작업을 만들지 않음).", 코드="화면전용")
    배치파일 = 편파일들(p, "원고", "배치").get(편)
    배치 = 고칠_json(배치파일) if 배치파일 else None
    유효, 이유 = 승인확인(배치, 편) if isinstance(배치, dict) else (False, "글 없음")
    if not 유효:
        글 = {"승인 뒤 바뀜": "승인한 뒤 글이 바뀌었어요. 미리보기에서 다시 [이 글 승인]을 눌러 주세요.",
             "승인 안 함": "이 글은 아직 승인하지 않았어요. 글 화면에서 [이 글 승인]을 눌러 주세요.",
             "공용 모듈 없음": "공용 발행 모듈이 옛 판이라 승인을 확인할 수 없어요. 화면 위쪽 [공용 파일 갱신]을 눌러 주세요."}.get(
            이유, "이 글의 승인 표시가 화면에서 서명되지 않았어요(예전 승인이거나 다른 프로그램이 적음). 다시 [이 글 승인]을 눌러 주세요.")
        raise 요청오류(403, 글, 코드="예약불가", 이유=이유)
    패키지파일 = 편파일들(p, "발행", "패키지").get(편)
    패 = 고칠_json(패키지파일) if 패키지파일 else None
    if not isinstance(패, dict) or 글내용지문(패) != 글내용지문(배치):
        raise 요청오류(409, "발행 패키지의 내용이 승인한 글과 달라요. [발행 패키지 다시 만들어 달라기]를 눌러 주세요.", 코드="패키지_오래됨")
    # 패키지 승인(올라갈 파일까지 묶인 것)이 있어야 — 다시 만든 패키지는 글·파일이 같으면 예전 승인을 옮김
    if not 패키지승인옮기기(패키지파일, 편):
        _, 왜 = 승인확인(None, 편, 패키지파일, fresh=True)
        raise 요청오류(409, "발행 패키지(올라갈 사진·지도·영상 파일)를 아직 승인하지 않았거나 승인 뒤 파일이 바뀌었어요. "
                         "⑦의 [패키지 승인]을 눌러 주세요.", 코드="패키지승인필요", 이유=왜)
    예, 이유 = 공용확인("예약", [패키지파일], 데이터.get("예약시각"))
    if not 예:
        기록(f"예약 발행 작업 취소(데스크탑 확인: {이유 or '취소'}): {편}", p.name)
        raise 요청오류(403, f"컴퓨터의 확인 창에서 허락하지 않아 예약 작업을 만들지 않았어요({이유 or '취소를 누름'}).", 코드="데스크탑확인")


def 최근순(작업들: list[dict]) -> list[dict]:
    """만든 순서(같은 초에 만든 작업은 시작·끝 시각으로 가름) — 마지막이 가장 최근 작업."""
    return sorted(작업들, key=lambda j: (j.get("만든시각") or "", j.get("시작") or j.get("만든시각") or "", j.get("끝") or ""))


def _발행작업만들기(p: Path, 편: str, 모드: str, 데이터: dict, 상태: dict) -> dict:
    m0 = 발행연동.모듈(서버설정.스튜디오)
    앞작업 = 최근순([j for j in 공용api().jobs.list() if j.get("여행ID") == p.name and j.get("편ID") == 편])
    진행중 = any(j.get("상태") in getattr(m0, "ACTIVE", ("대기", "채우는중")) for j in 앞작업)
    if 앞작업 and not 데이터.get("새로") and not 진행중:  # 진행 중이면 공용 모듈이 '진행중작업'으로 알려 줌
        저장됨 = [j for j in 앞작업 if j.get("상태") in m0.FINISHED_OK]
        # 마지막으로 저장한 뒤에 실패하고 아직 [다시 시도]·취소하지 않은 작업(취소한 것은 사람이 정리한 것으로 봄)
        실패 = [j for j in 앞작업[앞작업.index(저장됨[-1]) + 1 if 저장됨 else 0:] if j.get("상태") == "실패"]
        if 실패:
            raise 요청오류(409, "실패한 작업이 있어요. 채우던 화면에서 이어 하려면 [다시 시도]를, 새 글로 처음부터 하려면 확인 뒤 새로 시작하세요."
                         + (" (이 글은 전에 임시저장한 적도 있어요.)" if 저장됨 else ""),
                         코드="실패한_작업있음", 작업ID=실패[-1].get("작업ID"))
        if 저장됨:
            j = 저장됨[-1]
            raise 요청오류(409, f"이 글은 이미 네이버에 임시저장했어요({(j.get('끝') or '')[:16].replace('T', ' ')}). "
                             "다시 하면 네이버 임시저장 글이 하나 더 생겨요(새 글로 저장됨).",
                         코드="이미_임시저장", 작업ID=j.get("작업ID"), 끝=j.get("끝"))
    pkg = _패키지찾기(p.name, 편)
    m = 발행연동.모듈(서버설정.스튜디오)
    try:  # human=True 는 화면 열쇠를 확인한 요청일 때만(공용 모듈: 예약발행은 사람 경로에서만)
        작업 = 공용api().jobs.create(pkg, 모드, 데이터.get("예약시각"), human=bool(데이터.get("_화면")))
    except m.ApiError as e:
        raise _공용오류(e)
    return {"성공": True, "작업": m.job_summary(작업), "브라우저": 글쓰기열기()}


def 발행작업재시도(데이터: dict) -> dict:
    작업ID = 데이터.get("작업ID")
    if not isinstance(작업ID, str) or not 작업ID:
        raise 요청오류(400, "다시 할 작업ID를 알려 주세요")
    m = 발행연동.모듈(서버설정.스튜디오)
    처음부터 = bool(데이터.get("처음부터"))
    앞 = 공용api().jobs.get(작업ID)
    if 앞 and 앞.get("모드") == "예약발행" and not 데이터.get("_화면"):
        raise 요청오류(403, "예약 발행 작업은 화면 ⑦·⑨에서 사람이 [다시 시도]를 눌러야 해요.", 코드="화면전용")
    try:  # 처음부터 = '준비' 단계부터, 아니면 실패한 단계부터(공용 retry)
        작업 = 공용api().jobs.retry(작업ID, "준비" if 처음부터 else None)
    except m.ApiError as e:
        raise _공용오류(e)
    if 처음부터 or (작업.get("시작단계") or "준비") == "준비":  # 처음부터(아직 채운 것 없음 포함)는 새 빈 글쓰기 화면에서
        return {"성공": True, "작업": 작업, "브라우저": 글쓰기열기()}
    # 실패한 단계부터는 '채우던 그 화면'에서 이어 해야 함. 새 글쓰기 화면을 열면 빈 화면의 도우미가 이 작업을 먼저 받아
    # '앞단계없음'으로 실패시킴(통합 리허설 2026-10-07 Edge 실측) → 열지 않고 패널 [작업 확인]을 안내
    return {"성공": True, "작업": 작업, "브라우저": {
        "열림": False, "이어하기": True,
        "이유": "채우던 네이버 글쓰기 화면의 블로그 도우미 패널에서 [작업 확인]을 눌러 주세요(그 화면을 닫았다면 [처음부터])."}}


def _패키지실패(p: Path, 편: str) -> dict | None:
    """그 편의 마지막 패키지 만들기(발행패키지·업로드사본)가 실패했고 그 뒤 패키지가 새로 생기지 않았으면 그 내용.
    업로드 사본 검사(위치·기기 정보, 모션 포토 꼬리·MPF 보조 그림)에 걸린 것이면 사본문제=True."""
    이력 = 읽기_json(p / "작업이력.json", []) or []
    후보 = [x for x in 이력 if isinstance(x, dict) and x.get("편ID") == 편
            and x.get("종류") in ("발행패키지", "업로드사본", "임시저장")]
    if not 후보:
        return None
    x = max(후보, key=lambda x: x.get("시작") or "")
    if x.get("상태") not in ("실패", "멈춤"):
        return None
    패 = 편파일들(p, "발행", "패키지").get(편)
    끝 = 시각읽기(x.get("끝") or x.get("시작"))
    if 패 and 끝 and (수정시각(패) or 0) > 끝.timestamp():
        return None
    단계 = next((s for s in x.get("단계") or [] if s.get("상태") == "실패"), {}) or {}
    글 = f"{단계.get('오류') or ''} {단계.get('메시지') or ''}"
    return {"작업ID": x.get("작업ID"), "단계": 단계.get("이름"), "오류": (단계.get("오류") or "")[:300],
            "로그": 단계.get("로그"),
            "사본문제": 단계.get("이름") == "업로드 사본" or any(k in 글 for k in ("메타", "MPF", "꼬리", "GPS", "기기"))}


def 패키지승인상태(p: Path, 편: str) -> str:
    """'승인됨' | '필요'(글은 승인됨, 패키지는 아직·파일 바뀜) | '글미승인' | '다른글'(패키지가 글과 다름)."""
    배치파일, 패키지 = 편파일들(p, "원고", "배치").get(편), 편파일들(p, "발행", "패키지").get(편)
    배치 = 고칠_json(배치파일) if 배치파일 else None
    if not 승인확인(배치, 편)[0]:
        return "글미승인"
    패 = 고칠_json(패키지) if 패키지 else None
    if not isinstance(패, dict) or 글내용지문(패) != 글내용지문(배치):
        return "다른글"
    return "승인됨" if 패키지승인옮기기(패키지, 편) else "필요"


def 발행상태(여행ID, 편ID) -> dict:
    """화면 ⑦용 한 번에: 패키지 묶음·경고(공용 build_bundles) + 이 편의 작업 + 확장 연결 + 설정."""
    p = 여행폴더(여행ID)
    편 = 편확인(편ID)
    결과 = {"공용모듈": 발행연동.모듈경로(), "설정": 사용자설정(), "예약경고": 예약경고, "패키지": {"있음": False},
          "작업": [], "최근작업": None, "확장": None}
    a = 공용api()
    m = 발행연동.모듈(서버설정.스튜디오)
    상태 = next((x for x in 편상태들(p) if x["편ID"] == 편), None) or {}
    if 상태.get("패키지있음"):
        try:
            pkg = _패키지찾기(p.name, 편)
            응답, _ = m.build_bundles(pkg)
            결과["패키지"] = {"있음": True, "오래됨": 상태.get("패키지오래됨"), "키": pkg.key,
                          "승인": m.approval_state(pkg), "공개": pkg.data.get("공개"),
                          "패키지승인": 패키지승인상태(p, 편),
                          "묶음수": 응답["묶음수"], "사진수": 응답["사진수"], "합계크기": 응답["합계크기"],
                          "건너뜀": 응답["건너뜀"], "경고": 응답["경고"] + [w for b in 응답["묶음"] for w in b["경고"]],
                          "묶음": [{k: b[k] for k in ("번호", "블록", "종류", "방식", "장수", "합계크기", "설명", "앞소제목")}
                                 for b in 응답["묶음"]]}
            # 동영상: 공용 모듈이 묶음에 넣으면 블로그 도우미가 올림(자동), 건너뛰면 사람이 '동영상' 버튼으로
            결과["패키지"]["블록종류"] = [b.get("종류") if isinstance(b, dict) else None for b in pkg.data.get("블록") or []]
            결과["패키지"]["AI활용표시"] = pkg.data.get("AI활용표시")
            결과["패키지"]["영상수"] = 응답.get("영상수", 0)
            결과["패키지"]["영상"] = (
                [{"블록": b["블록"], "자동": True, "개수": b["장수"], "합계크기": b["합계크기"]}
                 for b in 응답["묶음"] if b["종류"] == "영상"]
                + [{"블록": x["블록"], "자동": False, "사유": x.get("사유")} for x in 응답["건너뜀"] if x.get("종류") == "영상"])
        except 요청오류 as e:
            결과["패키지"] = {"있음": True, "오류": e.메시지}
        except (ValueError, OSError) as e:
            결과["패키지"] = {"있음": True, "오류": f"패키지를 읽지 못했어요: {e}"}
    모든작업 = a.jobs.list()
    작업들 = 최근순([j for j in 모든작업 if j.get("여행ID") == p.name and j.get("편ID") == 편])
    결과["작업"] = 작업들[-10:]
    cfg = a.settings()  # 공용 모듈이 맞춘 설정(편사이간격분 → 최소간격초) — 확장에게 작업을 내줄 때와 같은 값
    간격초 = int(cfg.get("최소간격초") or round(float(cfg.get("편사이간격분", 10)) * 60))
    끝들 = [m.parse_time(j.get("끝")) for j in 모든작업 if j.get("상태") in m.FINISHED_OK and j.get("끝")]
    끝들 = [t for t in 끝들 if t]
    결과["편사이간격분"] = cfg.get("편사이간격분", 간격초 / 60)
    결과["다음가능"] = None
    if 끝들:
        가능 = max(끝들) + timedelta(seconds=간격초)
        if 가능 > datetime.now().astimezone():
            결과["다음가능"] = 가능.isoformat(timespec="seconds")
    결과["패키지실패"] = _패키지실패(p, 편)
    if 작업들:
        결과["최근작업"] = a.jobs.get(작업들[-1]["작업ID"])
        if 결과["최근작업"]:
            결과["최근작업"].pop("기록", None)
    결과["확장"] = a.pairing.connections()
    return 결과


# ---------------------------------------------------------------- HTTP

class 처리기(BaseHTTPRequestHandler):
    server_version = "TravelStudio/2"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, 형식, *인자):  # 2초마다 오는 요청은 기록하지 않음
        if getattr(self, "_조용히", False):
            return
        try:
            sys.stderr.write(f"[{datetime.now():%H:%M:%S}] {self.address_string()} {형식 % 인자}\n")
        except Exception:
            pass

    def do_GET(self):
        self._처리("GET")

    def do_HEAD(self):
        self._처리("HEAD")

    def do_POST(self):
        self._처리("POST")

    def do_OPTIONS(self):  # 확장의 사전 요청은 공용 PublishAPI 주소에서만(그 밖은 거절)
        self._처리("OPTIONS")

    # ---- 보안(스튜디오 화면 주소) — /api/발행/*·/api/확장연결* 은 공용 PublishAPI 가 같은 규칙 + 토큰으로 확인
    def _보안확인(self, 경로: str = "", 방식: str = "GET"):
        host = (self.headers.get("Host") or "").lower()
        if host not in {f"127.0.0.1:{서버설정.포트}", f"localhost:{서버설정.포트}", f"[::1]:{서버설정.포트}"}:
            raise 요청오류(403, "이 서버는 http://localhost:8765 로만 열 수 있어요")  # DNS 리바인딩 막기
        출처 = self.headers.get("Origin")
        자기 = {f"http://127.0.0.1:{서버설정.포트}", f"http://localhost:{서버설정.포트}"}
        if 출처 and 출처 not in 자기:   # 확장도 화면 주소(/파일/ 등)는 못 씀 → CORS 헤더도 붙이지 않음
            raise 요청오류(403, "다른 사이트·확장에서 보낸 요청은 받지 않아요")
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        mode = (self.headers.get("Sec-Fetch-Mode") or "").lower()
        if site in ("cross-site", "same-site"):
            raise 요청오류(403, "다른 사이트에서 끌어오는 요청은 받지 않아요")
        # 'none' = 주소창·북마크·확장(서비스 워커)의 요청. 주소창으로 화면(/)을 여는 것만 받음(검수 M1)
        if site == "none" and not (mode == "navigate" and 경로 in ("/", "/index.html")):
            raise 요청오류(403, "주소창에서 여행 스튜디오 화면(http://localhost:8765/)을 연 뒤 써 주세요", 코드="주소창전용")
        # 브라우저의 요청(Sec-Fetch·Origin 이 있음)은 화면 열쇠가 있어야 데이터(/api/·/파일/)를 줌.
        # 브라우저 밖 프로그램(작업함.py·시험)은 Sec-Fetch 머리가 없음 → 읽기는 지금처럼, 사람 동작(POST)은 _POST 에서 막음
        브라우저 = bool(출처 or site or mode or self.headers.get("Sec-Fetch-Dest"))
        self._화면키맞음 = self._화면키확인(방식)
        self._브라우저 = 브라우저
        if 브라우저 and 경로.startswith(("/api/", "/파일/")) and not (self._화면키맞음 or self._파일키확인(방식, 경로)):
            raise 요청오류(403, "화면 열쇠가 맞지 않아요(서버가 다시 켜졌을 수 있어요). 화면을 새로 고쳐 주세요.", 코드="화면키")

    def _화면키확인(self, 방식: str) -> bool:
        """머리 X-Studio-Key(화면키) — API 읽기·쓰기와 '사람 경로'(human) 판단은 이것만."""
        머리 = (self.headers.get("X-Studio-Key") or "").encode("utf-8")
        return bool(머리) and hmac.compare_digest(머리, 서버설정.화면키.encode("utf-8"))

    def _파일키확인(self, 방식: str, 경로: str) -> bool:
        """쿠키 열쇠(파일키) — GET·HEAD 로 /파일/·/api/미리보기 를 읽을 때만(그림·영상·미리보기 틀은 머리를 못 붙임)."""
        if 방식 not in ("GET", "HEAD") or not (경로.startswith("/파일/") or 경로 == "/api/미리보기") or not self.headers.get("Cookie"):
            return False
        try:
            c = SimpleCookie(self.headers.get("Cookie"))
        except CookieError:
            return False
        값 = c.get(화면키쿠키)
        return bool(값) and hmac.compare_digest(값.value.encode("utf-8"), 서버설정.파일키.encode("utf-8"))

    def _길이(self) -> int:
        """Content-Length(없으면 0). 숫자가 아니거나 음수면 400 — 음수면 rfile.read 가 연결이 끊길 때까지 기다림(검수 L2)."""
        글 = (self.headers.get("Content-Length") or "").strip()
        if not 글:
            return 0
        if not 글.isdigit():
            raise 요청오류(400, "Content-Length 가 올바르지 않아요")
        return int(글)

    def _공용으로(self, 방식: str):
        """공용 PublishAPI 에 요청을 그대로 넘기고 응답(상태·헤더·몸)을 그대로 돌려줌(발행API.md 10절)."""
        a = 공용api()
        길이 = self._길이()
        if 길이 > 1_000_000:
            raise 요청오류(413, "보낸 내용이 너무 커요", 코드="너무큼")
        몸 = self.rfile.read(길이) if 길이 else b""
        # human: 화면 열쇠(X-Studio-Key 머리)를 확인한 요청만 '사람 경로'(공용 모듈이 예약발행 작업 만들기에만 씀)
        r = a.handle("GET" if 방식 == "HEAD" else 방식, self.path, self.headers, 몸, human=self._화면키확인("POST"))
        self.send_response(r.status)
        for k, v in r.headers:
            self.send_header(k, v)
        self.end_headers()
        if 방식 == "HEAD":
            return
        if not hasattr(r, "write_to"):  # 옛 공용 모듈(몸이 늘 r.body)
            self.wfile.write(r.body)
            return
        try:  # 큰 동영상(16MB 초과)·Range 응답은 r.body 가 비어 있고 파일 구간을 1MB씩 보냄(발행API.md 4.2·10절)
            r.write_to(self.wfile)
        except (ConnectionError, TimeoutError):  # 확장이 받다가 끊음(취소·다시 받기) — 응답 머리는 이미 보냈으니 연결만 닫음
            self.close_connection = True

    def _처리(self, 방식: str):
        self._조용히 = False
        경로 = ""
        try:
            주소 = urlsplit(self.path)
            경로 = unquote(주소.path)
            발행연동.모듈(서버설정.스튜디오)
            if 발행연동.처리할주소(self.path):
                return self._공용으로(방식)
            if 경로.startswith(("/api/발행/", "/api/확장연결")):
                raise 요청오류(503, "공용 발행 모듈(공용/발행서버.py v2)을 찾지 못했어요. 'python 공용가져오기.py'로 복사해 주세요.", 코드="준비중")
            self._보안확인(경로, 방식)
            if 방식 == "OPTIONS":
                raise 요청오류(403, "사전 요청은 /api/발행/ 주소에서만 받아요")
            질의 = {k: v[0] for k, v in parse_qs(주소.query, keep_blank_values=True).items()}
            if 방식 == "POST":
                return self._POST(경로)
            return self._GET(경로, 질의, 방식 == "HEAD")
        except 요청오류 as e:
            self._json({"오류": e.메시지, **e.덧붙임}, e.상태)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            traceback.print_exc()
            기록(f"서버 오류({방식} {경로}): {e!r}", 수준="오류")
            try:
                self._json({"오류": f"서버 안에서 문제가 생겼어요: {e}", "코드": "서버_오류"}, 500)
            except Exception:
                pass

    def _GET(self, 경로: str, 질의: dict, 머리만: bool):
        if 경로 in ("/", "/index.html"):
            return self._화면(머리만)
        if 경로 == "/favicon.ico":
            return self._파일(기본스튜디오 / "아이콘" / "studio.ico", 머리만)
        if 경로.startswith("/아이콘/"):
            return self._안전한파일(기본스튜디오 / "아이콘", 경로[len("/아이콘/"):], 머리만)
        if 경로.startswith("/파일/"):
            여행ID, _, 안경로 = 경로[len("/파일/"):].partition("/")
            return self._안전한파일(여행폴더(여행ID), 안경로, 머리만, 데이터=True)
        if 경로.startswith("/api/"):
            api = 경로[len("/api/"):]
            if api in ("상태", "질문"):
                self._조용히 = True
            응답 = {
                "여행": lambda: 여행목록(),
                "목록": lambda: 목록주기(질의.get("여행")),
                "장소": lambda: 장소주기(질의.get("여행")),
                "상태": lambda: 상태주기(질의.get("여행") or None),
                "질문": lambda: 질문주기(질의.get("여행") or None),
                "꿀팁노트": lambda: 꿀팁노트(),
                "이력": lambda: 이력주기(질의.get("여행")),
                "로그": lambda: 로그보기(질의.get("날짜"), 질의.get("줄")),
                "설정": lambda: {"설정": 사용자설정(), "경고": 예약경고, "브라우저들": list(브라우저들)},
                "발행상태": lambda: 발행상태(질의.get("여행"), 질의.get("편")),
            }.get(api)
            if 응답:
                return self._json(응답())
            if api == "미리보기":
                p = 여행폴더(질의.get("여행"))
                return self._글(미리보기(p.name, 편값(질의), 질의.get("보기") or "pc"))
            raise 요청오류(404, "그런 주소는 없어요")
        return self._안전한파일(화면폴더, 경로.lstrip("/"), 머리만)  # 화면 파일(app.js, style.css …)

    def _POST(self, 경로: str):
        if 경로 not in 도우미주소 and not self._화면키맞음:  # 승인·설정·결정·답변 … 은 사람이 화면에서만
            raise 요청오류(403, "이 동작은 여행 스튜디오 화면에서 사람이 눌러야 해요", 코드="화면전용")
        데이터 = self._본문()
        데이터["_화면"] = bool(self._화면키맞음)  # 보낸 쪽이 적은 값은 덮어씀
        처리 = {
            "/api/여행": 새여행, "/api/결정": 결정바꾸기, "/api/답변": 답변저장, "/api/요청": 요청만들기,
            "/api/승인": 승인바꾸기, "/api/구성안선택": 구성안선택, "/api/설정": 설정바꾸기,
            "/api/claude연결": lambda _d: claude연결(),
            "/api/글쓰기열기": 글쓰기열기,
            "/api/발행작업": 발행작업만들기,           # 화면 [네이버 임시저장]: 공용 jobs.create + 브라우저 열기
            "/api/발행작업/다시": 발행작업재시도,      # 화면 [다시 시도]: 공용 jobs.retry + 브라우저 열기
            "/api/알림": 알림바꾸기,                  # 화면 알림 [지우기]·[모두 지우기] → 지난 알림
            "/api/AI활용표시": AI표시바꾸기,          # 화면 ⑥ 'AI 활용 설정' 체크박스
            "/api/공용갱신": 공용갱신,                # 화면 위쪽 [공용 파일 갱신](사람) — 검수 L13
            "/api/폴더열기": 폴더열기,                # 화면 ⑧ [음악 폴더 열기]
            "/api/패키지승인": 패키지승인,            # 화면 ⑦ [패키지 승인](글 승인 뒤 만든 패키지)
        }.get(경로)
        if not 처리:
            raise 요청오류(404, "그런 주소는 없어요")
        return self._json(처리(데이터))

    def _본문(self) -> dict:
        길이 = self._길이()
        if 길이 > 1_000_000:
            raise 요청오류(413, "보낸 내용이 너무 커요")
        종류 = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if 종류 != "application/json":  # 다른 사이트의 몰래 보내기(form) 막기
            raise 요청오류(415, "JSON 으로 보내 주세요")
        원문 = self.rfile.read(길이) if 길이 else b""
        try:
            데이터 = json.loads(원문.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            raise 요청오류(400, "JSON 형식이 아니에요")
        if not isinstance(데이터, dict):
            raise 요청오류(400, "{…} 모양으로 보내 주세요")
        return 데이터

    def _보안헤더(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, 데이터, 코드=200):
        몸 = json.dumps(데이터, ensure_ascii=False).encode("utf-8")
        self.send_response(코드)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(몸)))
        self.send_header("Cache-Control", "no-store")
        self._보안헤더()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(몸)

    def _글(self, 글: str):
        몸 = 글.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(몸)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", 미리보기CSP)
        self._보안헤더()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(몸)

    def _화면(self, 머리만: bool):
        """index.html 에 화면 열쇠를 심어 줌(메타). 쿠키에는 다른 값(파일키, 읽기 전용). 캐시하지 않음.
        브라우저 요청이면 문서로 열 때(Sec-Fetch-Dest: document)만 열쇠를 심음 — fetch 로 / 를 읽어 열쇠를 얻지 못하게."""
        글 = (화면폴더 / "index.html").read_text(encoding="utf-8")
        문서 = (self.headers.get("Sec-Fetch-Dest") or "document").lower() == "document"
        if 문서:
            글 = 글.replace('<meta name="studio-key" content="">', f'<meta name="studio-key" content="{서버설정.화면키}">', 1)
        몸 = 글.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(몸)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", 화면CSP)
        if 문서:
            self.send_header("Set-Cookie", f"{화면키쿠키}={서버설정.파일키}; Path=/; HttpOnly; SameSite=Strict")
        self._보안헤더()
        self.end_headers()
        if not 머리만:
            self.wfile.write(몸)

    def _안전한파일(self, 기준: Path, 안경로: str, 머리만: bool, 데이터: bool = False):
        """기준 폴더 밖으로 나가는 경로(.., 절대경로, 드라이브 문자)는 거절."""
        if not 안경로 or "\x00" in 안경로:
            raise 요청오류(404, "파일 이름이 없어요")
        조각 = re.split(r"[\\/]+", 안경로)
        if any(c in ("..", ".") or ":" in c for c in 조각) or 안경로.startswith(("/", "\\")):
            raise 요청오류(403, "그 경로는 열 수 없어요")
        대상 = (기준 / Path(*[c for c in 조각 if c])).resolve()
        if not 안쪽인가(대상, 기준):
            raise 요청오류(403, "그 경로는 열 수 없어요")
        return self._파일(대상, 머리만, 내려받기=데이터 and 대상.suffix.lower() not in 바로보기형식)

    def _파일(self, 대상: Path, 머리만: bool, 내려받기: bool = False):
        if not 대상.is_file():
            raise 요청오류(404, "파일을 찾지 못했어요")
        st = 대상.stat()
        크기 = st.st_size
        종류 = "application/octet-stream" if 내려받기 else 파일종류.get(대상.suffix.lower(), "application/octet-stream")
        고친시각 = email.utils.formatdate(st.st_mtime, usegmt=True)
        범위 = self.headers.get("Range")
        if not 범위 and self.headers.get("If-Modified-Since") == 고친시각:
            self.send_response(304)
            self.send_header("Last-Modified", 고친시각)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        시작, 끝, 코드 = 0, 크기 - 1, 200
        if 범위:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", 범위.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    시작 = int(m.group(1))
                    끝 = min(int(m.group(2)), 크기 - 1) if m.group(2) else 크기 - 1
                else:
                    시작 = max(0, 크기 - int(m.group(2)))
                if 시작 > 끝 or 시작 >= 크기:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{크기}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                코드 = 206
        self.send_response(코드)
        self.send_header("Content-Type", 종류)
        self.send_header("Content-Length", str(끝 - 시작 + 1 if 크기 else 0))
        self.send_header("Last-Modified", 고친시각)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if 내려받기:  # html·svg·js 같은 것은 화면 출처로 실행되지 않게(검수 L3)
            self.send_header("Content-Disposition", "attachment")
            self.send_header("Content-Security-Policy", "sandbox")
        elif 대상.suffix.lower() == ".html":
            self.send_header("Content-Security-Policy", 화면CSP)
        self._보안헤더()
        if 코드 == 206:
            self.send_header("Content-Range", f"bytes {시작}-{끝}/{크기}")
        self.end_headers()
        if 머리만 or not 크기:
            return
        with open(대상, "rb") as f:
            f.seek(시작)
            남음 = 끝 - 시작 + 1
            while 남음 > 0:
                조각 = f.read(min(256 * 1024, 남음))
                if not 조각:
                    break
                self.wfile.write(조각)
                남음 -= len(조각)


class 스튜디오서버(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # Windows 에서 True 면 같은 포트에 서버가 둘 뜰 수 있음

    def handle_error(self, request, client_address):
        # 브라우저가 새로 고침 등으로 연결을 먼저 끊은 것은 문제가 아니므로 기록하지 않음
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def 이미켜짐(포트: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{포트}{quote('/api/상태')}", timeout=2) as r:
            return "연결" in json.loads(r.read().decode("utf-8"))
    except Exception:
        return False


def main():
    if sys.stdout is None or sys.stderr is None:  # pythonw(콘솔 없음)로 실행됨 → 기록 파일로
        기록파일 = 서버폴더 / "서버기록.log"
        넘침 = 기록파일.is_file() and 기록파일.stat().st_size > 1_000_000
        기록통 = open(기록파일, "w" if 넘침 else "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or 기록통
        sys.stderr = sys.stderr or 기록통
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="여행 스튜디오 서버")
    ap.add_argument("--포트", type=int, default=8765)
    ap.add_argument("--폴더", help="여행스튜디오 폴더(기본: 이 파일의 위 폴더)")
    ap.add_argument("--딥링크끄기", action="store_true", help="시험용: Claude 앱을 실제로 열지 않음")
    ap.add_argument("--브라우저끄기", action="store_true", help="시험용: 브라우저(Chrome 또는 Edge)를 실제로 열지 않음")
    ap.add_argument("--시험확인", choices=["예", "아니오"], help="시험용: 데스크탑 확인 창을 띄우지 않고 이 답으로")
    a = ap.parse_args()
    서버설정.화면키 = secrets.token_urlsafe(32)
    서버설정.파일키 = secrets.token_urlsafe(32)
    if a.시험확인:  # 확인 창을 자동으로 답하는 시험 옵션은 임시 폴더(시험용 --폴더)에서만 — 재검수 N3
        import tempfile
        임시 = Path(tempfile.gettempdir()).resolve()
        폴더 = Path(a.폴더).resolve() if a.폴더 else None
        if not 폴더 or 임시 not in 폴더.parents:  # 실제 스튜디오(바탕화면·실습공간)는 임시 폴더 안에 있지 않음
            print("--시험확인 은 임시 폴더 안의 시험용 --폴더 와 함께만 쓸 수 있어요(실제 스튜디오에서는 확인 창이 꼭 떠야 함).")
            return 2
    서버설정.시험확인 = a.시험확인
    서버설정.포트 = a.포트
    서버설정.스튜디오 = Path(a.폴더).resolve() if a.폴더 else 기본스튜디오
    서버설정.딥링크열기 = not a.딥링크끄기
    서버설정.브라우저열기 = not a.브라우저끄기
    폴더준비()
    try:
        서버 = 스튜디오서버(("127.0.0.1", 서버설정.포트), 처리기)
    except OSError:
        if 이미켜짐(서버설정.포트):
            print(f"이미 켜져 있어요: http://localhost:{서버설정.포트}")
            return 0
        print(f"포트 {서버설정.포트}을(를) 다른 프로그램이 쓰고 있어요(발행서버가 켜져 있나요?). 그 프로그램을 끄거나 --포트 로 바꿔 주세요.")
        return 1
    설정옮겨적기()
    공용비교()
    a = 발행연동.api(서버설정.스튜디오, 서버설정.포트, _공용설정, 발행사건)
    print(f"여행 스튜디오 서버: http://localhost:{서버설정.포트}  (폴더: {서버설정.스튜디오})", flush=True)
    print(f"공용 발행 모듈: {발행연동.모듈경로() or '없음 — python 공용가져오기.py 실행'}"
          f"{'' if a else ' (v2 PublishAPI 없음: /api/발행/* 닫힘)'}", flush=True)
    print("끄려면 이 창에서 Ctrl+C (스튜디오실행으로 켰으면 작업 관리자에서 pythonw 끄기)", flush=True)
    기록(f"서버 시작 (포트 {서버설정.포트})")
    try:
        서버.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        서버.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
