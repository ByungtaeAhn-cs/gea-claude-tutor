# -*- coding: utf-8 -*-
"""작업이력.py — 블로그 글 한 편의 제작 단계를 기록하고, 실패하면 그 단계부터 다시 하게 돕습니다.

표준 라이브러리만 씁니다. Windows·Mac 공용. 형식: 규약 v2 2.6(`작업이력.json`).

단계(기본 순서)
  자료조사 → 초안 → 팩트체크 → 다듬기 → 이미지 → 미리보기 → 패키지 → 임시저장

사용 예 (글 폴더 = 글 한 편의 폴더, 예: 글/2026-10-07_헤켈배아)
  python 작업이력.py 시작 --폴더 글/2026-10-07_헤켈배아 --편ID 헤켈배아
  python 작업이력.py 단계 --폴더 … --이름 자료조사 --상태 진행중
  python 작업이력.py 단계 --폴더 … --이름 자료조사 --상태 완료 --산출물 자료조사_헤켈배아.md
  python 작업이력.py 단계 --폴더 … --이름 미리보기 --상태 실패 --오류 "템플릿.html 없음"
  python 작업이력.py 이어하기 --폴더 …      ← 어느 단계부터 다시 할지 + 다시 쓸 산출물
  python 작업이력.py 처음부터 --폴더 …      ← 지금까지 산출물을 보관/ 으로 옮기고 새 작업
  python 작업이력.py 보기 --폴더 …

규칙
  - 단계가 끝날 때마다 산출물(파일 이름, 글 폴더 기준)을 적습니다. 다음에 이어 할 때 그 파일을 다시 씁니다(토큰 절약).
  - 실패하면 작업 상태가 '실패'가 되고, 그 자리에서 멈춥니다. 고친 뒤 '이어하기'로 그 단계부터.
  - 고치느라 **앞 단계의 산출물**을 바꿨다면(예: 패키지 실패를 고치려고 원고를 고침) 그 뒤 단계도 다시 합니다:
    바꾼 단계 다음부터 `단계 --이름 <단계> --상태 진행중`으로 다시 기록하며 진행(예: 원고 수정 → 미리보기부터).
  - 모든 기록은 로그 폴더의 `YYYY-MM-DD.log`에도 한 줄씩 남습니다(기본: CLAUDE.md가 있는 프로젝트의 `로그/`).
마지막 줄에 JSON 요약을 출력합니다.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

STEPS = ["자료조사", "초안", "팩트체크", "다듬기", "이미지", "미리보기", "패키지", "임시저장"]
FILE = "작업이력.json"
REPAIR = ("로그/{날짜}.log의 마지막 오류를 분석해서 원인을 찾고 고친 다음, "
          "작업이력.py 이어하기로 '{단계}' 단계부터 다시 실행해줘. 앞 단계 산출물은 다시 만들지 마.")


def now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log_dir_for(folder: Path, given: str | None) -> Path:
    if given:
        return Path(given)
    for up in [folder, *folder.parents]:
        if (up / "CLAUDE.md").is_file():
            return up / "로그"
    return folder / "로그"


class Lock:
    """같은 파일을 두 프로그램이 동시에 고치지 않게 하는 간단한 잠금."""
    def __init__(self, folder: Path):
        self.p = folder / ".작업이력.lock"

    def __enter__(self):
        for _ in range(50):
            try:
                fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() - self.p.stat().st_mtime > 60:  # 오래된 잠금은 버림
                    self.p.unlink(missing_ok=True)
                time.sleep(0.1)
        raise SystemExit("작업이력 잠금을 얻지 못했습니다(다른 작업이 기록 중). 잠시 뒤 다시 하세요.")

    def __exit__(self, *a):
        self.p.unlink(missing_ok=True)


def load(folder: Path) -> list:
    p = folder / FILE
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save(folder: Path, data: list):
    tmp = folder / (FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, folder / FILE)  # 원자적 교체


def write_log(ldir: Path, pid: str, step: str, state: str, msg: str) -> str:
    ldir.mkdir(parents=True, exist_ok=True)
    day = _dt.date.today().isoformat()
    lp = ldir / f"{day}.log"
    n = 1
    if lp.exists():
        with open(lp, encoding="utf-8") as f:
            n = sum(1 for _ in f) + 1
    with open(lp, "a", encoding="utf-8") as f:
        f.write(f"{now()} [{pid}] {step} {state}: {msg}\n")
    return f"{ldir.name}/{day}.log#L{n}"


def latest(data: list) -> dict | None:
    return data[-1] if data else None


def cmd_start(a, folder: Path, ldir: Path):
    with Lock(folder):
        data = load(folder)
        t = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        job = {"작업ID": f"t{t}_{a.kind}_{a.pid}", "종류": a.kind, "편ID": a.pid, "상태": "진행중",
               "단계": [{"이름": s, "상태": "대기"} for s in (a.steps or STEPS)],
               "재시도": "가능", "시작": now(), "끝": ""}
        data.append(job)
        save(folder, data)
    ref = write_log(ldir, a.pid, "작업", "시작", job["작업ID"])
    return {"작업ID": job["작업ID"], "단계": [s["이름"] for s in job["단계"]], "로그": ref}


def cmd_step(a, folder: Path, ldir: Path):
    with Lock(folder):
        data = load(folder)
        job = latest(data)
        if not job:
            raise SystemExit("작업이 없습니다. 먼저 '시작'을 하세요.")
        step = next((s for s in job["단계"] if s["이름"] == a.name), None)
        if not step:
            step = {"이름": a.name, "상태": "대기"}
            job["단계"].append(step)
        step["상태"] = a.state
        step["갱신"] = now()
        if a.outputs:
            step["산출물"] = a.outputs if len(a.outputs) > 1 else a.outputs[0]
        msg = a.error or a.memo or ", ".join(a.outputs or [])
        ref = write_log(ldir, job["편ID"], a.name, a.state, msg)
        if a.state == "실패":
            step["오류"] = a.error or "(오류 내용 없음)"
            step["로그"] = ref
            job["상태"] = "실패"
            job["재시도"] = f"불가({a.no_retry})" if a.no_retry else "가능"
        elif a.state in ("완료", "건너뜀"):
            step.pop("오류", None)
            if all(s["상태"] in ("완료", "건너뜀") for s in job["단계"]):
                job["상태"], job["끝"] = "완료", now()
            elif job["상태"] in ("실패", "멈춤"):
                job["상태"] = "진행중"
        elif a.state == "멈춤":
            job["상태"] = "멈춤"
        else:
            job["상태"] = "진행중"
        save(folder, data)
    out = {"작업ID": job["작업ID"], "단계": a.name, "상태": a.state, "작업상태": job["상태"], "로그": ref}
    if a.state == "실패":
        out["수리프롬프트"] = REPAIR.format(날짜=_dt.date.today().isoformat(), 단계=a.name)
    return out


def outputs_of(step: dict) -> list:
    o = step.get("산출물")
    return o if isinstance(o, list) else ([o] if o else [])


def cmd_resume(a, folder: Path, ldir: Path):
    job = latest(load(folder))
    if not job:
        return {"결과": "작업 없음", "다음": "시작"}
    if job["상태"] == "완료":
        return {"작업ID": job["작업ID"], "결과": "모두 완료"}
    if str(job.get("재시도", "가능")).startswith("불가"):
        return {"작업ID": job["작업ID"], "결과": job["재시도"], "다음": "처음부터 또는 사람 판단"}
    reuse, start_at, missing = [], None, []
    for s in job["단계"]:
        if s["상태"] in ("완료", "건너뜀") and start_at is None:
            outs = outputs_of(s)
            lost = [o for o in outs if not (folder / o).exists()]
            if lost:  # 산출물이 사라졌으면 그 단계부터 다시
                missing += lost
                start_at = s["이름"]
            else:
                reuse += outs
        elif start_at is None:
            start_at = s["이름"]
    write_log(ldir, job["편ID"], start_at or "-", "이어하기", f"재사용 {len(reuse)}개")
    return {"작업ID": job["작업ID"], "다시시작단계": start_at, "재사용산출물": reuse, "사라진산출물": missing,
            "직전오류": next((s.get("오류") for s in job["단계"] if s["상태"] == "실패"), None)}


def cmd_restart(a, folder: Path, ldir: Path):
    job = latest(load(folder))
    moved = []
    if job:
        dest = folder / "보관" / _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        for s in job["단계"]:
            for o in outputs_of(s):
                src = folder / o
                if src.exists():
                    (dest / o).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dest / o))
                    moved.append(o)
    a.pid = a.pid or (job["편ID"] if job else folder.name)
    a.kind = a.kind or (job["종류"] if job else "글쓰기")
    started = cmd_start(a, folder, ldir)
    started["보관한산출물"] = moved
    return started


def cmd_show(a, folder: Path, ldir: Path):
    data = load(folder)
    for job in data[-3:]:
        print(f"■ {job['작업ID']}  상태: {job['상태']}  재시도: {job.get('재시도', '')}")
        for s in job["단계"]:
            extra = f" — {s.get('오류')}" if s.get("오류") else (f" → {', '.join(outputs_of(s))}" if outputs_of(s) else "")
            print(f"   {s['이름']:<6} {s['상태']}{extra}")
    j = latest(data)
    return {"작업수": len(data), "최근": j["작업ID"] if j else None, "최근상태": j["상태"] if j else None}


def main():
    ap = argparse.ArgumentParser(description="글 한 편의 제작 단계 기록·이어하기")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--폴더", "--folder", dest="folder", required=True, help="글 한 편의 폴더")
    common.add_argument("--로그폴더", "--logdir", dest="logdir", default=None)
    s = sub.add_parser("시작", parents=[common])
    s.add_argument("--편ID", "--id", dest="pid", required=True)
    s.add_argument("--종류", "--kind", dest="kind", default="글쓰기")
    s.add_argument("--단계목록", "--steps", dest="steps", nargs="*", default=None)
    st = sub.add_parser("단계", parents=[common])
    st.add_argument("--이름", "--name", dest="name", required=True)
    st.add_argument("--상태", "--state", dest="state", required=True, choices=["진행중", "완료", "실패", "건너뜀", "멈춤"])
    st.add_argument("--산출물", "--outputs", dest="outputs", nargs="*", default=None)
    st.add_argument("--오류", "--error", dest="error", default="")
    st.add_argument("--메모", "--memo", dest="memo", default="")
    st.add_argument("--재시도불가", "--no-retry", dest="no_retry", default="")
    sub.add_parser("이어하기", parents=[common])
    r = sub.add_parser("처음부터", parents=[common])
    r.add_argument("--편ID", "--id", dest="pid", default=None)
    r.add_argument("--종류", "--kind", dest="kind", default=None)
    r.add_argument("--단계목록", "--steps", dest="steps", nargs="*", default=None)
    sub.add_parser("보기", parents=[common])
    a = ap.parse_args()
    folder = Path(a.folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    ldir = log_dir_for(folder, a.logdir)
    fn = {"시작": cmd_start, "단계": cmd_step, "이어하기": cmd_resume, "처음부터": cmd_restart, "보기": cmd_show}[a.cmd]
    print(json.dumps(fn(a, folder, ldir), ensure_ascii=False))


if __name__ == "__main__":
    main()
