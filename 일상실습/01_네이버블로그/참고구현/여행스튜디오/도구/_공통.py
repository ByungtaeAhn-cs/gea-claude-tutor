# -*- coding: utf-8 -*-
"""_공통.py — 여행 스튜디오 사진 도구들이 함께 쓰는 도우미 (규약 0절·2절·2.6)

- 여행 폴더 찾기:  --여행 <여행ID>  (시험할 때는 --루트 <여행스튜디오 폴더 대신 쓸 곳>)
- 잠금 + 원자적 쓰기: 목록.json 은 .목록.lock(화면 서버와 같은 잠금), 쓰기 직전에 다시 읽어 합침
- '사용자결정'은 절대 덮어쓰지 않음(서버=화면만 바꿈)
- 로그/YYYY-MM-DD.log 기록, 작업이력.json 단계 기록, 마지막 줄 JSON 요약
표준 라이브러리만 씁니다(사진 꾸러미는 각 도구가 '필요()'로 확인하고 가져옴).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

도구폴더 = Path(__file__).resolve().parent
기본스튜디오 = 도구폴더.parent          # 여행스튜디오/
설치명령 = "python -m pip install pillow pillow-heif av imagehash mediapipe py-staticmaps tzdata"
지킬필드 = ("사용자결정",)             # 도구가 절대 바꾸지 않는 목록 필드
약한출처 = ("EXIF", "파일명", "파일수정시각")
강한출처 = ("EXIF+Offset", "영상UTC", "영상현지", "사용자")


# ───────────────────────────────────────────── 시각
def 지금() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def 시각읽기(글) -> datetime | None:
    """ISO 문자열 → datetime(시간대가 없으면 None 시간대 그대로). '+0900'·'Z' 도 받음."""
    if not isinstance(글, str) or not 글.strip():
        return None
    s = 글.strip().replace(" ", "T", 1)
    s = re.sub(r"Z$", "+00:00", s)
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # 소수점 7자리 이상은 자름
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def 시간대(정보: dict):
    """여행정보.시간대 '+09:00' 또는 'Asia/Seoul' → tzinfo."""
    값 = str((정보 or {}).get("시간대") or "+09:00").strip()
    m = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})", 값)
    if m:
        분 = int(m.group(2)) * 60 + int(m.group(3))
        return timezone(timedelta(minutes=분 if m.group(1) == "+" else -분))
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(값)
    except Exception as e:  # Windows 에 tzdata 가 없을 때 등
        raise 도구오류(f"여행 시간대 '{값}'을(를) 알 수 없어요({e}). '+09:00'처럼 적거나 tzdata 를 설치하세요.",
                     힌트="python -m pip install tzdata")


def 오프셋글(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def 하루경계(정보: dict) -> timedelta:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str((정보 or {}).get("하루경계") or "04:00"))
    return timedelta(hours=int(m.group(1)), minutes=int(m.group(2))) if m else timedelta(hours=4)


def 기준날짜(촬영시각: str | None, 정보: dict) -> date | None:
    t = 시각읽기(촬영시각)
    if t is None:
        return None
    return (t - 하루경계(정보)).date()


def 일차계산(촬영시각: str | None, 정보: dict) -> int | None:
    날 = 기준날짜(촬영시각, 정보)
    시작 = ((정보 or {}).get("기간") or {}).get("시작")
    if 날 is None or not 시작:
        return None
    try:
        n = (날 - date.fromisoformat(str(시작)[:10])).days + 1
    except ValueError:
        return None
    return n if n >= 1 else None


def 초글(초: float) -> str:
    """4020 → '1:07:00', -65 → '-0:01:05'"""
    부호 = "-" if 초 < 0 else ""
    초 = int(round(abs(초)))
    return f"{부호}{초 // 3600}:{초 % 3600 // 60:02d}:{초 % 60:02d}"


def 분초글(초: float) -> str:
    초 = int(round(초))
    return f"{초 // 60:02d}:{초 % 60:02d}" if 초 < 3600 else f"{초 // 3600}:{초 % 3600 // 60:02d}:{초 % 60:02d}"


# ───────────────────────────────────────────── 파일
class 도구오류(Exception):
    def __init__(self, 메시지: str, 힌트: str | None = None, 코드: int = 1, 자료: dict | None = None):
        super().__init__(메시지)
        self.메시지, self.힌트, self.코드, self.자료 = 메시지, 힌트, 코드, 자료 or {}


def 읽기_json(경로: Path, 기본=None):
    for 번 in range(20):
        try:
            with open(경로, encoding="utf-8-sig") as f:
                return json.load(f)
        except PermissionError:  # Windows: 서버가 같은 파일을 막 바꿔 끼우는 중 → 잠깐 뒤 다시(없는 파일로 보지 않음)
            time.sleep(0.05 * (번 + 1))
        except (OSError, ValueError):
            return 기본
    return 기본


def 원자적_쓰기(경로: Path, 데이터=None, 글: str | None = None):
    """임시 파일에 다 쓴 뒤 한 번에 바꿔 끼움 → 화면 서버가 반쯤 쓰인 파일을 읽지 않음."""
    경로 = Path(경로)
    경로.parent.mkdir(parents=True, exist_ok=True)
    if 글 is None:
        글 = json.dumps(데이터, ensure_ascii=False, indent=2)
    임시 = 경로.with_name(f".{경로.name}.{os.getpid()}.tmp")
    with open(임시, "w", encoding="utf-8", newline="\n") as f:
        f.write(글)
        f.flush()
        os.fsync(f.fileno())
    for 번 in range(40):
        try:
            os.replace(임시, 경로)
            return
        except PermissionError:  # Windows: 다른 프로그램(서버)이 잠깐 열고 있음
            time.sleep(0.05 * (번 + 1))
    try:
        임시.unlink()
    except OSError:
        pass
    raise 도구오류(f"{경로.name} 을(를) 쓰지 못했어요(다른 프로그램이 열고 있음). 잠시 뒤 다시 실행하세요.")


class 파일잠금:
    """여러 프로그램(화면 서버·작업함.py·도구)이 같은 파일을 동시에 고치지 않게 하는 잠금 파일.
    서버와 같은 규칙: O_EXCL 로 만들고, 30초 넘게 남은 잠금은 죽은 프로그램의 것으로 보고 치움."""

    def __init__(self, 경로: Path, 기다림: float = 30.0, 오래됨: float = 30.0, 이름: str = "도구"):
        self.경로, self.기다림, self.오래됨, self.이름 = Path(경로), 기다림, 오래됨, 이름

    def __enter__(self):
        끝 = time.monotonic() + self.기다림
        while True:
            try:
                fd = os.open(self.경로, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {self.이름}".encode("utf-8"))
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):  # Windows: 막 지워지는 중인 잠금 파일은 PermissionError
                try:
                    if time.time() - self.경로.stat().st_mtime > self.오래됨:
                        self.경로.unlink()
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass
                if time.monotonic() > 끝:
                    raise 도구오류(f"{self.경로.name} 잠금을 얻지 못했어요(화면에서 고르는 중일 수 있음). 잠시 뒤 다시 실행하세요.")
                time.sleep(0.05)

    def __exit__(self, *_):
        try:
            self.경로.unlink()
        except OSError:
            pass


def 목록항목(데이터) -> list:
    if isinstance(데이터, list):
        return 데이터
    if isinstance(데이터, dict):
        for 키 in ("항목", "목록", "사진", "items"):
            if isinstance(데이터.get(키), list):
                return 데이터[키]
    return []


def 정렬키(x: dict):
    return (str(x.get("촬영시각") or "9999"), str(x.get("id") or ""))


def 한글글꼴(굵게: bool = False) -> str | None:
    """Windows 맑은 고딕 / Mac Apple SD Gothic Neo / 리눅스 Noto CJK 순서로 찾기."""
    후보 = []
    if 굵게:
        후보 += ["C:/Windows/Fonts/malgunbd.ttf"]
    후보 += [
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    windir = os.environ.get("WINDIR")
    if windir:
        후보.insert(0, str(Path(windir) / "Fonts" / ("malgunbd.ttf" if 굵게 else "malgun.ttf")))
    for p in 후보:
        if Path(p).is_file():
            return p
    return None


def 필요(*이름들: str):
    """사진 꾸러미 가져오기. 없으면 친절한 설치 안내와 함께 멈춤.
    이름: 'PIL', 'pillow_heif', 'av', 'imagehash', 'mediapipe', 'staticmaps', 'numpy', 'cv2'"""
    pip이름 = {"PIL": "pillow", "pillow_heif": "pillow-heif", "av": "av", "imagehash": "imagehash",
              "mediapipe": "mediapipe", "staticmaps": "py-staticmaps", "numpy": "numpy",
              "cv2": "opencv-contrib-python(mediapipe 를 설치하면 함께 깔림)", "requests": "requests"}
    모듈들, 없음 = [], []
    for 이름 in 이름들:
        try:
            모듈들.append(importlib.import_module(이름))
        except ImportError:
            없음.append(pip이름.get(이름, 이름))
    if 없음:
        raise 도구오류(
            "사진 도구에 필요한 파이썬 꾸러미가 없어요: " + ", ".join(없음),
            힌트=(f"설치: {설치명령}\n(Mac은 python3 -m pip …, 가상환경을 쓰면 그 환경을 켠 뒤. "
                 "Python 3.12 이상 권장 — av 가 3.12 이상을 요구합니다. 인텔 Mac은 mediapipe 가 설치되지 않을 수 있어요.)"),
            코드=2, 자료={"설치필요": 없음, "설치명령": 설치명령})
    return 모듈들[0] if len(모듈들) == 1 else 모듈들


def ffmpeg경로(이름: str = "ffmpeg") -> str:
    p = shutil.which(이름)
    if not p:
        raise 도구오류(
            f"{이름} 프로그램을 찾지 못했어요(영상 만들기에 필요).",
            힌트=("Windows: winget install -e --id Gyan.FFmpeg  → 설치 후 Claude 앱(또는 터미널)을 새로 열기\n"
                 "Mac: brew install ffmpeg  (이 도구는 글자를 Pillow로 그리므로 ffmpeg-full 이 아니어도 됩니다)"),
            코드=2)
    return p


def 실행(명령: list[str], 시간제한: float | None = None, 작업폴더: Path | None = None) -> subprocess.CompletedProcess:
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(명령, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=시간제한, cwd=str(작업폴더) if 작업폴더 else None, **kw)


def 설정읽기(스튜디오: Path) -> dict:
    """선택: <여행스튜디오>/도구/도구설정.json (없으면 기본값). 화면 서버의 설정.json 과 따로 둠
    (서버는 설정.json 을 자기 항목만 남기고 다시 쓰므로 거기 두면 지워짐).
    예) {"지도_UserAgent": "OurChurchBlog-TravelStudio/1.0 (+https://example.org/contact)", "지도_연락처": "단체 대표 메일"}
    환경 변수 TRAVEL_STUDIO_USER_AGENT 가 있으면 그 값이 지도_UserAgent 보다 먼저."""
    d = 읽기_json(스튜디오 / "도구" / "도구설정.json", {}) or {}
    d = d if isinstance(d, dict) else {}
    if os.environ.get("TRAVEL_STUDIO_USER_AGENT"):
        d["지도_UserAgent"] = os.environ["TRAVEL_STUDIO_USER_AGENT"]
    return d


# ───────────────────────────────────────────── 숨길 장소(집·숙소) — 지도·영상·발행패키지가 같은 규칙을 씀(보안 검수 M4)
기본숨길장소 = ["숙소", "집"]


def 숨길이름들(정보: dict) -> list[str]:
    """여행정보.숨길장소. 비었거나 없으면 기본 ["숙소", "집"]."""
    v = (정보 or {}).get("숨길장소")
    return [str(s) for s in v if str(s).strip()] if isinstance(v, list) and v else list(기본숨길장소)


def 사람이공개함(p: dict) -> bool:
    """사람이 '공개해도 됨'을 고른 장소인가(지도.py --장소 L.. --공개)."""
    return bool(p.get("공개확인")) or (p.get("숨김출처") == "사용자" and p.get("숨김") is False)


def 장소숨김이유(p: dict, 숨길: list[str]) -> str | None:
    """None 이면 공개. 기본은 숨김 쪽(fail-closed): '비공개 추정'은 사람이 공개를 고르기 전까지 숨김."""
    if not isinstance(p, dict):
        return None
    if p.get("숨김"):
        return "숨김"
    if 사람이공개함(p):
        return None
    이름 = str(p.get("이름") or "")
    for k in 숨길:
        if k and k in 이름:
            return f"숨길장소 '{k}'"
    if p.get("숙소추정"):
        return "비공개 추정(" + ", ".join(p.get("비공개이유") or ["숙소·집일 수 있음"]) + ") — 사람이 공개를 고르기 전까지 뺌"
    return None


def 숨긴장소표(장소: dict, 정보: dict) -> dict[str, str]:
    """{장소ID: 숨기는 이유}"""
    숨길 = 숨길이름들(정보)
    return {pid: 이유 for pid, p in (장소 or {}).items() if (이유 := 장소숨김이유(p, 숨길))}


# ───────────────────────────────────────────── 도구 실행(로그·작업이력·요약)
_로그스레드잠금 = threading.Lock()
_이력스레드잠금 = threading.Lock()


class 도구실행:
    """도구 한 번 실행 = 작업이력의 작업 하나. 단계마다 산출물·오류를 기록합니다.
    작업 상태: 진행중 → 성공/실패 (화면은 재시도횟수>0 인 성공을 '재시도 완료'로 보여 줌). 단계 상태: 진행중/완료/실패"""

    def __init__(self, 이름: str, 인자: argparse.Namespace, 편ID: str | None = None, 여행필수: bool = True):
        self.이름 = 이름
        self.인자 = 인자
        self.시작시각 = time.monotonic()
        self.스튜디오 = Path(인자.루트).resolve() if getattr(인자, "루트", None) else 기본스튜디오
        self.여행ID = getattr(인자, "여행", None)
        self.편ID = 편ID
        self.작업ID = None
        self.단계들: list[dict] = []
        self._이어하기 = None
        if not self.여행ID:
            if 여행필수:
                raise 도구오류("--여행 <여행ID> 를 알려 주세요(여행 폴더 이름).")
            self.여행 = None
            return
        if re.search(r'[\\/:*?"<>|\x00-\x1f]', self.여행ID) or self.여행ID.startswith(".") or len(self.여행ID) > 100:
            raise 도구오류(f"여행ID가 올바르지 않아요: {self.여행ID}")
        self.여행 = self.스튜디오 / "여행" / self.여행ID
        if not self.여행.is_dir():
            있는것 = sorted(p.name for p in (self.스튜디오 / "여행").glob("*") if p.is_dir() and not p.name.startswith("."))
            raise 도구오류(f"'{self.여행ID}' 여행 폴더가 없어요: {self.여행}",
                         힌트=("있는 여행: " + ", ".join(있는것)) if 있는것 else "화면에서 [새 여행 만들기]를 먼저 하세요.")
        self._작업시작(getattr(인자, "작업ID", None))

    # ── 로그
    def 로그(self, 메시지: str, 수준: str = "정보") -> str:
        """로그/YYYY-MM-DD.log 에 한 줄(여러 줄이면 여러 줄) 쓰고 '로그/날짜.log#L번호'를 돌려줌."""
        폴더 = self.스튜디오 / "로그"
        폴더.mkdir(parents=True, exist_ok=True)
        파일 = 폴더 / f"{datetime.now():%Y-%m-%d}.log"
        # 화면 서버와 같은 모양: '날짜 시각 [수준] [누가] [여행ID] 내용' — 로그 보기 화면이 '[오류]' 줄을 표시함
        머리 = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{수준}] [{self.이름}]" + (f" [{self.여행ID}]" if self.여행ID else "")
        줄들 = [f"{머리} {l}" for l in str(메시지).splitlines() or [""]]
        번호 = 0
        with _로그스레드잠금:  # 같은 도구 안 여러 스레드(영상 장면 동시 작업)끼리 차례로
            try:
                with 파일잠금(폴더 / ".로그.lock", 기다림=30, 오래됨=60, 이름=self.이름):
                    try:
                        with open(파일, "rb") as f:
                            번호 = sum(1 for _ in f)
                    except OSError:
                        번호 = 0
                    with open(파일, "a", encoding="utf-8", newline="\n") as f:
                        f.write("\n".join(줄들) + "\n")
            except (도구오류, OSError):  # 로그를 못 써도 일은 계속 — 잠금 없이 쓰면 다른 프로그램과 덧써 글자가 깨지므로 화면(stderr)에만
                print(f"[{self.이름}] (로그 잠금을 얻지 못해 로그 파일에 못 씀) " + " / ".join(줄들), file=sys.stderr, flush=True)
        if 수준 != "정보" or getattr(self.인자, "자세히", False):
            print(f"[{self.이름}] {메시지}", file=sys.stderr, flush=True)
        return f"로그/{파일.name}#L{번호 + 1}"

    def 알림(self, 메시지: str):
        """사람(Claude)에게 보이는 진행 메시지: 화면(stderr) + 로그."""
        print(f"[{self.이름}] {메시지}", file=sys.stderr, flush=True)
        self.로그(메시지)

    # ── 작업이력(규약 2.6)
    def _이력파일(self) -> Path:
        return self.여행 / "작업이력.json"

    def _이력고치기(self, 고치기):
        with _이력스레드잠금, 파일잠금(self.여행 / ".작업이력.lock", 이름=self.이름):
            이력 = 읽기_json(self._이력파일(), [])
            if not isinstance(이력, list):
                이력 = []
            고치기(이력)
            원자적_쓰기(self._이력파일(), 이력[-300:])

    def _작업시작(self, 이어할ID: str | None):
        명령 = "python 도구/" + Path(sys.argv[0]).name + " " + " ".join(
            a if re.fullmatch(r"[\w가-힣:./=+-]+", a) else json.dumps(a, ensure_ascii=False) for a in sys.argv[1:])
        if 이어할ID:
            이전 = next((x for x in (읽기_json(self._이력파일(), []) or []) if isinstance(x, dict) and x.get("작업ID") == 이어할ID), None)
            if 이전 is None:
                raise 도구오류(f"작업이력에 '{이어할ID}' 작업이 없어요.")
            self.작업ID = 이어할ID
            self._이어하기 = 이전
            self.단계들 = [d for d in (이전.get("단계") or []) if d.get("상태") == "완료"]

            def 고치기(이력):
                for x in 이력:
                    if x.get("작업ID") == 이어할ID:
                        x.update({"상태": "진행중", "단계": self.단계들, "재시도횟수": int(x.get("재시도횟수") or 0) + 1,
                                  "다시시작": 지금(), "끝": None, "명령": 명령})
            self._이력고치기(고치기)
            self.로그(f"재시도 시작: {이어할ID} (완료된 단계 {len(self.단계들)}개는 산출물 재사용)")
            return
        n = datetime.now()
        기본 = f"t{n:%Y%m%d_%H%M}_{self.이름}" + (f"_{self.편ID}" if self.편ID else "")

        def 고치기(이력):
            있는 = {x.get("작업ID") for x in 이력 if isinstance(x, dict)}
            후보, k = 기본, 2
            while 후보 in 있는:
                후보, k = f"{기본}_{k}", k + 1
            self.작업ID = 후보
            이력.append({"작업ID": 후보, "종류": self.이름, "편ID": self.편ID, "상태": "진행중", "단계": [],
                       "재시도": "가능", "시작": 지금(), "끝": None, "명령": 명령})
        self._이력고치기(고치기)
        self.로그(f"시작: {명령} (작업ID {self.작업ID})")

    def 이미완료(self, 단계이름: str) -> dict | None:
        """재시도(--작업ID)일 때, 앞서 완료된 단계이고 산출물이 남아 있으면 그 기록을 돌려줌."""
        for d in self.단계들:
            if d.get("이름") == 단계이름 and d.get("상태") == "완료":
                산출물 = d.get("산출물")
                if not 산출물 or all((self.여행 / s).exists() for s in ([산출물] if isinstance(산출물, str) else 산출물)):
                    return d
        return None

    def _단계저장(self, 기록: dict):
        self.단계들 = [d for d in self.단계들 if d.get("이름") != 기록["이름"]] + [기록]

        def 고치기(이력):
            for x in 이력:
                if x.get("작업ID") == self.작업ID:
                    x["단계"] = self.단계들
        if self.여행 is not None:
            self._이력고치기(고치기)

    @contextmanager
    def 단계(self, 이름: str):
        """with 실행.단계("미리보기 만들기") as 기록: ...; 기록["산출물"] = "작업/미리보기/" """
        기록 = {"이름": 이름, "상태": "진행중", "시작": 지금()}
        self.로그(f"단계 시작: {이름}")
        try:
            yield 기록
        except BaseException as e:
            기록["상태"] = "실패"
            기록["끝"] = 지금()
            메시지 = e.메시지 if isinstance(e, 도구오류) else f"{type(e).__name__}: {e}"
            기록["오류"] = 메시지
            기록["로그"] = self.로그(f"단계 실패: {이름} — {메시지}\n{traceback.format_exc()}", "오류")
            self._단계저장(기록)
            raise
        기록["상태"] = "완료"
        기록["끝"] = 지금()
        self._단계저장(기록)
        self.로그(f"단계 완료: {이름}" + (f" → {기록['산출물']}" if 기록.get("산출물") else ""))

    def 끝(self, 요약: dict, 성공: bool = True, 재시도: str = "가능"):
        걸린 = round(time.monotonic() - self.시작시각, 1)
        결과 = {"성공": 성공, "도구": self.이름, "여행ID": self.여행ID, "작업ID": self.작업ID, "걸린초": 걸린, **요약}
        if self.여행 is not None and self.작업ID:
            def 고치기(이력):
                for x in 이력:
                    if x.get("작업ID") == self.작업ID:
                        x.update({"상태": "성공" if 성공 else "실패", "끝": 지금(), "단계": self.단계들,
                                  "재시도": 재시도, "걸린초": 걸린})
            try:
                self._이력고치기(고치기)
            except 도구오류:
                pass
        self.로그(("완료" if 성공 else "실패") + f" ({걸린}초): " + json.dumps(
            {k: v for k, v in 결과.items() if not isinstance(v, (list, dict))}, ensure_ascii=False))
        print(json.dumps(결과, ensure_ascii=False), flush=True)
        return 결과

    # ── 데이터 파일
    def 정보(self) -> dict:
        d = 읽기_json(self.여행 / "여행정보.json")
        if not isinstance(d, dict):
            raise 도구오류("여행정보.json 을 읽지 못했어요.", 힌트="화면에서 만든 여행 폴더인지 확인하세요.")
        return d

    def 정보고치기(self, 고치기) -> dict:
        with 파일잠금(self.여행 / ".여행정보.lock", 이름=self.이름):
            d = 읽기_json(self.여행 / "여행정보.json")
            if not isinstance(d, dict):
                raise 도구오류("여행정보.json 을 읽지 못했어요.")
            고치기(d)
            원자적_쓰기(self.여행 / "여행정보.json", d)
            return d

    def 목록(self, 있어야: bool = True) -> list[dict]:
        d = 읽기_json(self.여행 / "목록.json")
        if d is None:
            if 있어야:
                raise 도구오류("목록.json 이 아직 없어요.", 힌트=f"먼저 python 도구/목록만들기.py --여행 {self.여행ID}")
            return []
        return [x for x in 목록항목(d) if isinstance(x, dict)]

    def 목록합치기(self, 고칠것: dict[str, dict] | None = None, 새항목: list[dict] | None = None,
                 정렬: bool = True) -> dict:
        """쓰기 직전에 잠그고 다시 읽어서, 고칠 필드만 바꿔 씀. '사용자결정'은 절대 건드리지 않음(규약 0-8).
        고칠것: {id: {필드: 값}} (점수·판정처럼 dict 인 필드도 통째로 바꿈 — 합치기는 호출하는 쪽에서)
        새항목: 목록에 없던 항목(사용자결정이 없으면 '미정')"""
        고칠것 = 고칠것 or {}
        새항목 = 새항목 or []
        with 파일잠금(self.여행 / ".목록.lock", 이름=self.이름):
            원래 = 읽기_json(self.여행 / "목록.json")
            if 원래 is None and (self.여행 / "목록.json").exists():
                raise 도구오류("목록.json 을 읽지 못했어요(깨졌거나 다른 프로그램이 쓰는 중). 덮어쓰지 않고 멈춰요.")
            항목들 = [x for x in 목록항목(원래) if isinstance(x, dict)] if 원래 is not None else []
            있는id = {x.get("id") for x in 항목들}
            바뀜 = 0
            for x in 항목들:
                고칠 = 고칠것.get(x.get("id"))
                if not 고칠:
                    continue
                for k, v in 고칠.items():
                    if k in 지킬필드 or k == "id":
                        continue
                    if x.get(k) != v:
                        x[k] = v
                        바뀜 += 1
            더함 = 0
            for x in 새항목:
                if x.get("id") in 있는id:
                    continue
                x.setdefault("사용자결정", "미정")
                항목들.append(x)
                더함 += 1
            if 정렬:
                항목들.sort(key=정렬키)
            # 원래 파일이 {"항목": [...]} 모양이면 그 모양을 지킴
            if isinstance(원래, dict):
                for 키 in ("항목", "목록", "사진", "items"):
                    if isinstance(원래.get(키), list):
                        원래[키] = 항목들
                        break
                저장 = 원래
            else:
                저장 = 항목들
            원자적_쓰기(self.여행 / "목록.json", 저장)
        return {"바뀐값": 바뀜, "더한항목": 더함, "항목수": len(항목들)}

    def 상대(self, 경로: Path) -> str:
        try:
            return Path(경로).resolve().relative_to(self.여행.resolve()).as_posix()
        except ValueError:
            return Path(경로).as_posix()


def 인자틀(설명: str, 예시: str = "") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=설명, epilog=예시,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--여행", help="여행ID (여행/<여행ID>/ 폴더 이름)")
    ap.add_argument("--루트", help="여행스튜디오 폴더 대신 쓸 곳(시험용). 여행 폴더 = <루트>/여행/<여행ID>, 로그 = <루트>/로그")
    ap.add_argument("--작업ID", help="실패한 작업을 이어서 다시 할 때(작업이력.json 의 작업ID). 완료된 단계 산출물은 재사용")
    ap.add_argument("--자세히", action="store_true", help="진행 기록을 화면에도 자세히 보여 줌")
    return ap


def 실행틀(이름: str, 본문, 인자: argparse.Namespace, 편ID: str | None = None, 여행필수: bool = True) -> int:
    """도구 main 공통: 오류를 쉬운 말 + JSON 으로 바꾸고 작업이력에 '실패'를 남김."""
    실 = None
    try:
        실 = 도구실행(이름, 인자, 편ID=편ID, 여행필수=여행필수)
        결과 = 본문(실)
        return 0 if (결과 or {}).get("성공", True) else 1
    except 도구오류 as e:
        자료 = {"오류": e.메시지, **({"힌트": e.힌트} if e.힌트 else {}), **e.자료}
        if 실 is not None and 실.여행 is not None and 실.작업ID:
            자료["로그"] = 실.로그(f"{e.메시지}" + (f"\n힌트: {e.힌트}" if e.힌트 else ""), "오류")
            실.끝(자료, 성공=False, 재시도="가능" if e.코드 != 2 else "불가(설치 필요)")
        else:
            print(f"[{이름}] 오류: {e.메시지}" + (f"\n{e.힌트}" if e.힌트 else ""), file=sys.stderr)
            print(json.dumps({"성공": False, "도구": 이름, **자료}, ensure_ascii=False))
        return e.코드
    except KeyboardInterrupt:
        if 실 is not None and 실.작업ID:
            실.끝({"오류": "사용자가 멈춤"}, 성공=False)
        return 130
    except Exception as e:  # 예상 못 한 오류도 기록하고 쉬운 말로
        자료 = {"오류": f"예상 못 한 오류: {type(e).__name__}: {e}",
              "힌트": "로그/오늘.log 의 마지막 오류를 Claude에게 보여 주고 '원인을 찾아 고쳐줘'라고 하세요."}
        if 실 is not None and 실.여행 is not None and 실.작업ID:
            자료["로그"] = 실.로그(traceback.format_exc(), "오류")
            실.끝(자료, 성공=False)
        else:
            traceback.print_exc()
            print(json.dumps({"성공": False, "도구": 이름, **자료}, ensure_ascii=False))
        return 1
