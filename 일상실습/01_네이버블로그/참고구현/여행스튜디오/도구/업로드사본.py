# -*- coding: utf-8 -*-
"""업로드사본.py — 블로그에 올릴 사본을 만듭니다(원본은 그대로). (규약 2.5)

사진: EXIF 회전 반영 → sRGB → 장변 2048px(작으면 그대로) → JPG 품질 85 → GPS·기기 정보 등 메타데이터 없이 저장
      (Pillow 로 픽셀만 다시 인코딩 — 모션 포토 MP4 꼬리·MPF 보조 그림·PNG eXIf/iTXt·WebP EXIF/XMP 가 따라오지 않음)
      → 저장한 파일을 **다시 읽어** GPS·기기·EXIF·XMP·IPTC·주석·MPF·꼬리·여러그림이 하나라도 남으면 실패(올리지 않음)
      → 작업/업로드사본/<id>.jpg
      10MB 를 넘으면 품질을 낮춰 다시(네이버 권장 장당 10MB 이하)
영상: FFmpeg 로 다시 인코딩(H.264·AAC, 1080p 이하, -map_metadata -1) → 위치·기기·생성 시각 태그가 없는지 다시 읽어 확인
      → 작업/업로드사본/<id>.mp4 (영상은 네이버 에디터의 '동영상' 버튼으로 사람이 올림)

어떤 사진을?  --편 1일차 (원고/배치_1일차.json 에 들어간 사진·영상)  /  --id p0001 p0002  /
              아무것도 안 주면 화면에서 '사용'·'대표'로 고른 사진 전부
사용  python 도구/업로드사본.py --여행 2026-09_제주 --편 1일차
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import 도구오류, 인자틀, 읽기_json, 실행, 실행틀, 필요, ffmpeg경로  # noqa: E402
import _사진 as 사진  # noqa: E402

장변 = 2048
품질들 = (85, 80, 75, 68, 60)
최대바이트 = 10 * 1024 * 1024


def 사진사본(원본: Path, 대상: Path, 다시: bool = False) -> dict:
    if not 다시 and 대상.is_file() and 대상.stat().st_mtime >= 원본.stat().st_mtime:
        점검 = 사진.메타점검(대상)
        if not any(점검.values()):
            return {"상태": "그대로", "크기": 대상.stat().st_size, "점검": 점검}
    im = 사진.열기(원본)                      # 회전 반영 + sRGB + RGB
    if max(im.size) > 장변:
        im.thumbnail((장변, 장변), 사진.Image.LANCZOS)
    im.info = {}                              # EXIF·XMP·ICC 등 따라오는 정보 비우기(새 파일에 쓰지 않음)
    대상.parent.mkdir(parents=True, exist_ok=True)
    임시 = 대상.with_name(f".{대상.name}.{os.getpid()}.tmp.jpg")
    for q in 품질들:
        im.save(임시, "JPEG", quality=q, optimize=True)
        if 임시.stat().st_size <= 최대바이트:
            break
    os.replace(임시, 대상)
    점검 = 사진.메타점검(대상)                # 다시 읽어 확인
    return {"상태": "만듦", "크기": 대상.stat().st_size, "품질": q, "가로세로": list(im.size), "점검": 점검}


def 영상점검(경로: Path) -> dict:
    av = 필요("av")
    with av.open(str(경로)) as c:
        태그 = {str(k).lower(): str(v) for k, v in (c.metadata or {}).items()}
        for s in c.streams:
            for k, v in (s.metadata or {}).items():
                태그[f"stream:{str(k).lower()}"] = str(v)
    남음 = {k: v for k, v in 태그.items()
          if any(w in k for w in ("location", "gps", "xyz", "make", "model", "creation", "apple", "android", "date"))}
    return {"GPS": any(w in k for k in 남음 for w in ("location", "gps", "xyz")), "기기": any("make" in k or "model" in k for k in 남음),
            "남은태그": 남음}


def 영상사본(원본: Path, 대상: Path, 다시: bool = False) -> dict:
    if not 다시 and 대상.is_file() and 대상.stat().st_mtime >= 원본.stat().st_mtime:
        점검 = 영상점검(대상)
        if not 점검["GPS"] and not 점검["기기"] and not 점검["남은태그"]:
            return {"상태": "그대로", "크기": 대상.stat().st_size, "점검": 점검}
    ff = ffmpeg경로()
    대상.parent.mkdir(parents=True, exist_ok=True)
    임시 = 대상.with_name(f".{대상.stem}.{os.getpid()}.tmp.mp4")
    명령 = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(원본),
          "-map", "0:v:0", "-map", "0:a:0?",
          "-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p",
          "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "128k",
          "-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1", "-map_chapters", "-1",
          "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
          "-movflags", "+faststart", str(임시)]
    r = 실행(명령, 시간제한=3600)
    if r.returncode != 0:
        try:
            임시.unlink()
        except OSError:
            pass
        raise 도구오류(f"영상 사본을 만들지 못했어요({원본.name}): {r.stderr.strip()[-400:]}")
    os.replace(임시, 대상)
    return {"상태": "만듦", "크기": 대상.stat().st_size, "점검": 영상점검(대상)}


def 남은것(점검: dict) -> list[str]:
    """점검 결과에서 하나라도 남았으면 그 이름들(빈 목록이면 깨끗함). 사진·영상 공통, fail-closed."""
    return [k for k, v in (점검 or {}).items() if v]


def 대상고르기(실, 목록: list[dict]) -> tuple[list[dict], str]:
    인자 = 실.인자
    표 = {x["id"]: x for x in 목록}
    if 인자.편:
        배치 = 읽기_json(실.여행 / "원고" / f"배치_{인자.편}.json")
        if not isinstance(배치, dict):
            raise 도구오류(f"원고/배치_{인자.편}.json 을 읽지 못했어요.")
        ids = []
        for b in 배치.get("블록") or []:
            if isinstance(b, dict) and b.get("종류") in ("사진", "그룹사진"):
                ids += [i for i in (b.get("사진") or []) if isinstance(i, str)]
            elif isinstance(b, dict) and b.get("종류") == "영상" and isinstance(b.get("영상"), str):
                ids.append(b["영상"])
        없음 = [i for i in ids if i not in 표]
        if 없음:
            raise 도구오류(f"배치에 목록에 없는 id 가 있어요: {', '.join(없음)}")
        return [표[i] for i in dict.fromkeys(ids)], f"배치_{인자.편}"
    if 인자.id:
        없음 = [i for i in 인자.id if i not in 표]
        if 없음:
            raise 도구오류(f"목록에 없는 id: {', '.join(없음)}")
        return [표[i] for i in 인자.id], "지정"
    고른 = [x for x in 목록 if x.get("사용자결정") in ("사용", "대표")]
    if not 고른:
        raise 도구오류("화면에서 '사용'·'대표'로 고른 사진이 없어요.", 힌트="--편 1일차 또는 --id 로 알려 주세요.")
    return 고른, "사용·대표"


def 만들기(실, 항목들: list[dict], 다시: bool = False) -> list[dict]:
    """발행패키지.py 도 이 함수를 씁니다. → [{id, 종류, 사본(여행 기준 경로), 상태, 크기, 점검, 오류?}]"""
    사진.준비()
    폴더 = 실.여행 / "작업" / "업로드사본"

    def 하나(x):
        원본 = Path(x["원본"])
        try:
            if not 원본.is_file():
                raise 도구오류(f"원본 파일이 없어요: {원본}")
            if x.get("종류") == "영상":
                대상 = 폴더 / f"{x['id']}.mp4"
                r = 영상사본(원본, 대상, 다시)
            else:
                대상 = 폴더 / f"{x['id']}.jpg"
                r = 사진사본(원본, 대상, 다시)
            return {"id": x["id"], "종류": x.get("종류"), "사본": 실.상대(대상), **r}
        except Exception as e:
            return {"id": x["id"], "종류": x.get("종류"), "상태": "실패",
                    "오류": e.메시지 if isinstance(e, 도구오류) else f"{type(e).__name__}: {e}"}
    사진들 = [x for x in 항목들 if x.get("종류") != "영상"]
    영상들 = [x for x in 항목들 if x.get("종류") == "영상"]
    with ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
        결과 = list(ex.map(하나, 사진들))
    결과 += [하나(x) for x in 영상들]  # 영상은 FFmpeg 가 이미 여러 코어를 씀 → 하나씩
    순서 = {x["id"]: k for k, x in enumerate(항목들)}
    return sorted(결과, key=lambda r: 순서[r["id"]])


def 본문(실):
    목록 = [x for x in 실.목록() if not x.get("원본없음")]
    with 실.단계("대상 고르기"):
        항목들, 기준 = 대상고르기(실, 목록)
    with 실.단계("업로드 사본 만들기·다시 읽어 확인") as 기록:
        결과 = 만들기(실, 항목들, 실.인자.다시)
        기록["산출물"] = "작업/업로드사본"
    실패 = [r for r in 결과 if r["상태"] == "실패"]
    남음 = [r for r in 결과 if r["상태"] != "실패" and 남은것(r["점검"])]
    for r in 실패:
        실.로그(f"사본 실패 {r['id']}: {r['오류']}", "오류")
    for r in 남음:
        실.로그(f"메타가 남음 {r['id']}: {r['점검']}", "오류")
    return 실.끝({
        "기준": 기준, "사진": sum(1 for r in 결과 if r.get("종류") != "영상"), "영상": sum(1 for r in 결과 if r.get("종류") == "영상"),
        "새로만듦": sum(1 for r in 결과 if r["상태"] == "만듦"), "그대로": sum(1 for r in 결과 if r["상태"] == "그대로"),
        "합계MB": round(sum(r.get("크기") or 0 for r in 결과) / 1048576, 2),
        "최대MB": round(max((r.get("크기") or 0 for r in 결과), default=0) / 1048576, 2),
        "GPS남음": len([r for r in 남음 if r["점검"].get("GPS")]), "메타남음": len(남음), "실패": 실패,
        "사본": [{k: r.get(k) for k in ("id", "사본", "상태", "크기", "가로세로")} for r in 결과 if r["상태"] != "실패"],
        "확인": "저장한 사본을 다시 읽어 GPS·기기·EXIF·XMP(영상은 위치·기기·생성 시각 태그)가 없는지 확인했어요." if not 남음 else "메타가 남은 사본이 있어요 — 올리지 마세요.",
    }, 성공=not 실패 and not 남음)


def main() -> int:
    ap = 인자틀("블로그 업로드용 사본(회전 반영·2048px·품질 85·GPS·기기 정보 제거, 다시 읽어 확인)",
              "예) python 도구/업로드사본.py --여행 2026-09_제주 --편 1일차")
    ap.add_argument("--편", help="편ID(원고/배치_<편ID>.json 의 사진·영상)")
    ap.add_argument("--id", nargs="+", help="이 id 들만")
    ap.add_argument("--다시", action="store_true", help="이미 있는 사본도 새로 만들기")
    return 실행틀("업로드사본", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
