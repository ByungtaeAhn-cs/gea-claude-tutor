# -*- coding: utf-8 -*-
"""작업함.py — Claude가 작업함(상태·질문·처리완료)·작업 이력·로그를 안전하게 고치는 도우미. (규약 v2 2.6·3절)

여행스튜디오 폴더에서 실행합니다. 아래에서 H = python .claude/skills/studio-connect/작업함.py
  진행·알림
    H 진행 --요청 r_… --작업 t20261007_1012_글쓰기_1일차 --단계 "초안 쓰는 중" --메시지 "블록 12개" --퍼센트 30
    H 알림 "사진 목록을 만들었어요: 사진 44장 · 영상 3개"
  컨셉(여행정보.json 의 '컨셉' 한 칸만 — 여행정보.json 은 직접 고치지 않음: 원본폴더·숨길장소·기기보정초는 도구·서버만)
    H 컨셉 --여행 <ID> --글 "아이와 처음 간 제주, 느리게 걷기"
    H 알림 "블로그 도우미 확장을 먼저 연결해 주세요(⑦ [확장 연결])" --키 확장연결필요   → 같은 키의 옛 알림은 '지난 알림'으로
    H 알림 --해결 확장연결필요                                                      → 그 키의 알림을 '지난 알림'으로
  질문 카드
    H 질문 --여행 2026-09_제주 --id q_20261007-1012_시계 --제목 "…" --설명 "…" --사진 p0012 p0040 --선택지 "네" "아니요" --관련요청 r_…
  처리완료로 옮기기
    H 완료 요청/20261007-101203-123_구성안.json 답변/q_….json [--완료표시 --메시지 "…"]
  작업 이력(재시도·이어하기)
    H 이력 시작 --여행 <ID> --종류 글쓰기 --편 1일차 --요청 r_…      → 작업ID 출력
    H 이력 단계 --여행 <ID> --작업 <작업ID> --이름 초안 --상태 완료 --산출물 원고/1일차.md
    H 이력 단계 --여행 <ID> --작업 <작업ID> --이름 미리보기 --상태 실패 --오류 "…"   → 로그에 오류, 작업 '실패'(자동 멈춤)
    H 이력 끝 --여행 <ID> --작업 <작업ID> --상태 성공
    H 이력 재시도 --여행 <ID> --작업 <작업ID> [--처음부터]   → 다시 시작할 단계·재사용할 산출물 출력
    H 이력 보기 --여행 <ID> [--작업 <작업ID>]
  로그
    H 로그 "목록 만들기 시작" --여행 <ID> [--오류]           → '로그/YYYY-MM-DD.log#L번호' 출력
  발행(블로그 도우미 확장 — 스튜디오 서버가 공용 발행 API 로 처리)
    H 발행 시작 --여행 <ID> --편 1일차 [--새로]       (임시저장만. 예약 발행은 사람이 화면 ⑦에서만 — 보안 검수 H1)
      (--새로: 이미 임시저장했거나 실패한 작업이 있는 편을 새 글로 다시 — 사용자가 분명히 원할 때만)
    H 발행 보기 --여행 <ID> --편 1일차
    H 발행 다시 --작업 n20261007-101233-a3f9 [--처음부터]
  판정(콘택트 시트 결과 합치기 — 사용자결정은 안 건드림)
    H 판정 --여행 <ID> --파일 여행/<ID>/작업/판정_1.json
  H 보기   (상태.json·쌓인 요청)
  H 보기 목록 --여행 '<ID>' [--id p0016-p0024 | p0003,p0010] [--일차 2] [--결정 사용] [--필드 id,촬영시각,판정]
      (목록.json 을 읽기만 하는 걸러 보기 — 서브에이전트·직접 python 대신. 여행ID 는 작은따옴표로)
마지막 줄에 JSON 요약을 출력합니다.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

스튜디오 = Path(__file__).resolve().parents[3]  # .claude/skills/studio-connect/ 의 세 단계 위
작업함 = 스튜디오 / "작업함"
로그폴더 = 스튜디오 / "로그"
금지글자 = '\\/:*?"<>|'


def 지금() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def 사용중(e: BaseException) -> bool:
    """Windows: 다른 프로그램이 파일을 잠깐 열고 있거나 막 지워지는 중이면 PermissionError(5·32·33) → '사용 중'.
    도구/_공통.py·서버와 같은 규칙으로 짧게 기다렸다 다시 합니다."""
    return isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32, 33)


def _읽기(경로: Path, 번수: int = 12):
    for 번 in range(번수):
        try:
            with open(경로, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            raise
        except OSError as e:
            if not 사용중(e) or 번 == 번수 - 1:
                raise
            time.sleep(0.02 * (번 + 1))


def 읽기(경로: Path, 기본=None):
    """보기용: 없거나·깨졌거나·계속 사용 중이면 기본값."""
    try:
        return _읽기(Path(경로))
    except (OSError, ValueError):
        return 기본


def 고칠것읽기(경로: Path, 기본=None, 깨지면_새로: bool = False):
    """읽고-고치고-쓰기용(잠금 안에서): 없으면 기본값. 계속 사용 중이거나 깨졌으면 멈춤 →
    잠깐 못 읽었다고 빈 값으로 덮어써 기록이 사라지는 일을 막음(깨지면_새로=True 면 '.깨짐'으로 남기고 새로)."""
    경로 = Path(경로)
    try:
        return _읽기(경로)
    except FileNotFoundError:
        return 기본
    except ValueError:
        if 깨지면_새로:
            try:
                shutil.copy2(경로, 경로.with_name(경로.name + ".깨짐"))
            except OSError:
                pass
            return 기본
        raise SystemExit(f"{경로.name} 파일이 깨져 있어요(JSON 모양이 아님). 내용을 확인해 고친 뒤 다시 실행하세요.")
    except OSError:
        raise SystemExit(f"{경로.name} 을(를) 다른 프로그램이 쓰고 있어요. 잠시 뒤 다시 실행하세요.")


def 쓰기(경로: Path, 데이터):
    경로.parent.mkdir(parents=True, exist_ok=True)
    임시 = 경로.with_name(f".{경로.name}.{os.getpid()}.tmp")
    with open(임시, "w", encoding="utf-8", newline="\n") as f:
        json.dump(데이터, f, ensure_ascii=False, indent=2)
    for 번 in range(40):  # Windows: 다른 프로그램이 잠깐 열고 있으면 바꿔 끼우기 실패 → 백오프로 다시
        try:
            os.replace(임시, 경로)
            return
        except OSError as e:
            if not 사용중(e):
                break
            time.sleep(0.05 * (번 + 1))
    try:
        임시.unlink()
    except OSError:
        pass
    raise SystemExit(f"{경로.name} 을(를) 쓰지 못했어요(다른 프로그램이 열고 있음). 잠시 뒤 다시 실행하세요.")


class 잠금:
    """서버·대기.py·도구와 같은 잠금 파일 이름·규칙으로 같은 파일을 동시에 고치지 않게."""

    def __init__(self, 경로: Path, 기다림=15.0, 오래됨=30.0, 실패시멈춤=True):
        self.경로, self.기다림, self.오래됨, self.실패시멈춤 = 경로, 기다림, 오래됨, 실패시멈춤
        self.얻음 = False

    def __enter__(self):
        끝 = time.monotonic() + self.기다림
        self.경로.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.경로, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, f"{os.getpid()} 작업함.py".encode("utf-8"))
                finally:
                    os.close(fd)
                self.얻음 = True
                return self
            except (FileExistsError, PermissionError):  # 막 지워지는 중인 잠금 파일은 PermissionError
                try:
                    if time.time() - self.경로.stat().st_mtime > self.오래됨:
                        self.경로.unlink()
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass
                if time.monotonic() > 끝:
                    if self.실패시멈춤:
                        raise SystemExit(f"{self.경로.name} 잠금을 얻지 못했어요(다른 작업 중). 잠시 뒤 다시 실행하세요.")
                    return self
                time.sleep(random.uniform(0.005, 0.03))  # 짧고 고르지 않게 — 여러 프로그램이 번갈아 잡게

    def __exit__(self, *_):
        if not self.얻음:
            return
        for 번 in range(20):
            try:
                self.경로.unlink()
                return
            except FileNotFoundError:
                return
            except OSError as e:
                if not 사용중(e):
                    return
                time.sleep(0.02 * (번 + 1))


def 여행폴더(여행ID: str) -> Path:
    if not 여행ID or any(c in 여행ID for c in 금지글자) or 여행ID.startswith("."):
        raise SystemExit("여행ID 가 올바르지 않아요")
    p = 스튜디오 / "여행" / 여행ID
    if not p.is_dir():
        raise SystemExit(f"'{여행ID}' 여행 폴더가 없어요")
    return p


# ---------------------------------------------------------------- 로그

def 로그쓰기(메시지: str, 여행ID: str | None = None, 오류: bool = False) -> str:
    """로그/오늘.log 에 한 줄 쓰고 '로그/날짜.log#L줄번호' 를 돌려줌(이력의 '로그' 칸에 씀)."""
    로그폴더.mkdir(parents=True, exist_ok=True)
    날짜 = f"{datetime.now():%Y-%m-%d}"
    파일 = 로그폴더 / f"{날짜}.log"
    한줄 = " ".join(str(메시지).split())[:4000]
    with 잠금(로그폴더 / ".로그.lock", 기다림=30, 오래됨=60, 실패시멈춤=False) as 잠긴것:
        if not 잠긴것.얻음:  # 잠금 없이 쓰면 다른 프로그램과 같은 자리에 덧써 글자가 깨짐 → 쓰지 않고 알림
            print(f"[작업함] 로그 잠금을 얻지 못해 로그에 쓰지 못함: {한줄[:200]}", file=sys.stderr)
            return None
        줄수 = 0
        for 번 in range(10):
            try:
                with open(파일, "rb") as f:
                    줄수 = sum(1 for _ in f)
                break
            except FileNotFoundError:
                break
            except OSError as e:
                if not 사용중(e):
                    break
                time.sleep(0.02 * (번 + 1))
        with open(파일, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{'오류' if 오류 else '정보'}] [Claude]"
                    f"{f' [{여행ID}]' if 여행ID else ''} {한줄}\n")
    return f"로그/{날짜}.log#L{줄수 + 1}"


def 로그(a):
    return {"로그": 로그쓰기(" ".join(a.글), a.여행, a.오류)}


# ---------------------------------------------------------------- 상태.json(진행·알림)

def 상태고치기(고치기):
    with 잠금(작업함 / ".상태.lock", 기다림=5, 오래됨=15):
        상태 = 고칠것읽기(작업함 / "상태.json", {}, 깨지면_새로=True)
        if not isinstance(상태, dict):
            상태 = {}
        상태.setdefault("연결", {"마지막신호": None})
        상태.setdefault("진행", [])
        상태.setdefault("알림", [])
        고치기(상태)
        쓰기(작업함 / "상태.json", 상태)
        return 상태


def 진행남기기(요청id, 작업ID, 단계, 메시지="", 퍼센트=None, 상태="진행중") -> dict:
    항목 = {"요청id": 요청id, "작업ID": 작업ID, "단계": 단계, "메시지": 메시지 or "", "퍼센트": 퍼센트,
          "상태": 상태, "갱신": 지금()}
    열쇠 = 작업ID or 요청id

    def 고치기(s):
        목록 = [x for x in s["진행"] if isinstance(x, dict) and (x.get("작업ID") or x.get("요청id")) != 열쇠]
        목록.append(항목)
        s["진행"] = 목록[-20:]  # 최근 20개만
    상태고치기(고치기)
    return 항목


def 진행(a):
    if not (a.요청 or a.작업):
        raise SystemExit("--요청 이나 --작업 중 하나는 필요해요")
    return {"진행": 진행남기기(a.요청, a.작업, a.단계, a.메시지, a.퍼센트, a.상태)}


def 알림(a):
    """화면 알림 = {"글","시각","키"}. 같은 키의 옛 알림·--해결 한 키의 알림은 지우지 않고 '지난알림'으로 옮김."""
    글 = " ".join(a.글 or []).strip()
    if not 글 and not a.해결:
        raise SystemExit("알림 글이나 --해결 <키> 중 하나는 필요해요")
    옮길키 = {k for k in (a.키, a.해결) if k}
    옮김 = []

    def 고치기(s):
        남김 = []
        for x in s["알림"]:
            if isinstance(x, dict) and x.get("키") in 옮길키:
                옮김.append({**x, "해결": "해결됨" if x.get("키") == a.해결 else "같은 키의 새 알림", "해결시각": 지금()})
            else:
                남김.append(x)
        if 글:
            남김.append({"글": 글, "시각": 지금(), "키": a.키})
        s["알림"] = 남김[-20:]
        if 옮김:
            s["지난알림"] = (list(s.get("지난알림") or []) + 옮김)[-30:]
    상태고치기(고치기)
    return {"알림": 글 or None, "키": a.키, "지난알림으로": len(옮김)}


# ---------------------------------------------------------------- 컨셉(여행정보.json 의 한 칸만)

컨셉최대 = 120


def 컨셉(a):
    """질문 카드로 받은 여행 컨셉을 여행정보.json '컨셉'에만 씀(한 줄·120자 이하). 다른 칸은 손대지 않음(재검수 N4)."""
    p = 여행폴더(a.여행)
    글 = "".join(c for c in " ".join(str(a.글).split()) if c.isprintable()).strip()
    if not 글:
        raise SystemExit("컨셉 글이 비었어요")
    if len(글) > 컨셉최대:
        raise SystemExit(f"컨셉은 {컨셉최대}자 이하로 적어 주세요(지금 {len(글)}자)")
    with 잠금(p / ".여행정보.lock", 기다림=10, 오래됨=30):
        정보 = 고칠것읽기(p / "여행정보.json", None)
        if not isinstance(정보, dict):
            raise SystemExit("여행정보.json 을 읽지 못했어요(다른 프로그램이 쓰는 중일 수 있어요). 잠시 뒤 다시 하세요.")
        정보["컨셉"] = 글
        쓰기(p / "여행정보.json", 정보)
    로그쓰기(f"컨셉 정함(사용자 답): {글}", a.여행)
    return {"컨셉": 글}


# ---------------------------------------------------------------- 질문·완료

def 질문(a):
    if any(c in a.id for c in 금지글자) or a.id.startswith("."):
        raise SystemExit("질문 id 에 쓸 수 없는 글자가 있어요")
    q = {
        "id": a.id, "여행ID": a.여행, "제목": a.제목, "설명": a.설명 or "", "사진": a.사진 or [],
        "선택지": a.선택지 or [], "여러개선택": bool(a.여러개), "입력칸": bool(a.입력칸 or not a.선택지),
        "관련요청": a.관련요청, "보낸시각": 지금(),
    }
    쓰기(작업함 / "질문" / f"{a.id}.json", q)
    로그쓰기(f"질문 카드: {a.제목} ({a.id})", a.여행)
    return {"질문": q}


def 완료(a):
    옮김 = []
    (작업함 / "처리완료").mkdir(parents=True, exist_ok=True)
    for 이름 in a.파일:
        원래 = (작업함 / 이름).resolve()
        if 원래.parent.name not in ("요청", "답변") or 원래.parent.parent != 작업함.resolve():
            raise SystemExit(f"요청/ 이나 답변/ 안의 파일만 옮길 수 있어요: {이름}")
        if not 원래.is_file():
            print(f"(이미 옮겼거나 없음: {이름})", file=sys.stderr)
            continue
        대상 = 작업함 / "처리완료" / 원래.name
        shutil.move(str(원래), str(대상))
        옮김.append(f"처리완료/{원래.name}")
        d = 읽기(대상, {}) or {}
        로그쓰기(f"처리완료로 옮김: {원래.parent.name}/{원래.name} {d.get('종류', '')}", d.get("여행ID"))
        if a.완료표시 and 원래.parent.name == "요청" and d.get("id"):
            진행남기기(d["id"], a.작업, "완료", a.메시지 or "", 100, "완료")
    return {"옮김": 옮김}


# ---------------------------------------------------------------- 작업 이력(작업이력.json)

def 이력파일(여행ID: str) -> Path:
    return 여행폴더(여행ID) / "작업이력.json"


def 이력고치기(여행ID: str, 고치기):
    파일 = 이력파일(여행ID)
    with 잠금(파일.parent / ".작업이력.lock"):
        이력 = 고칠것읽기(파일, [])
        if not isinstance(이력, list):
            raise SystemExit("작업이력.json 모양이 달라요([…] 이어야 함). 내용을 확인해 주세요.")
        결과 = 고치기(이력)
        쓰기(파일, 이력)
        return 결과


def 작업찾기(이력: list, 작업ID: str) -> dict:
    for x in 이력:
        if isinstance(x, dict) and x.get("작업ID") == 작업ID:
            return x
    raise SystemExit(f"작업 이력에서 '{작업ID}' 를 찾지 못했어요")


def 이력시작(a):
    편 = a.편 or ""
    if 편 and (any(c in 편 for c in 금지글자) or " " in 편):
        raise SystemExit("편ID 에 공백·특수문자가 있어요")
    머리 = f"t{datetime.now():%Y%m%d_%H%M}_{a.종류}" + (f"_{편}" if 편 else "")

    def 고치기(이력):
        있는것 = {x.get("작업ID") for x in 이력 if isinstance(x, dict)}
        작업ID, n = 머리, 2
        while 작업ID in 있는것:
            작업ID, n = f"{머리}-{n}", n + 1
        이력.append({"작업ID": 작업ID, "종류": a.종류, "편ID": 편 or None, "요청id": a.요청, "상태": "진행중",
                   "단계": [], "재시도": "가능", "재시도횟수": 0, "시작": 지금(), "끝": ""})
        return 작업ID
    작업ID = 이력고치기(a.여행, 고치기)
    로그쓰기(f"작업 시작: {작업ID}", a.여행)
    진행남기기(a.요청, 작업ID, "시작", f"{a.종류} {편}".strip(), 0, "진행중")
    return {"작업ID": 작업ID}


def 이력단계(a):
    로그칸 = None
    if a.상태 == "실패":
        로그칸 = 로그쓰기(f"단계 실패: {a.작업} / {a.이름} — {a.오류 or '(이유 없음)'}", a.여행, 오류=True)
    else:
        로그쓰기(f"단계 {a.상태}: {a.작업} / {a.이름}" + (f" → {a.산출물}" if a.산출물 else ""), a.여행)

    def 고치기(이력):
        x = 작업찾기(이력, a.작업)
        단계 = next((s for s in x["단계"] if s.get("이름") == a.이름), None)
        if 단계 is None:
            단계 = {"이름": a.이름}
            x["단계"].append(단계)
        단계["상태"] = a.상태
        단계["시각"] = 지금()
        if a.산출물:
            단계["산출물"] = a.산출물
        if a.상태 == "실패":
            단계["오류"] = a.오류 or ""
            단계["로그"] = 로그칸
            x["상태"] = "실패"              # 오류가 나면 그 작업은 자동으로 멈춤(규약 2.6)
            x["재시도"] = f"불가({a.재시도불가})" if a.재시도불가 else "가능"
            x["끝"] = 지금()
        else:
            단계.pop("오류", None)
            단계.pop("로그", None)
        return x
    x = 이력고치기(a.여행, 고치기)
    if a.상태 == "실패":
        진행남기기(x.get("요청id"), a.작업, a.이름, f"{a.이름} 단계에서 멈춤: {a.오류 or ''}"[:200], None, "실패")
    else:
        진행남기기(x.get("요청id"), a.작업, a.이름, a.메시지 or a.이름, a.퍼센트, "진행중")
    return {"작업ID": a.작업, "단계": a.이름, "상태": a.상태, "로그": 로그칸}


def 이력끝(a):
    def 고치기(이력):
        x = 작업찾기(이력, a.작업)
        x["상태"] = a.상태
        x["끝"] = 지금()
        if a.재시도불가:
            x["재시도"] = f"불가({a.재시도불가})"
        return x
    x = 이력고치기(a.여행, 고치기)
    로그쓰기(f"작업 끝: {a.작업} → {a.상태}", a.여행, 오류=a.상태 == "실패")
    진행남기기(x.get("요청id"), a.작업, "완료" if a.상태 == "성공" else a.상태,
             a.메시지 or "", 100 if a.상태 == "성공" else None, "완료" if a.상태 == "성공" else a.상태)
    return {"작업ID": a.작업, "상태": a.상태}


def 이력재시도(a):
    """실패한 단계부터 다시(앞 단계 산출물 재사용). --처음부터 면 산출물을 처리완료/보관/ 으로 옮기고 처음부터."""
    p = 여행폴더(a.여행)
    보관 = []

    def 고치기(이력):
        x = 작업찾기(이력, a.작업)
        if str(x.get("재시도") or "").startswith("불가") and not a.처음부터:
            raise SystemExit(f"이 작업은 이어서 다시 할 수 없어요: {x['재시도']} — --처음부터 를 쓰세요")
        x["재시도횟수"] = int(x.get("재시도횟수") or 0) + 1
        x["상태"] = "진행중"
        x["끝"] = ""
        if a.처음부터:
            폴더 = 작업함 / "처리완료" / "보관" / f"{x['작업ID']}_{datetime.now():%Y%m%d-%H%M%S}"
            for s in x["단계"]:
                산출 = s.get("산출물")
                if not 산출:
                    continue
                원래 = (p / 산출).resolve()
                if 원래.is_file() and str(원래).startswith(str(p.resolve())):
                    폴더.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(원래), str(폴더 / 원래.name))
                    보관.append(f"{산출} → {폴더.relative_to(스튜디오).as_posix()}/{원래.name}")
            x["이전단계"] = (x.get("이전단계") or []) + [x["단계"]]
            x["단계"] = []
            x["재시도"] = "가능"
            return x, None, []
        다시 = next((s["이름"] for s in x["단계"] if s.get("상태") != "완료"), None)
        재사용 = [{"이름": s["이름"], "산출물": s.get("산출물")} for s in x["단계"] if s.get("상태") == "완료"]
        return x, 다시, 재사용
    x, 다시, 재사용 = 이력고치기(a.여행, 고치기)
    로그쓰기(f"재시도({'처음부터' if a.처음부터 else '실패한 단계부터'}): {a.작업} {x['재시도횟수']}번째" +
            (f", 보관 {len(보관)}개" if 보관 else ""), a.여행)
    진행남기기(x.get("요청id"), a.작업, 다시 or "처음부터", "다시 시도 중", 0, "진행중")
    return {"작업ID": a.작업, "처음부터": a.처음부터, "다시시작단계": 다시, "재사용": 재사용, "보관": 보관}


def 이력보기(a):
    이력 = 읽기(이력파일(a.여행), []) or []
    if a.작업:
        return {"작업": 작업찾기(이력, a.작업)}
    return {"이력": 이력[-20:]}


# ---------------------------------------------------------------- 판정(콘택트 시트 결과)

def 판정(a):
    """판정 파일(JSON)의 내용을 목록.json 에 합치기. '판정'·'장면설명'만 고치고 '사용자결정'은 절대 건드리지 않음."""
    p = 여행폴더(a.여행)
    목록파일 = p / "목록.json"
    새것 = 읽기(Path(a.파일))
    if isinstance(새것, list):
        새것 = {x.get("id"): x for x in 새것 if isinstance(x, dict) and x.get("id")}
    if not isinstance(새것, dict) or not 새것:
        raise SystemExit("판정 파일이 비었거나 모양이 달라요. 예: {\"p0001\": {\"판정\": {\"제외후보\": true, \"사유\": [\"흐림\"]}, \"장면설명\": \"…\"}}")
    with 잠금(p / ".목록.lock"):            # 화면 서버와 같은 잠금 → 쓰기 직전에 다시 읽음(규약 0절 8)
        목록 = 고칠것읽기(목록파일)
        if 목록 is None:
            raise SystemExit("목록.json 이 없어요(먼저 사진 목록 만들기)")
        항목들 = 목록 if isinstance(목록, list) else ((목록.get("항목") or 목록.get("목록") or []) if isinstance(목록, dict) else [])
        바뀜, 있는id = 0, set()
        for 항목 in 항목들:
            고칠것 = 새것.get(항목.get("id"))
            if not isinstance(고칠것, dict):
                continue
            있는id.add(항목["id"])
            if isinstance(고칠것.get("판정"), dict):
                항목["판정"] = {**(항목.get("판정") or {}), **고칠것["판정"]}
            if isinstance(고칠것.get("장면설명"), str):
                항목["장면설명"] = 고칠것["장면설명"]
            바뀜 += 1
        쓰기(목록파일, 목록)
    로그쓰기(f"판정 합침: {바뀜}장 ({Path(a.파일).name})", a.여행)
    return {"바뀜": 바뀜, "목록에없는id": sorted(set(새것) - 있는id)}


# ---------------------------------------------------------------- 발행(스튜디오 서버 → 공용 발행 API 에 맡김)

def _서버(경로: str, 몸: dict | None = None) -> tuple[int, dict]:
    """켜져 있는 스튜디오 서버(127.0.0.1:8765)에 묻기. 발행 작업은 서버가 공용 발행서버 모듈로 처리."""
    import urllib.error
    import urllib.request
    from urllib.parse import quote
    주소 = "http://127.0.0.1:8765" + quote(경로, safe="/?=&")
    req = urllib.request.Request(주소, data=json.dumps(몸, ensure_ascii=False).encode("utf-8") if 몸 is not None else None,
                                 headers={"Content-Type": "application/json"} if 몸 is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")
    except OSError:
        raise SystemExit("스튜디오 서버가 꺼져 있어요. 먼저 'python 스튜디오실행.pyw --브라우저안열기'")


def 발행시작(a):
    몸 = {"여행ID": a.여행, "편ID": a.편, "모드": "임시저장"}  # 예약 발행 작업은 만들지 않음(사람이 화면에서만)
    if a.새로:
        몸["새로"] = True
    상태, d = _서버("/api/발행작업", 몸)
    if 상태 != 200:
        로그쓰기(f"발행 작업을 만들지 못함({a.편}): {d.get('오류')}", a.여행, 오류=True)
        if d.get("코드") in ("이미_임시저장", "실패한_작업있음"):
            raise SystemExit(f"발행 작업을 만들지 않았어요({d.get('코드')}): {d.get('오류')} "
                             "→ 사용자에게 물어보세요. 실패한 작업은 'H 발행 다시 --작업 <작업ID>'(같은 화면에서 이어 하기), "
                             "새 글로 한 번 더 넣기를 사용자가 분명히 원하면 --새로.")
        raise SystemExit(f"발행 작업을 만들지 못했어요({d.get('코드')}): {d.get('오류')}")
    return {"작업": d["작업"], "브라우저": d.get("브라우저")}


def 발행다시(a):
    상태, d = _서버("/api/발행작업/다시", {"작업ID": a.작업, "처음부터": bool(a.처음부터)})
    if 상태 != 200:
        raise SystemExit(f"다시 시도하지 못했어요({d.get('코드')}): {d.get('오류')}")
    return {"작업": d["작업"], "브라우저": d.get("브라우저")}


def 발행보기(a):
    if any(c in a.여행 + a.편 for c in "&=?#%"):
        raise SystemExit("--여행·--편 에 & = ? # % 는 쓸 수 없어요")
    상태, d = _서버(f"/api/발행상태?여행={a.여행}&편={a.편}")
    if 상태 != 200:
        raise SystemExit(f"발행 상태를 읽지 못했어요: {d.get('오류')}")
    j = d.get("최근작업") or {}
    return {"작업ID": j.get("작업ID"), "상태": j.get("상태"), "현재단계": j.get("현재단계"), "실패": j.get("실패"),
            "단계": [(s.get("이름"), s.get("상태"), s.get("메시지")) for s in j.get("단계") or []],
            "패키지": {k: (d.get("패키지") or {}).get(k) for k in ("있음", "오래됨", "묶음수", "사진수", "경고")},
            "확장연결수": len((d.get("확장") or {}).get("연결") or [])}


def _번호(id_):
    import re
    m = re.fullmatch(r"p(\d+)", str(id_))
    return int(m.group(1)) if m else None


def 목록보기(a):
    """2026-10-08 실측: 목록.json 의 일부만 보려고 서브에이전트가 python -c 를 직접 돌려 승인 창이 열두 번 떴음 → 읽기 전용 걸러 보기."""
    p = 여행폴더(a.여행)
    목록 = 읽기(p / "목록.json")
    if 목록 is None:
        raise SystemExit("목록.json 이 없어요(먼저 사진 목록 만들기)")
    항목들 = 목록 if isinstance(목록, list) else ((목록.get("항목") or 목록.get("목록") or []) if isinstance(목록, dict) else [])
    항목들 = [x for x in 항목들 if isinstance(x, dict)]
    if a.id:
        고름, 범위 = set(), []
        for 조각 in a.id.replace(" ", "").split(","):
            앞, _, 뒤 = 조각.partition("-")
            if 뒤 and _번호(앞) is not None and _번호(뒤) is not None:
                범위.append((_번호(앞), _번호(뒤)))
            elif 조각:
                고름.add(조각)
        항목들 = [x for x in 항목들 if x.get("id") in 고름 or any(
            _번호(x.get("id")) is not None and 가 <= _번호(x.get("id")) <= 나 for 가, 나 in 범위)]
    if a.일차 is not None:
        항목들 = [x for x in 항목들 if x.get("일차") == a.일차]
    if a.결정:
        항목들 = [x for x in 항목들 if (x.get("사용자결정") or "미정") == a.결정]
    필드 = [f.strip() for f in a.필드.split(",") if f.strip()]
    한도 = 200
    return {"전체": len(항목들), "보임": min(len(항목들), 한도),
            "항목": [{k: x.get(k) for k in 필드} for x in 항목들[:한도]]}


def 보기(_a):
    if getattr(_a, "대상", None) == "목록":
        if not _a.여행:
            raise SystemExit("--여행 '<여행ID>' 를 알려 주세요")
        return 목록보기(_a)
    완료됨 = {f.name for f in (작업함 / "처리완료").glob("*.json")}
    쌓임 = {종류: [f.name for f in sorted((작업함 / 종류).glob("*.json"))
                 if not f.name.startswith(".") and f.name not in 완료됨] for 종류 in ("요청", "답변")}
    return {"상태": 읽기(작업함 / "상태.json", {}), "쌓임": 쌓임}


def main():
    ap = argparse.ArgumentParser(description="작업함·작업 이력·로그 도우미")
    sub = ap.add_subparsers(dest="명령", required=True)

    p = sub.add_parser("진행", help="상태.json 진행 항목 고치기(작업ID 또는 요청id 마다 하나)")
    p.add_argument("--요청")
    p.add_argument("--작업")
    p.add_argument("--단계", required=True)
    p.add_argument("--메시지", default="")
    p.add_argument("--퍼센트", type=int, default=None)
    p.add_argument("--상태", default="진행중", choices=["진행중", "완료", "멈춤", "실패"])
    p.set_defaults(함수=진행)

    p = sub.add_parser("알림", help="화면에 띄울 알림 한 줄 더하기(--키: 같은 키 옛 알림은 지난 알림으로, --해결: 그 키 알림 치우기)")
    p.add_argument("글", nargs="*")
    p.add_argument("--키", help="알림 종류(예: 확장연결필요, 패키지:<여행ID>/<편ID>)")
    p.add_argument("--해결", help="이 키의 알림을 '지난 알림'으로 옮김(문제가 풀렸을 때)")
    p.set_defaults(함수=알림)

    p = sub.add_parser("컨셉", help="여행 컨셉(질문 카드의 답)을 여행정보.json '컨셉'에만 쓰기(120자 이하)")
    p.add_argument("--여행", required=True)
    p.add_argument("--글", required=True)
    p.set_defaults(함수=컨셉)

    p = sub.add_parser("질문", help="질문 카드 만들기(작업함/질문/<id>.json)")
    p.add_argument("--여행", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--제목", required=True)
    p.add_argument("--설명", default="")
    p.add_argument("--사진", nargs="*", default=[])
    p.add_argument("--선택지", nargs="*", default=[])
    p.add_argument("--여러개", action="store_true", help="여러 개 고를 수 있음")
    p.add_argument("--입력칸", action="store_true", help="직접 적는 칸 보이기(선택지가 없으면 항상 보임)")
    p.add_argument("--관련요청", default=None)
    p.set_defaults(함수=질문)

    p = sub.add_parser("완료", help="처리한 요청·답변을 처리완료/로 옮기기")
    p.add_argument("파일", nargs="+", help="예: 요청/20261007-101203-123_구성안.json")
    p.add_argument("--완료표시", action="store_true", help="요청의 진행 항목을 '완료 100%%'로")
    p.add_argument("--작업", default=None)
    p.add_argument("--메시지", default="")
    p.set_defaults(함수=완료)

    p = sub.add_parser("이력", help="작업 이력(작업이력.json): 시작·단계·끝·재시도·보기")
    이력 = p.add_subparsers(dest="이력명령", required=True)
    q = 이력.add_parser("시작")
    q.add_argument("--여행", required=True)
    q.add_argument("--종류", required=True)
    q.add_argument("--편")
    q.add_argument("--요청")
    q.set_defaults(함수=이력시작)
    q = 이력.add_parser("단계")
    q.add_argument("--여행", required=True)
    q.add_argument("--작업", required=True)
    q.add_argument("--이름", required=True)
    q.add_argument("--상태", required=True, choices=["진행중", "완료", "실패", "건너뜀"])
    q.add_argument("--산출물")
    q.add_argument("--오류")
    q.add_argument("--메시지", default="")
    q.add_argument("--퍼센트", type=int)
    q.add_argument("--재시도불가", help="이어서 다시 할 수 없는 이유(예: 원본 폴더가 없음)")
    q.set_defaults(함수=이력단계)
    q = 이력.add_parser("끝")
    q.add_argument("--여행", required=True)
    q.add_argument("--작업", required=True)
    q.add_argument("--상태", required=True, choices=["성공", "실패", "멈춤"])
    q.add_argument("--메시지", default="")
    q.add_argument("--재시도불가")
    q.set_defaults(함수=이력끝)
    q = 이력.add_parser("재시도")
    q.add_argument("--여행", required=True)
    q.add_argument("--작업", required=True)
    q.add_argument("--처음부터", action="store_true")
    q.set_defaults(함수=이력재시도)
    q = 이력.add_parser("보기")
    q.add_argument("--여행", required=True)
    q.add_argument("--작업")
    q.set_defaults(함수=이력보기)

    p = sub.add_parser("로그", help="로그/오늘.log 에 한 줄(줄 번호 출력)")
    p.add_argument("글", nargs="+")
    p.add_argument("--여행")
    p.add_argument("--오류", action="store_true")
    p.set_defaults(함수=로그)

    p = sub.add_parser("판정", help="콘택트 시트로 본 판정을 목록.json 에 합치기(사용자결정은 안 건드림)")
    p.add_argument("--여행", required=True)
    p.add_argument("--파일", required=True, help="판정 JSON 파일(예: 여행/<ID>/작업/판정_1.json)")
    p.set_defaults(함수=판정)

    p = sub.add_parser("발행", help="네이버 발행 작업(블로그 도우미 확장): 시작·보기 — 스튜디오 서버가 공용 발행 API로 처리")
    발행 = p.add_subparsers(dest="발행명령", required=True)
    q = 발행.add_parser("시작", help="임시저장 작업 만들기 + 설정한 브라우저(Chrome·Edge·기본)로 글쓰기 화면 열기(예약 발행은 화면에서 사람만)")
    q.add_argument("--여행", required=True)
    q.add_argument("--편", required=True)
    q.add_argument("--새로", action="store_true",
                   help="이미 임시저장했거나 실패한 작업이 있어도 새 작업(네이버에 새 글로 저장됨 — 사용자가 원할 때만)")
    q.set_defaults(함수=발행시작)
    q = 발행.add_parser("다시", help="실패·취소한 발행 작업을 실패한 단계부터(또는 --처음부터) 다시 + 글쓰기 화면 열기")
    q.add_argument("--작업", required=True)
    q.add_argument("--처음부터", action="store_true")
    q.set_defaults(함수=발행다시)
    q = 발행.add_parser("보기", help="그 편의 최근 발행 작업·단계·패키지 경고")
    q.add_argument("--여행", required=True)
    q.add_argument("--편", required=True)
    q.set_defaults(함수=발행보기)

    p = sub.add_parser("보기", help="상태와 쌓인 요청 보기 / '보기 목록 --여행 …' 은 목록.json 걸러 보기(읽기 전용)")
    p.add_argument("대상", nargs="?", choices=["목록"])
    p.add_argument("--여행")
    p.add_argument("--id", help="p0016-p0024 (범위) 또는 p0003,p0010 (쉼표)")
    p.add_argument("--일차", type=int)
    p.add_argument("--결정", choices=["미정", "사용", "대표", "제외"])
    p.add_argument("--필드", default="id,종류,기기,촬영시각,일차,사용자결정,판정,장면설명", help="쉼표로 구분")
    p.set_defaults(함수=보기)

    a = ap.parse_args()
    for 이름 in ("요청", "질문", "답변", "처리완료"):  # 아직 서버·대기.py 를 켠 적이 없어도 되게
        (작업함 / 이름).mkdir(parents=True, exist_ok=True)
    print(json.dumps(a.함수(a), ensure_ascii=False))


if __name__ == "__main__":
    main()
