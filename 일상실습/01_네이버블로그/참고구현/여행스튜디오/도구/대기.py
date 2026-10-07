# -*- coding: utf-8 -*-
"""대기.py — 화면(GUI)에서 온 요청·답변을 기다립니다. (여행스튜디오_규약.md v2 3절)

Claude가 이 스크립트를 '백그라운드'로 켜 둡니다.
- 3초마다 작업함/상태.json 의 연결.마지막신호 를 지금 시각으로 바꿉니다 → 화면에 '연결됨'.
- 작업함/요청/ 이나 작업함/답변/ 에 아직 처리 안 한 파일이 생기면, 그 내용을 JSON 한 줄로 출력하고 끝납니다.
  (처리완료/ 에 같은 이름이 있으면 이미 처리한 것이므로 무시)
- 50분 동안 아무 일이 없으면 {"종류":"시간초과"} 를 출력하고 끝납니다 → Claude가 다시 켭니다.
- 이 스크립트가 끝나면 Claude에게 알림이 가고, Claude가 깨어나 출력된 요청을 처리합니다.
- 시작·깨움·시간초과·교대를 로그/YYYY-MM-DD.log 에 남깁니다(3초 신호는 남기지 않음).

사용:  python 도구/대기.py            (기다리기)
       python 도구/대기.py --한번     (기다리지 않고 지금 쌓인 것만 확인 → 없으면 {"종류":"없음"}. 연결 신호는 안 남김)
시험용: --폴더 <여행스튜디오 폴더>  --간격 3  --최대분 50
출력(마지막 줄 JSON):
  {"종류":"새작업","요청":[{"파일":"…","내용":{…}}],"답변":[{"파일":"…","내용":{…},"질문":{…}}]}
  {"종류":"시간초과"} · {"종류":"없음"} · {"종류":"교대"}(다른 대기.py가 새로 켜져서 이쪽은 물러남)
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

for _s in (sys.stdout, sys.stderr):  # 안내 글(stderr)도 UTF-8 — Windows 에서 한글이 깨지지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def 지금() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def 사용중(e: BaseException) -> bool:
    """Windows: 다른 프로그램이 파일을 잠깐 열고 있거나 막 지워지는 중이면 PermissionError(5·32·33) → '사용 중'."""
    return isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32, 33)


def 읽기_엄격(경로: Path, 번수: int = 12):
    """JSON 읽기. 없으면 FileNotFoundError, '사용 중'이면 백오프로 다시, 끝까지 안 되면 그 오류."""
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


def 읽기_json(경로: Path):
    """요청·답변 파일 읽기: 못 읽으면 None(아직 쓰는 중 → 다음 번에)."""
    try:
        return 읽기_엄격(경로)
    except (OSError, ValueError):
        return None


def 원자적_쓰기(경로: Path, 데이터) -> bool:
    임시 = 경로.with_name(f".{경로.name}.{os.getpid()}.tmp")
    with open(임시, "w", encoding="utf-8", newline="\n") as f:
        json.dump(데이터, f, ensure_ascii=False, indent=2)
    for 번 in range(40):  # Windows: 화면 서버가 잠깐 읽는 중이면 바꿔 끼우기 실패 → 백오프로 다시
        try:
            os.replace(임시, 경로)
            return True
        except OSError as e:
            if not 사용중(e):
                break
            time.sleep(0.05 * (번 + 1))
    try:
        임시.unlink()
    except OSError:
        pass
    return False


class 잠금:
    """상태.json 을 서버·Claude(작업함.py)와 동시에 고치지 않게 하는 잠금 파일(도구/_공통.py 와 같은 규칙)."""

    def __init__(self, 경로: Path, 기다림: float = 3.0, 오래됨: float = 15.0):
        self.경로, self.기다림, self.오래됨 = 경로, 기다림, 오래됨
        self.얻음 = False

    def __enter__(self):
        끝 = time.monotonic() + self.기다림
        while time.monotonic() < 끝:
            try:
                fd = os.open(self.경로, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, f"{os.getpid()} 대기".encode())
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
                time.sleep(random.uniform(0.005, 0.03))
        return self  # 못 얻었음(self.얻음=False) → 부르는 쪽이 이번 신호를 건너뜀

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


def 신호보내기(작업함: Path) -> bool:
    """연결 신호 한 번. 잠금을 못 얻거나 상태.json 을 못 읽으면 이번은 건너뜀(3초 뒤 다시) —
    잠깐 못 읽었다고 빈 상태로 덮어써서 진행·알림이 사라지는 일이 없게."""
    파일 = 작업함 / "상태.json"
    with 잠금(작업함 / ".상태.lock") as 잠:
        if not 잠.얻음:
            return False
        try:
            상태 = 읽기_엄격(파일)
        except FileNotFoundError:
            상태 = {}
        except ValueError:  # 깨진 상태.json(직접 고친 경우 등) → 남겨 두고 새로
            try:
                shutil.copy2(파일, 파일.with_name("상태.json.깨짐"))
            except OSError:
                pass
            상태 = {}
        except OSError:
            return False
        if not isinstance(상태, dict):
            상태 = {}
        연결 = 상태.get("연결") if isinstance(상태.get("연결"), dict) else {}
        연결["마지막신호"] = 지금()
        연결["대기pid"] = os.getpid()
        상태["연결"] = 연결
        상태.setdefault("진행", [])
        상태.setdefault("알림", [])
        return 원자적_쓰기(파일, 상태)


def 주인쓰기(주인파일: Path):
    for 번 in range(20):  # 두 대기.py 가 동시에 켜질 때 Windows 에서 잠깐 사용 중일 수 있음
        try:
            주인파일.write_text(str(os.getpid()), encoding="utf-8")
            return
        except OSError as e:
            if not 사용중(e):
                raise
            time.sleep(0.02 * (번 + 1))


def 쌓인것(작업함: Path) -> dict:
    완료 = {f.name for f in (작업함 / "처리완료").glob("*.json")}
    결과 = {"요청": [], "답변": []}
    for 종류 in ("요청", "답변"):
        for f in sorted((작업함 / 종류).glob("*.json")):
            if f.name.startswith(".") or f.name in 완료:
                continue  # 쓰는 중인 임시 파일, 이미 처리한 파일
            내용 = 읽기_json(f)
            if 내용 is None:
                continue  # 아직 쓰는 중 → 다음 번에
            항목 = {"파일": f"{종류}/{f.name}", "내용": 내용}
            if 종류 == "답변":  # 어떤 질문의 답인지 함께 보여 주기
                qid = 내용.get("질문id") if isinstance(내용, dict) else None
                q = 읽기_json(작업함 / "질문" / f"{qid or f.stem}.json")
                if q is not None:
                    항목["질문"] = q
            결과[종류].append(항목)
    return 결과


def 출력(데이터: dict):
    print(json.dumps(데이터, ensure_ascii=False), flush=True)


def 로그(스튜디오: Path, 메시지: str):
    """로그/오늘.log 에 한 줄(규약 v2 1절). 실패해도 대기는 계속."""
    try:
        폴더 = 스튜디오 / "로그"
        폴더.mkdir(parents=True, exist_ok=True)
        with 잠금(폴더 / ".로그.lock", 기다림=30, 오래됨=60) as 잠긴것:  # 서버·도구와 같은 잠금 → 줄 번호(#L…)가 어긋나지 않게
            if not 잠긴것.얻음:  # 잠금 없이 쓰면 글자가 깨질 수 있음 → 이 줄은 버림
                return
            with open(폴더 / f"{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8", newline="\n") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [정보] [대기] {메시지}\n")
    except OSError:
        pass


def 요약(쌓임: dict) -> str:
    조각 = [f"요청 {x['내용'].get('종류', '?')}({x['파일']})" for x in 쌓임["요청"] if isinstance(x.get("내용"), dict)]
    조각 += [f"답변 {x['파일']}" for x in 쌓임["답변"]]
    return ", ".join(조각)[:500]


def main() -> int:
    ap = argparse.ArgumentParser(description="여행 스튜디오 작업함 기다리기")
    ap.add_argument("--폴더", help="여행스튜디오 폴더(기본: 이 파일의 위 폴더)")
    ap.add_argument("--간격", type=float, default=3.0, help="확인 간격(초)")
    ap.add_argument("--최대분", type=float, default=50.0, help="이 시간 동안 아무 일이 없으면 끝냄(분)")
    ap.add_argument("--한번", action="store_true", help="기다리지 않고 지금 쌓인 것만 확인")
    a = ap.parse_args()

    스튜디오 = Path(a.폴더).resolve() if a.폴더 else Path(__file__).resolve().parent.parent
    작업함 = 스튜디오 / "작업함"
    for 이름 in ("요청", "질문", "답변", "처리완료"):
        (작업함 / 이름).mkdir(parents=True, exist_ok=True)

    if a.한번:  # 연결 신호는 남기지 않음(지켜보는 것이 아니므로 화면에 '연결됨'이 잠깐 떴다 사라지지 않게)
        쌓임 = 쌓인것(작업함)
        출력({"종류": "새작업", **쌓임} if 쌓임["요청"] or 쌓임["답변"] else {"종류": "없음"})
        return 0

    # 대기.py 는 한 번에 하나만: 새로 켜진 쪽이 주인이 되고, 예전 것은 알아서 물러남
    주인파일 = 작업함 / "대기.pid"
    주인쓰기(주인파일)
    로그(스튜디오, f"기다리기 시작(pid {os.getpid()})")
    끝시각 = time.monotonic() + a.최대분 * 60
    print(f"[대기] 작업함을 지켜보는 중… ({a.간격:g}초마다 확인, 최대 {a.최대분:g}분)", file=sys.stderr, flush=True)
    while True:
        try:
            if 주인파일.read_text(encoding="utf-8").strip() != str(os.getpid()):
                로그(스튜디오, f"새 대기.py 가 켜져 물러남(pid {os.getpid()})")
                출력({"종류": "교대"})
                return 0
        except OSError:
            pass
        신호보내기(작업함)
        쌓임 = 쌓인것(작업함)
        if 쌓임["요청"] or 쌓임["답변"]:
            로그(스튜디오, f"새 작업 → Claude 깨움: {요약(쌓임)}")
            출력({"종류": "새작업", **쌓임})
            return 0
        if time.monotonic() >= 끝시각:
            로그(스튜디오, f"{a.최대분:g}분 동안 일이 없어 끝냄(시간초과) — Claude가 다시 켬")
            출력({"종류": "시간초과"})
            return 0
        time.sleep(a.간격)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
