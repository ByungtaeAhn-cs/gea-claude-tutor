# -*- coding: utf-8 -*-
"""바탕화면에 '여행 스튜디오' 아이콘을 만듭니다. 더블클릭하면 스튜디오가 열립니다.

- Windows: 바탕화면에 '여행 스튜디오.lnk'(바로가기)
    대상 = pythonw.exe + 스튜디오실행.pyw, 아이콘 = 아이콘/studio.ico, 시작 위치 = 이 폴더
    (바탕화면이 OneDrive 로 옮겨진 PC도 Windows 가 알려 주는 진짜 바탕화면 위치를 찾아 씁니다)
- Mac: 바탕화면에 '여행 스튜디오.command'(이 폴더 경로가 들어간 사본) + 실행 권한(chmod +x)
    ※ Mac 실기에서는 아직 확인하지 못했습니다(실기 미확인).

사용:  python 바탕화면아이콘만들기.py
       python 바탕화면아이콘만들기.py --대상 <폴더>    바탕화면 대신 다른 폴더에 만들기(시험용)
마지막 줄에 JSON 요약을 출력합니다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

폴더 = Path(__file__).resolve().parent
이름 = "여행 스튜디오"


def 윈도우_바탕화면() -> Path:
    """셸 특수 폴더(Known Folder: Desktop) 경로 → OneDrive 로 옮겨진 바탕화면도 정확히."""
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")  # FOLDERID_Desktop
        g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        경로 = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(경로)) == 0:
            결과 = 경로.value
            ctypes.windll.ole32.CoTaskMemFree(경로)
            if 결과 and Path(결과).is_dir():
                return Path(결과)
    except Exception:
        pass
    try:  # 두 번째 방법: PowerShell 에 묻기
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Environment]::GetFolderPath('Desktop')"],
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.stdout.strip() and Path(r.stdout.strip()).is_dir():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return Path.home() / "Desktop"


def 창없는_파이썬() -> Path:
    """콘솔 창이 뜨지 않는 pythonw.exe 찾기(가상환경이면 원래 파이썬 쪽)."""
    후보 = []
    for exe in (getattr(sys, "_base_executable", None), sys.executable):
        if exe:
            후보.append(Path(exe).with_name("pythonw.exe"))
    for 이름들 in ("pythonw", "pyw"):
        w = shutil.which(이름들)
        if w:
            후보.append(Path(w))
    후보.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "pyw.exe")
    for p in 후보:
        if p.is_file():
            return p
    return Path(sys.executable)  # 마지막 수단(검은 창이 잠깐 보일 수 있음)


def 윈도우_바로가기(대상폴더: Path) -> dict:
    lnk = 대상폴더 / f"{이름}.lnk"
    파이썬 = 창없는_파이썬()
    스크립트 = 폴더 / "스튜디오실행.pyw"
    아이콘 = 폴더 / "아이콘" / "studio.ico"
    환경 = dict(os.environ,
              LNK_PATH=str(lnk), LNK_TARGET=str(파이썬), LNK_ARGS=f'"{스크립트}"',
              LNK_DIR=str(폴더), LNK_ICON=f"{아이콘},0", LNK_DESC="여행 사진으로 블로그 여행기 만들기")
    # 경로(한글·띄어쓰기)는 환경 변수로 넘겨 따옴표 문제를 피함
    명령 = ("$ws = New-Object -ComObject WScript.Shell; "
          "$s = $ws.CreateShortcut($env:LNK_PATH); "
          "$s.TargetPath = $env:LNK_TARGET; $s.Arguments = $env:LNK_ARGS; "
          "$s.WorkingDirectory = $env:LNK_DIR; $s.IconLocation = $env:LNK_ICON; "
          "$s.Description = $env:LNK_DESC; $s.WindowStyle = 1; $s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", 명령],
                       capture_output=True, text=True, timeout=60, env=환경)
    if r.returncode != 0 or not lnk.is_file():
        raise SystemExit(f"바로가기를 만들지 못했어요: {r.stderr.strip()}")
    return {"만든것": str(lnk), "대상": str(파이썬), "인자": str(스크립트), "아이콘": str(아이콘), "시작위치": str(폴더)}


def 맥_실행파일(대상폴더: Path) -> dict:
    원본 = (폴더 / "스튜디오실행.command").read_text(encoding="utf-8")
    경로 = str(폴더)
    for 글자 in '\\"$`':  # bash 큰따옴표 안에서 특별한 뜻이 있는 글자는 그대로 쓰이게
        경로 = 경로.replace(글자, "\\" + 글자)
    사본글 = 원본.replace('STUDIO_DIR="${STUDIO_DIR:-$(cd "$(dirname "$0")" && pwd)}"', f'STUDIO_DIR="{경로}"', 1)
    사본 = 대상폴더 / f"{이름}.command"
    사본.write_text(사본글, encoding="utf-8", newline="\n")
    사본.chmod(사본.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    아이콘됨 = False
    if sys.platform == "darwin":  # 아이콘 입히기(되면 좋고, 안 돼도 실행에는 지장 없음)
        png = 폴더 / "아이콘" / "studio_512.png"
        jxa = ("ObjC.import('AppKit');"
               f"var img=$.NSImage.alloc.initWithContentsOfFile({json.dumps(str(png))});"
               f"$.NSWorkspace.sharedWorkspace.setIconForFileOptions(img,{json.dumps(str(사본))},0);")
        try:
            아이콘됨 = subprocess.run(["osascript", "-l", "JavaScript", "-e", jxa], capture_output=True, timeout=30).returncode == 0
        except Exception:
            pass
    return {"만든것": str(사본), "실행권한": True, "아이콘": 아이콘됨}


def main() -> int:
    ap = argparse.ArgumentParser(description="바탕화면에 여행 스튜디오 아이콘 만들기")
    ap.add_argument("--대상", help="바탕화면 대신 이 폴더에 만들기(시험용)")
    a = ap.parse_args()
    if a.대상:
        대상폴더 = Path(a.대상).expanduser().resolve()
        대상폴더.mkdir(parents=True, exist_ok=True)
    else:
        대상폴더 = 윈도우_바탕화면() if os.name == "nt" else Path.home() / "Desktop"
    if not 대상폴더.is_dir():
        raise SystemExit(f"폴더를 찾지 못했어요: {대상폴더}")
    결과 = 윈도우_바로가기(대상폴더) if os.name == "nt" else 맥_실행파일(대상폴더)
    print(f"'{이름}' 아이콘을 만들었어요: {결과['만든것']}")
    print(json.dumps(결과, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
