# -*- coding: utf-8 -*-
"""여행 스튜디오 실행 — 더블클릭하면 서버를 켜고 브라우저로 화면을 엽니다.

- 서버가 이미 켜져 있으면 브라우저만 엽니다.
- Windows: .pyw 파일은 pythonw 로 열려서 검은 창(콘솔)이 뜨지 않습니다.
- Mac: '스튜디오실행.command' 가 이 파일을 python3 로 실행합니다.
- 서버 기록: 서버/서버기록.log (안 켜질 때 여기를 보거나 Claude에게 보여 주세요)

옵션: --브라우저안열기   서버만 켜기(Claude가 스튜디오에 연결할 때 씀)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote

for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

폴더 = Path(__file__).resolve().parent
서버파일 = 폴더 / "서버" / "server.py"
기록파일 = 폴더 / "서버" / "서버기록.log"
포트 = 8765
주소 = f"http://localhost:{포트}/"


def 알리기(글: str):
    """콘솔이 없을 수 있으므로 Windows 는 메시지 창으로."""
    if sys.stdout is not None:
        print(글)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 글, "여행 스튜디오", 0x40)
        except Exception:
            pass


def 켜져있나() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{포트}{quote('/api/상태')}", timeout=1.5) as r:
            return "연결" in json.loads(r.read().decode("utf-8"))
    except Exception:
        return False


def 서버켜기():
    exe = Path(getattr(sys, "_base_executable", None) or sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")  # 콘솔 창 없이
    if 기록파일.is_file() and 기록파일.stat().st_size > 1_000_000:
        기록파일.unlink()  # 너무 커지면 새로 시작
    기록 = open(기록파일, "a", encoding="utf-8")
    기록.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} 서버 시작 ===\n")
    기록.flush()
    공통 = dict(cwd=str(폴더), stdin=subprocess.DEVNULL, stdout=기록, stderr=기록, close_fds=True)
    if os.name == "nt":
        흐름 = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen([str(exe), "-X", "utf8", str(서버파일)], creationflags=흐름, **공통)
    else:
        subprocess.Popen([str(exe), "-X", "utf8", str(서버파일)], start_new_session=True, **공통)  # 터미널을 닫아도 계속
    기록.close()


def main() -> int:
    브라우저 = "--브라우저안열기" not in sys.argv
    if not 켜져있나():
        서버켜기()
        for _ in range(60):  # 최대 15초 기다리기
            time.sleep(0.25)
            if 켜져있나():
                break
        else:
            알리기("여행 스튜디오 서버를 켜지 못했어요.\n"
                 f"'{기록파일}' 를 열어 보거나, Claude에게 '스튜디오 서버가 안 켜져'라고 말해 주세요.\n"
                 f"(다른 프로그램이 {포트}번 포트를 쓰고 있을 수도 있어요)")
            return 1
    if 브라우저:
        webbrowser.open(주소)
    if sys.stdout is not None:
        print(json.dumps({"서버": 주소, "켜짐": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
