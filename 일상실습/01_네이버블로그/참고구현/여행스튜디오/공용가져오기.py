# -*- coding: utf-8 -*-
"""공용가져오기.py — 단체 블로그와 함께 쓰는 '공용' 파일을 이 스튜디오의 공용/ 폴더로 복사합니다. (규약 v2 1절)

복사하는 것: 미리보기.py · 템플릿.html(네이버식 미리보기) · 발행서버.py(사진 묶음·발행 작업) ·
            발행묶음_API.md · 발행API.md(있으면)
         + 문서/여행스튜디오_규약.md (교재의 규약 — Claude 가 스튜디오 밖을 뒤지지 않도록 안에 둔 사본)
공용 파일이 바뀌면(교재 업데이트) 스튜디오 화면 위쪽에 '공용 파일 갱신 필요'가 뜹니다.
**사람이** 화면의 [공용 파일 갱신]을 누르거나 이 파일을 직접 실행합니다. Claude 가 실행하지 않습니다
(공용/ 의 코드는 서버가 불러 실행하므로, 원본을 바꿔치기하면 내 PC에서 아무 코드나 돌 수 있음 — 보안 검수 H1).

사용:  python 공용가져오기.py                       (원본을 알아서 찾음: ① 이 폴더 옆의 ../공용
                                                      ② 교재 저장소의 ../../일상실습/01_네이버블로그/참고구현/공용
                                                         — 실습공간/여행스튜디오 에 복사해 쓸 때
                                                      ③ 위쪽 폴더들의 일상실습/01_네이버블로그/참고구현/공용)
       python 공용가져오기.py --원본 <공용 폴더>     (교재 저장소의 참고구현/공용 등 — 이 스튜디오 폴더 안은 안 됨)
       python 공용가져오기.py --확인                 (복사하지 않고 무엇이 다른지만 보기)
마지막 줄에 JSON 요약을 출력합니다. 스튜디오 서버도 이 파일의 함수(원본찾기·비교·복사)를 씁니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
가져올것 = {  # 원본 공용 폴더 안의 위치 → 스튜디오 공용/ 안의 이름
    "미리보기/미리보기.py": "미리보기.py",
    "미리보기/템플릿.html": "템플릿.html",
    "발행서버.py": "발행서버.py",
    "발행묶음_API.md": "발행묶음_API.md",
    "발행API.md": "발행API.md",
}
꼭필요 = {"미리보기.py", "템플릿.html", "발행서버.py"}
규약이름 = "여행스튜디오_규약.md"       # 교재의 01_네이버블로그/ 에 있음 → 스튜디오 문서/ 안으로 복사
규약대상 = "문서/" + 규약이름
교재속공용 = Path("일상실습") / "01_네이버블로그" / "참고구현" / "공용"


class 원본오류(Exception):
    pass


def 원본후보() -> list[Path]:
    """찾아볼 공용 폴더(순서대로). 모두 이 스튜디오 폴더 밖."""
    후보 = [여기.parent / "공용", 여기.parent.parent / 교재속공용]
    후보 += [위 / 교재속공용 for 위 in 여기.parents]
    결과, 본것 = [], set()
    for c in 후보:
        c = c.resolve()
        if str(c) not in 본것 and not 스튜디오안인가(c):
            본것.add(str(c))
            결과.append(c)
    return 결과


def 스튜디오안인가(폴더: Path) -> bool:
    폴더 = Path(폴더).resolve()
    return 폴더 == 여기 or 여기 in 폴더.parents


def 공용폴더인가(폴더: Path) -> bool:
    return 폴더.is_dir() and any((폴더 / 안).is_file() or (폴더 / Path(안).name).is_file() for 안 in 가져올것
                                 if Path(안).name in 꼭필요)


def 원본찾기(원본: str | Path | None = None) -> tuple[Path | None, list[Path]]:
    """(원본 폴더 또는 None, 찾아본 곳). --원본 이 이 스튜디오 폴더 안(여행/·작업함/ 등)이면 원본오류."""
    if 원본:
        p = Path(원본).expanduser().resolve()
        if 스튜디오안인가(p):
            raise 원본오류(f"이 스튜디오 폴더 안({p})은 원본으로 쓸 수 없어요. "
                        "교재 저장소의 '일상실습/01_네이버블로그/참고구현/공용' 만 됩니다.")
        return (p if 공용폴더인가(p) else None), [p]
    찾아본곳 = 원본후보()
    return next((c for c in 찾아본곳 if 공용폴더인가(c)), None), 찾아본곳


def 규약원본(원본: Path) -> Path | None:
    """2026-10-08 실측: Claude 가 '../../여행스튜디오_규약.md'를 찾으려고 스튜디오 밖을 뒤져 승인 창이 여러 번 떴음 →
    규약은 스튜디오 문서/ 안에 복사본을 두고, 이 사본만 읽게 함. 원본은 공용 폴더(…/참고구현/공용) 기준 ../../ ,
    못 찾으면 스튜디오 옆(../../)·위쪽 폴더들의 일상실습/01_네이버블로그/."""
    후보 = [원본.parent.parent / 규약이름, 여기.parent.parent / 규약이름]
    후보 += [위 / "일상실습" / "01_네이버블로그" / 규약이름 for 위 in 여기.parents]
    return next((c for c in 후보 if c.is_file() and not 스튜디오안인가(c.parent)), None)


def _해시(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def 비교(원본: Path) -> dict:
    """{"복사": 바뀔 것, "같음": …, "없음": 원본에 없는 것} — 내용(SHA-256)으로 비교."""
    결과 = {"복사": [], "같음": [], "없음": []}
    for 안, 이름 in 가져올것.items():
        src = 원본 / 안
        if not src.is_file():
            src = 원본 / Path(안).name           # 평평하게 놓인 원본도 받음
        if not src.is_file():
            결과["없음"].append(이름)
            continue
        dst = 여기 / "공용" / 이름
        결과["같음" if dst.is_file() and _해시(src) == _해시(dst) else "복사"].append(이름)
    규약 = 규약원본(원본)  # 없으면 건너뜀(있을 때만 최신으로)
    if 규약:
        dst = 여기 / 규약대상
        결과["같음" if dst.is_file() and _해시(규약) == _해시(dst) else "복사"].append(규약대상)
    return 결과


def 복사(원본: Path) -> dict:
    if 스튜디오안인가(원본):
        raise 원본오류("이 스튜디오 폴더 안은 원본으로 쓸 수 없어요")
    결과 = 비교(원본)
    대상 = 여기 / "공용"
    for 안, 이름 in 가져올것.items():
        if 이름 not in 결과["복사"]:
            continue
        src = 원본 / 안 if (원본 / 안).is_file() else 원본 / Path(안).name
        대상.mkdir(exist_ok=True)
        임시 = 대상 / f".{이름}.가져오는중"
        shutil.copy2(src, 임시)
        임시.replace(대상 / 이름)
    if 규약대상 in 결과["복사"]:
        문서 = 여기 / "문서"
        문서.mkdir(exist_ok=True)
        임시 = 문서 / f".{규약이름}.가져오는중"
        shutil.copy2(규약원본(원본), 임시)
        임시.replace(여기 / 규약대상)
    return 결과


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="공용 파일을 스튜디오 공용/ 으로 복사")
    ap.add_argument("--원본", help="공용 폴더(기본: 알아서 찾음). 이 스튜디오 폴더 안은 안 됨")
    ap.add_argument("--확인", action="store_true", help="복사하지 않고 차이만 보기")
    a = ap.parse_args()
    대상 = 여기 / "공용"
    try:
        원본, 찾아본곳 = 원본찾기(a.원본)
    except 원본오류 as e:
        print(e)
        print(json.dumps({"성공": False, "오류": str(e)}, ensure_ascii=False))
        return 2
    if 원본 is None:
        print("공용 폴더를 찾지 못했어요. 찾아본 곳:")
        for c in 찾아본곳[:3]:
            print(f"  - {c}")
        if len(찾아본곳) > 3:
            print(f"  - (그 위쪽 폴더 {len(찾아본곳) - 3}곳의 일상실습/01_네이버블로그/참고구현/공용)")
        print("교재 저장소(gea-claude-tutor)의 '일상실습/01_네이버블로그/참고구현/공용' 폴더를 --원본 으로 알려 주세요. 예:")
        print('  python 공용가져오기.py --원본 "C:/Users/<이름>/Desktop/gea-claude-tutor/일상실습/01_네이버블로그/참고구현/공용"')
        print("  (Mac: python3 공용가져오기.py --원본 ~/Desktop/gea-claude-tutor/일상실습/01_네이버블로그/참고구현/공용)")
        print(json.dumps({"성공": False, "원본": None, "찾아본곳": [str(c) for c in 찾아본곳[:8]]}, ensure_ascii=False))
        return 1
    print(f"원본: {원본}")
    결과 = 비교(원본) if a.확인 else 복사(원본)
    for 이름 in 결과["복사"]:
        print(("바뀔 것: " if a.확인 else "복사함: ") + 이름)
    for 이름 in 결과["없음"]:
        print(("(없어서 건너뜀 — 꼭 필요) " if 이름 in 꼭필요 else "(없어서 건너뜀) ") + 이름)
    if not 결과["복사"]:
        print("공용/ 이 이미 최신이에요.")
    elif not a.확인:
        print("스튜디오가 켜져 있으면 화면 위쪽 안내대로 [공용 파일 갱신]을 누르거나 스튜디오를 다시 켜면 새 파일을 씁니다.")
    print(json.dumps({"성공": not (꼭필요 & set(결과["없음"])), "원본": str(원본), "대상": str(대상), **결과,
                      "확인만": a.확인}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
