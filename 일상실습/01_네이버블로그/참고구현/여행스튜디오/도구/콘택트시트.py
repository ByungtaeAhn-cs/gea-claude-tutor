# -*- coding: utf-8 -*-
"""콘택트시트.py — 사진을 20장씩 번호 격자 한 장으로 모읍니다. Claude는 사진을 한 장씩 열지 않고 이 시트를 봅니다. (규약 4절)

  - 칸마다 큰 번호 + id + 시각 + 기기, 제외 후보는 빨간 테두리, 대표 후보는 노란 테두리, 연사 묶음은 파란 표시
  - 시트마다 번호→id 표(JSON)를 함께 저장 → "7번 흐림" 처럼 답하면 id 로 바꿀 수 있음
  - 시트가 여러 장이면 서브에이전트에 3~4장씩 나눠 보게 하세요(본 대화에 이미지가 쌓이지 않음)

사용
  python 도구/콘택트시트.py --여행 2026-09_제주                  (전체, 시각순)
  python 도구/콘택트시트.py --여행 2026-09_제주 --대상 판단필요   (제외·대표 후보·연사·시각 약함만)
  python 도구/콘택트시트.py --여행 2026-09_제주 --일차 2
  python 도구/콘택트시트.py --여행 2026-09_제주 --id p0021 p0018  (시계 맞추기 쌍처럼 몇 장만 크게)
결과: 작업/콘택트시트/<대상>_01.jpg … + <대상>_목록.json
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import 도구오류, 약한출처, 원자적_쓰기, 인자틀, 실행틀, 한글글꼴, 정렬키  # noqa: E402
import _사진 as 사진  # noqa: E402


def 글꼴(크기: int, 굵게=False):
    from PIL import ImageFont
    p = 한글글꼴(굵게)
    if not p:
        raise 도구오류("한글 글꼴을 찾지 못했어요(시트의 글자가 네모로 깨짐).",
                     힌트="Windows: C:/Windows/Fonts/malgun.ttf, Mac: /System/Library/Fonts/AppleSDGothicNeo.ttc 가 있는지 확인")
    return ImageFont.truetype(p, 크기)


def 시각약함(x: dict, 보정표: dict) -> bool:
    """화면(app.js)과 같은 기준: 약한 출처이되, 시계를 확인한(기기보정초에 있는) 기기의 EXIF 는 약하지 않음."""
    return x.get("시각출처") in 약한출처 and not (x.get("시각출처") == "EXIF" and x.get("기기") in 보정표)


def 시트그리기(항목들: list[dict], 여행: Path, 시작번호: int, 칸, 열: int, 제목: str, 보정표: dict):
    from PIL import Image, ImageDraw
    cw, ch = 칸
    줄 = math.ceil(len(항목들) / 열)
    머리 = 56
    시트 = Image.new("RGB", (cw * 열, 머리 + ch * 줄), (245, 245, 245))
    d = ImageDraw.Draw(시트)
    d.text((16, 12), 제목, font=글꼴(26, True), fill=(30, 30, 30))
    큰 = 글꼴(max(28, cw // 9), True)
    작은 = 글꼴(max(15, cw // 26))
    번호표 = {}
    for k, x in enumerate(항목들):
        번호 = 시작번호 + k
        번호표[str(번호)] = x["id"]
        cx, cy = (k % 열) * cw, 머리 + (k // 열) * ch
        글줄 = 34 if cw >= 300 else 28
        상자 = (cx + 6, cy + 6, cx + cw - 6, cy + ch - 6 - 글줄)
        p = 여행 / str(x.get("썸네일") if cw <= 420 else x.get("미리보기") or x.get("썸네일") or "")
        if not p.is_file():
            p = 여행 / str(x.get("미리보기") or "")
        try:
            im = 사진.Image.open(p).convert("RGB")
            im.thumbnail((상자[2] - 상자[0], 상자[3] - 상자[1]), 사진.Image.LANCZOS)
            시트.paste(im, (상자[0] + (상자[2] - 상자[0] - im.width) // 2, 상자[1] + (상자[3] - 상자[1] - im.height) // 2))
        except Exception:
            d.rectangle(상자, outline=(160, 160, 160))
            d.text((상자[0] + 10, 상자[1] + 40), "미리보기 없음", font=작은, fill=(120, 120, 120))
        판 = x.get("판정") or {}
        점 = x.get("점수") or {}
        색 = (220, 30, 30) if 판.get("제외후보") else ((235, 180, 0) if 판.get("대표후보") else None)
        if 색:
            d.rectangle((cx + 3, cy + 3, cx + cw - 4, cy + ch - 4 - 글줄 + 3), outline=색, width=6)
        # 번호(크게, 왼쪽 위)
        d.rounded_rectangle((cx + 10, cy + 10, cx + 10 + 큰.size * (len(str(번호)) * 0.62 + 0.5), cy + 10 + 큰.size * 1.25),
                            radius=8, fill=(0, 0, 0))
        d.text((cx + 10 + 큰.size * 0.25, cy + 12), str(번호), font=큰, fill=(255, 255, 255))
        표식 = []
        if x.get("종류") == "영상":
            초 = x.get("영상길이초") or 0
            표식.append(f"▶ {int(초) // 60}:{int(초) % 60:02d}")
        if 점.get("연사묶음"):
            표식.append(f"연사 {점['연사묶음']}" + (" ★" if 판.get("묶음베스트") else ""))
        if 시각약함(x, 보정표):
            표식.append(f"※시각:{x.get('시각출처')}")
        if 표식:
            t = " · ".join(표식)
            w = d.textlength(t, font=작은)
            d.rectangle((cx + cw - 14 - w, cy + 12, cx + cw - 8, cy + 14 + 작은.size + 6), fill=(20, 70, 160))
            d.text((cx + cw - 11 - w, cy + 14), t, font=작은, fill=(255, 255, 255))
        시각 = str(x.get("촬영시각") or "")[5:16].replace("T", " ")
        아래 = f"{x['id']}  {시각}  {x.get('기기') or ''}"
        d.text((cx + 10, cy + ch - 글줄 - 2), 아래, font=작은, fill=(40, 40, 40))
    return 시트, 번호표


def 본문(실):
    인자 = 실.인자
    사진.준비()
    목록 = [x for x in 실.목록() if not x.get("원본없음")]
    보정표 = 실.정보().get("기기보정초") or {}
    if 인자.id:
        표 = {x["id"]: x for x in 목록}
        없음 = [i for i in 인자.id if i not in 표]
        if 없음:
            raise 도구오류(f"목록에 없는 id: {', '.join(없음)}")
        고른 = [표[i] for i in 인자.id]
        대상 = 인자.이름 or "선택"
    else:
        대상 = 인자.대상
        고른 = sorted(목록, key=정렬키)
        if 인자.일차 is not None:
            고른 = [x for x in 고른 if x.get("일차") == 인자.일차]
        if 인자.사진만:
            고른 = [x for x in 고른 if x.get("종류") == "사진"]
        if 대상 == "판단필요":
            고른 = [x for x in 고른 if (x.get("판정") or {}).get("제외후보") or (x.get("판정") or {}).get("대표후보")
                  or (x.get("점수") or {}).get("연사묶음") or 시각약함(x, 보정표)]
        elif 대상 == "제외후보":
            고른 = [x for x in 고른 if (x.get("판정") or {}).get("제외후보")]
        elif 대상 == "대표후보":
            고른 = [x for x in 고른 if (x.get("판정") or {}).get("대표후보")]
        elif 대상 == "미정":
            고른 = [x for x in 고른 if (x.get("사용자결정") or "미정") == "미정"]
        if 인자.일차 is not None:
            대상 = f"{대상}_{인자.일차}일차"
    if not 고른:
        raise 도구오류("시트에 넣을 사진이 없어요(조건을 확인하세요).")

    폴더 = 실.여행 / "작업" / "콘택트시트"
    with 실.단계("콘택트 시트 그리기") as 기록:
        폴더.mkdir(parents=True, exist_ok=True)
        n = 인자.칸수
        if len(고른) <= 4:          # 몇 장만 비교(시계 쌍 등) → 크게
            열, 칸 = len(고른), (900, 760)
        else:
            열, 칸 = 5, (400, 375)
        시트들 = []
        쪽수 = math.ceil(len(고른) / n)
        for 쪽 in range(쪽수):
            묶음 = 고른[쪽 * n:(쪽 + 1) * n]
            시작 = 쪽 * n + 1
            제목 = f"{실.여행ID} · {대상} · {쪽 + 1}/{쪽수} (번호 {시작}~{시작 + len(묶음) - 1})"
            그림, 번호표 = 시트그리기(묶음, 실.여행, 시작, 칸, min(열, len(묶음)) if len(고른) <= 4 else 열, 제목, 보정표)
            파일 = 폴더 / f"{대상}_{쪽 + 1:02d}.jpg"
            그림.save(파일, "JPEG", quality=85, optimize=True)
            시트들.append({"시트": 실.상대(파일), "크기": list(그림.size), "번호표": 번호표})
        # 지난번에 이 대상으로 만든 시트가 더 많았으면 남은 것은 치움(이 도구가 만든 파일만)
        for 옛 in 폴더.glob(f"{대상}_*.jpg"):
            if 옛.stem.rsplit("_", 1)[-1].isdigit() and int(옛.stem.rsplit("_", 1)[-1]) > 쪽수:
                옛.unlink()
        원자적_쓰기(폴더 / f"{대상}_목록.json", {"대상": 대상, "사진수": len(고른), "시트": 시트들})
        기록["산출물"] = [s["시트"] for s in 시트들]
    나눔 = [[s["시트"] for s in 시트들[k:k + 4]] for k in range(0, len(시트들), 4)]
    return 실.끝({
        "대상": 대상, "사진수": len(고른), "시트수": len(시트들), "시트": 시트들,
        "목록파일": 실.상대(폴더 / f"{대상}_목록.json"),
        "서브에이전트분배": 나눔,
        "안내": "시트를 서브에이전트에 나눠 보게 하고 번호별 판정을 JSON으로 받으세요(사람 이름·관계는 쓰지 않음). "
              "결과는 작업/판정_<번호>.json → 작업함.py 판정 으로 합치기(사용자결정은 사람이).",
    })


def main() -> int:
    ap = 인자틀("사진 20장씩 번호 격자(콘택트 시트) 만들기 — Claude는 이 시트로 사진을 봄",
              "예) python 도구/콘택트시트.py --여행 2026-09_제주 --대상 판단필요")
    ap.add_argument("--대상", default="전체", choices=["전체", "판단필요", "제외후보", "대표후보", "미정"])
    ap.add_argument("--일차", type=int, help="이 일차만")
    ap.add_argument("--id", nargs="+", help="이 id 들만(예: 시계 맞추기 쌍)")
    ap.add_argument("--이름", help="--id 로 만들 때 파일 이름 앞부분(기본 '선택')")
    ap.add_argument("--칸수", type=int, default=20, help="시트 한 장의 칸 수(기본 20)")
    ap.add_argument("--사진만", action="store_true", help="영상은 빼기")
    return 실행틀("콘택트시트", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
