# -*- coding: utf-8 -*-
"""발행패키지.py — 배치(글 한 편) + 업로드 사본 → 발행 패키지. (규약 2.4·2.5, 공용/발행묶음_API.md 6절)

  1. 누수 점검: 원고·배치에 [S1] 같은 출처 표시, '내부용', '발행 금지', '예상 반론', '(추정)', 'TODO' 가 남았으면 **멈춤**
  2. 규칙 점검: 대표 '사진' 블록은 1장씩, '그룹사진'은 한 묶음 10장 이하, '장소'는 5곳 이하, 사람이 '제외'한 사진·숨긴 장소 금지
     지도 블록: 그 지도에 이름이 확인 안 된 장소가 있거나, 지도 그림이 장소.json 보다 오래됐으면(숨김을 바꾼 뒤 안 그림) 멈춤
     (경고만) 카테고리: 패키지는 배치 값 그대로(채우지 않음 — 승인 지문에 들어감). 배치에 없거나 설정.json 의 '카테고리'와
       다르면 경고 · 동영상 블록 '제목' 없음·40자 넘음
  3. 업로드 사본(업로드사본.py 와 같은 방법: 회전·2048px·GPS·기기 정보 제거, 다시 읽어 확인)
  4. 발행/사진묶음_<편ID>/<블록번호>_<photo|collage|slide|single|map>/d<일차>_<블록번호>_<id>.jpg (영문 파일명)
     블록 안에서 합계 10MB 미만이 되게 '업로드묶음' 번호
     영상 블록: 메타를 지운 업로드 사본(mp4)을 <블록번호>_video/ 에 두고 "업로드"(사진과 같은 모양)에 적음
     — 공용 build_bundles 가 '동영상' 묶음으로 만들고 블로그 도우미(v0.3.0~)가 올림(공용/발행API.md v2.1 4.3).
       공용 모듈이 영상을 건너뛰는 옛 판이면 사람이 '동영상' 버튼으로 올림
  5. 발행/패키지_<편ID>.json 저장 → **공용/발행서버.py 의 build_bundles() 로 다시 읽어 검사**(직접 구현하지 않음)
     GPS·기기 정보가 남았거나 10MB·10장 규칙을 어기면 패키지를 내놓지 않음

사용  python 도구/발행패키지.py --여행 2026-09_제주 --편 1일차   [--나누기: 10장 넘는 그룹을 10장씩 자동으로 나눔]
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import (도구오류, 기본스튜디오, 원자적_쓰기, 인자틀, 읽기_json, 실행틀, 지금, 숨긴장소표,  # noqa: E402
                 숨길이름들)
import _사진 as 사진  # noqa: E402
import 업로드사본  # noqa: E402

누수 = [(r"\[S\d+\]", "출처 표시 [S숫자]"), (r"내부용", "'내부용'"), (r"발행\s*금지", "'발행 금지'"),
       (r"예상\s*반론", "'예상 반론'"), (r"\(추정\)", "'(추정)' — 확인 안 된 내용"), (r"\bTODO\b|\bFIXME\b", "TODO"),
       (r"확인\s*필요", "'확인 필요'"), (r"<!--", "HTML 주석")]
방식영문 = {"사진": "photo", "콜라주": "collage", "슬라이드": "slide", "개별 사진": "single", "개별사진": "single", "개별": "single"}
묶음한도 = 10_000_000  # 발행묶음_API.md: Claude in Chrome 업로드 1회 합계 10MB 미만


def 발행서버가져오기():
    for 곳 in (기본스튜디오 / "공용", 기본스튜디오.parent / "공용", Path(__file__).resolve().parent):
        if (곳 / "발행서버.py").is_file():
            sys.path.insert(0, str(곳))
            import 발행서버
            return 발행서버
    raise 도구오류("공용/발행서버.py 를 찾지 못했어요(build_bundles 로 패키지를 검사해야 함).",
                 힌트="여행스튜디오/공용/ 또는 참고구현/공용/ 에 발행서버.py 가 있어야 해요(규약 1절).")


def 지도그림경로(실, 값) -> Path | None:
    """지도 블록의 '이미지'는 여행/<ID>/작업/지도/*.png 만(지도.py 가 그린 것). 다른 경로·바로가기로 밖을 가리키면 None."""
    m = re.fullmatch(r"작업/지도/([^/]+\.png)", str(값 or "").strip().replace("\\", "/"), re.I)
    if not m or m.group(1).startswith("."):
        return None
    폴더 = (실.여행 / "작업" / "지도").resolve()
    p = 실.여행 / "작업" / "지도" / m.group(1)
    try:
        if p.resolve().parent != 폴더:
            return None
    except OSError:
        return None
    return p


def 글모으기(배치: dict) -> list[tuple[str, str]]:
    """(어디, 글) 목록 — 누수 점검용."""
    결과 = [("제목", str(배치.get("제목") or ""))] + [("태그", str(t)) for t in 배치.get("태그") or []]
    for k, b in enumerate(배치.get("블록") or [], 1):
        if not isinstance(b, dict):
            continue
        for 키 in ("글", "설명", "출처"):
            if b.get(키):
                결과.append((f"블록 {k}({b.get('종류')})", str(b[키])))
        for 키 in ("목록", "장소"):
            for v in b.get(키) or []:
                결과.append((f"블록 {k}({b.get('종류')})", str(v)))
    return 결과


def 본문(실):
    인자 = 실.인자
    편 = 인자.편
    if not 편 or re.search(r'[\\/:*?"<>|\s]', 편):
        raise 도구오류("--편 <편ID> 를 알려 주세요(공백·특수문자 없이, 예: 1일차).")
    배치파일 = 실.여행 / "원고" / f"배치_{편}.json"
    배치 = 읽기_json(배치파일)
    if not isinstance(배치, dict) or not isinstance(배치.get("블록"), list):
        raise 도구오류(f"원고/배치_{편}.json 을 읽지 못했어요('블록' 목록이 있어야 해요).")
    목록 = {x["id"]: x for x in 실.목록() if x.get("id")}
    장소 = 읽기_json(실.여행 / "장소.json", {}) or {}
    정보 = 실.정보()

    with 실.단계("누수 점검") as 기록:
        글들 = 글모으기(배치)
        원고md = 실.여행 / "원고" / f"{편}.md"
        if 원고md.is_file():
            글들 += [(f"원고/{편}.md {n}줄", 줄) for n, 줄 in enumerate(원고md.read_text(encoding="utf-8").splitlines(), 1)]
        걸림 = []
        for 어디, 글 in 글들:
            for 패턴, 이름 in 누수:
                m = re.search(패턴, 글)
                if m:
                    앞 = max(0, m.start() - 15)
                    걸림.append({"어디": 어디, "무엇": 이름, "글": 글[앞:m.end() + 15]})
        if 걸림:
            raise 도구오류(f"내부 표시가 원고에 남아 있어요({len(걸림)}곳) — 패키지를 만들지 않고 멈춰요.",
                         힌트="그 문장만 고친 뒤 다시 실행하세요(전체 재작성 금지).", 자료={"누수": 걸림[:30]})
        기록["산출물"] = None

    with 실.단계("규칙 점검") as 기록:
        문제, 경고 = [], []
        숨긴장소 = set(숨긴장소표(장소, 정보))  # 지도·영상과 같은 규칙(_공통.py): 숨김·숨길장소·비공개 추정
        숨긴이름 = {str(장소[k].get("이름")) for k in 숨긴장소} | set(숨길이름들(정보))
        장소시각 = (실.여행 / "장소.json").stat().st_mtime if (실.여행 / "장소.json").is_file() else 0
        새블록 = []
        for k, b in enumerate(배치["블록"], 1):
            if not isinstance(b, dict):
                continue
            종류 = b.get("종류")
            ids = b.get("사진") or ([b["영상"]] if 종류 == "영상" and b.get("영상") else [])
            for i in ids:
                if i not in 목록:
                    문제.append(f"블록 {k}: 목록에 없는 사진 {i}")
                elif 목록[i].get("사용자결정") == "제외":
                    문제.append(f"블록 {k}: 사람이 '제외'한 사진 {i} 가 들어 있음")
                elif 목록[i].get("장소ID") in 숨긴장소:
                    경고.append(f"블록 {k}: {i} 는 숨긴 장소(숙소 등)에서 찍은 사진 — 위치가 드러나지 않는지 확인")
            if 종류 == "사진" and len(ids) != 1:
                문제.append(f"블록 {k}: '사진' 블록은 1장씩(대표 사진). {len(ids)}장 → 그룹사진으로")
            if 종류 == "그룹사진" and len(ids) > 10:
                if 인자.나누기:
                    for s in range(0, len(ids), 10):
                        조각 = {**b, "사진": ids[s:s + 10]}
                        if s:
                            조각["설명"] = ""
                        새블록.append(조각)
                    경고.append(f"블록 {k}: 그룹 사진 {len(ids)}장을 10장 이하 {(len(ids) + 9) // 10}묶음으로 나눔(미리보기와 모양이 달라질 수 있음)")
                    continue
                문제.append(f"블록 {k}: 그룹 사진 {len(ids)}장 → 한 묶음 10장 이하(--나누기 로 자동 분할 가능)")
            if 종류 == "장소":
                이름들 = [str(x) for x in b.get("장소") or []]
                if len(이름들) > 5:
                    문제.append(f"블록 {k}: 장소 {len(이름들)}곳 → 5곳 이하로 블록 나누기")
                for n in 이름들:
                    if any(h and (h in n or n in h) for h in 숨긴이름):
                        문제.append(f"블록 {k}: 숨긴 장소 '{n}' 이(가) 장소 블록에 있음")
            if 종류 == "영상":  # 2026-10-09 실측: 제목이 없으면 확장이 글 제목을 영상 제목으로 넣음(네이버 업로더는 제목 필수·40자)
                제목들 = b.get("제목") if isinstance(b.get("제목"), list) else [b.get("제목")]
                제목들 = [str(t or "").strip() for t in 제목들]
                if not any(제목들):
                    경고.append(f"동영상 블록 {k}에 제목이 없어 글 제목이 영상 제목으로 들어감 — 영상마다 40자 이하 제목 넣기")
                elif any(len(t) > 40 for t in 제목들):
                    경고.append(f"동영상 블록 {k}의 제목이 40자를 넘음 — 네이버는 40자까지만 받으니 40자 이하로 줄이기")
            if 종류 == "지도":
                그림 = 지도그림경로(실, b.get("이미지"))
                if 그림 is None:
                    문제.append(f"블록 {k}: 지도 그림은 작업/지도/*.png(지도.py 가 그린 것)만 쓸 수 있어요 — {b.get('이미지')}")
                elif not 그림.is_file():
                    문제.append(f"블록 {k}: 지도 그림이 없음 — {b.get('이미지')}")
                else:
                    if 그림.stat().st_mtime < 장소시각:
                        문제.append(f"블록 {k}: 지도 그림이 장소 정보보다 오래됐어요(숨김·이름을 바꾼 뒤 다시 안 그림) "
                                  f"→ python 도구/지도.py --여행 '{실.여행ID}' --지도만")
                    m = re.search(r"(\d+)일차", 그림.stem)
                    그날 = int(m.group(1)) if m else None
                    보이는곳 = {x.get("장소ID") for x in 목록.values()
                            if x.get("장소ID") in 장소 and x.get("장소ID") not in 숨긴장소 and (그날 is None or x.get("일차") == 그날)}
                    미확인 = sorted(f"{pid} {장소[pid].get('이름')}" for pid in 보이는곳 if not 장소[pid].get("확인됨"))
                    if 미확인:
                        문제.append(f"블록 {k}: 지도에 이름이 확인 안 된 장소가 있어요({', '.join(미확인)}) "
                                  "— 질문 카드로 이름을 확인(또는 숨김)한 뒤 지도를 다시 그리세요")
            새블록.append(b)
        if not 배치.get("제목"):
            문제.append("제목이 비어 있음")
        if len(배치.get("태그") or []) > 30:
            문제.append(f"태그 {len(배치['태그'])}개 → 30개 이하")
        # 2026-10-09 실측: 블로그에 없는 카테고리('여행')로 3편 모두 실패 → 설정.json(화면 ⑦)의 카테고리와 대조해 경고만.
        # 패키지에 채우지 않음: 승인 지문에 카테고리가 들어가므로 채우면 '승인한 글과 다름'이 됨(예약 발행·AI 표시 동기화가 깨짐)
        설정 = 읽기_json(실.스튜디오 / "설정.json", {})
        설정카테고리 = 설정.get("카테고리") if isinstance(설정, dict) else None
        설정카테고리 = 설정카테고리.strip() if isinstance(설정카테고리, str) else ""
        배치카테고리 = str(배치.get("카테고리") or "").strip()
        if 배치카테고리 and 설정카테고리 and 배치카테고리 != 설정카테고리:
            경고.append(f"카테고리가 배치와 설정에서 다름(배치 '{배치카테고리}' · 설정 '{설정카테고리}') — 블로그에 있는 이름인지 확인")
        elif not 배치카테고리 and 설정카테고리:
            경고.append(f"배치에 카테고리가 없음 — 설정 값('{설정카테고리}')을 넣으려면 ⑥ [Claude에게 고쳐 달라기]로 "
                        "'카테고리를 설정 값으로 넣어줘'라고 하기(그대로 두면 블로그 기본 카테고리로 임시저장되니 발행 전에 직접 고르기)")
        elif not 배치카테고리:
            경고.append("카테고리 없음 — 블로그 기본 카테고리로 임시저장되니 발행 전에 직접 고르기"
                        "(화면 ⑦ 설정에 '블로그 카테고리'를 적어 두면 다음 글부터 Claude가 넣음)")
        if 문제:
            raise 도구오류(f"고칠 것이 {len(문제)}개 있어요 — 패키지를 만들지 않았어요.", 자료={"고칠것": 문제, "경고": 경고})
        기록["산출물"] = None
        if 경고:
            기록["경고"] = list(경고)  # 작업이력에도 남김(요약 JSON 의 '경고'와 같은 문장)

    with 실.단계("업로드 사본") as 기록:
        쓸id = []
        for b in 새블록:
            if b.get("종류") in ("사진", "그룹사진"):
                쓸id += b.get("사진") or []
            elif b.get("종류") == "영상" and b.get("영상"):
                쓸id.append(b["영상"])
        사본결과 = 업로드사본.만들기(실, [목록[i] for i in dict.fromkeys(쓸id)])
        나쁨 = [r for r in 사본결과 if r["상태"] == "실패" or 업로드사본.남은것(r["점검"])]
        if 나쁨:
            raise 도구오류("업로드 사본 중 실패했거나 메타가 남은 것이 있어요.", 자료={"사본문제": 나쁨})
        사본 = {r["id"]: 실.여행 / r["사본"] for r in 사본결과}
        기록["산출물"] = "작업/업로드사본"

    발행 = 실.여행 / "발행"
    묶음폴더 = 발행 / f"사진묶음_{편}"
    with 실.단계("사진 묶음 폴더") as 기록:
        if 묶음폴더.is_dir():  # 이 도구가 전에 만든 사본만 치우고 새로(원본·다른 파일은 손대지 않음)
            for f in 묶음폴더.rglob("*"):
                if f.is_file() and re.fullmatch(r"d\d+_\d\d_[\w-]+\.(jpg|png|mp4)", f.name):
                    f.unlink()
            for d in sorted((p for p in 묶음폴더.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                if not any(d.iterdir()):
                    d.rmdir()
        패키지 = copy.deepcopy({k: v for k, v in 배치.items() if k != "블록"})
        패키지["블록"] = []
        합계, 장수 = 0, 0
        영상수, 영상합계 = 0, 0
        사진.준비()
        for k, b in enumerate(새블록, 1):
            b = copy.deepcopy(b)
            종류 = b.get("종류")
            if 종류 in ("사진", "그룹사진"):
                방식 = "사진" if 종류 == "사진" else str(b.get("방식") or "콜라주")
                폴더 = 묶음폴더 / f"{k:02d}_{방식영문.get(방식, 'group')}"
                폴더.mkdir(parents=True, exist_ok=True)
                업로드, 누적, 번호 = [], 0, 1
                for i in b.get("사진") or []:
                    일차 = 목록[i].get("일차") or 0
                    대상 = 폴더 / f"d{일차}_{k:02d}_{i}.jpg"
                    shutil.copyfile(사본[i], 대상)
                    크기 = 대상.stat().st_size
                    if 누적 and 누적 + 크기 >= 묶음한도:
                        번호, 누적 = 번호 + 1, 0
                    누적 += 크기
                    업로드.append({"id": i, "파일": 대상.relative_to(발행).as_posix(), "업로드묶음": 번호})
                    합계, 장수 = 합계 + 크기, 장수 + 1
                b["업로드"] = 업로드
            elif 종류 == "지도":
                원 = 지도그림경로(실, b.get("이미지"))  # 규칙 점검에서 이미 확인한 경로
                폴더 = 묶음폴더 / f"{k:02d}_map"
                폴더.mkdir(parents=True, exist_ok=True)
                m = re.search(r"(\d+)일차", 원.stem)
                대상 = 폴더 / f"d{m.group(1) if m else 0}_{k:02d}_map.jpg"
                im = 사진.Image.open(원).convert("RGB")
                im.info = {}
                im.save(대상, "JPEG", quality=90, optimize=True)
                b["업로드"] = [{"id": None, "파일": 대상.relative_to(발행).as_posix(), "업로드묶음": 1}]
                b.setdefault("설명", "")
                if "OpenStreetMap" not in b["설명"]:
                    b["출처표시"] = "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)"
                합계, 장수 = 합계 + 대상.stat().st_size, 장수 + 1
            elif 종류 == "영상" and b.get("영상") in 사본:
                # 메타를 지운 업로드 사본을 묶음 폴더에(같은 드라이브면 하드링크 — 용량을 두 번 쓰지 않음)
                i = b["영상"]
                폴더 = 묶음폴더 / f"{k:02d}_video"
                폴더.mkdir(parents=True, exist_ok=True)
                대상 = 폴더 / f"d{목록[i].get('일차') or 0}_{k:02d}_{i}.mp4"
                대상.unlink(missing_ok=True)
                try:
                    os.link(사본[i], 대상)
                except OSError:
                    shutil.copyfile(사본[i], 대상)
                크기 = 대상.stat().st_size
                b["업로드"] = [{"id": i, "파일": 대상.relative_to(발행).as_posix(), "업로드묶음": 1, "크기": 크기}]
                b["업로드영상"] = 실.상대(사본[i])  # 예전 이름(여행 폴더 기준) — 사람이 '동영상' 버튼으로 올릴 때
                영상수, 영상합계 = 영상수 + 1, 영상합계 + 크기
            패키지["블록"].append(b)
        m = re.fullmatch(r"(\d+)일차", 편)
        패키지.update({"여행ID": 실.여행ID, "편ID": 편, "일차": int(m.group(1)) if m else None})
        패키지["패키지"] = {"만든시각": 지금(), "원본배치": f"../원고/배치_{편}.json", "사진수": 장수,
                         "합계MB": round(합계 / 1048576, 2), "경로기준": "이 패키지 파일이 있는 폴더(발행/)",
                         "영상수": 영상수, "영상합계MB": round(영상합계 / 1048576, 2),
                         "업로드사본규칙": "회전 반영 → 장변 2048px → JPG 85 → GPS·기기 정보 제거(다시 읽어 확인)"}
        기록["산출물"] = 실.상대(묶음폴더)

    with 실.단계("build_bundles 검사·저장") as 기록:
        공용 = 발행서버가져오기()
        임시 = 발행 / f".패키지_{편}.검사중.json"
        최종 = 발행 / f"패키지_{편}.json"
        원자적_쓰기(임시, 패키지)
        try:
            pkg = 공용.load_package(임시)
            응답, 허용 = 공용.build_bundles(pkg)
        except Exception:
            임시.unlink(missing_ok=True)
            raise
        심각 = [w for b in 응답["묶음"] for w in b["경고"] if re.search(r"GPS|촬영기기|10MB|10장|최대 10|파일이 없음|허용 폴더", w)]
        심각 += [w for w in 응답["경고"] if "업로드 사본" in w]
        장수맞음 = all(b["장수"] == len(next(x for i, x in enumerate(패키지["블록"], 1) if i == b["블록"]).get("업로드") or [])
                    for b in 응답["묶음"])
        if 심각 or not 장수맞음:
            임시.unlink(missing_ok=True)
            raise 도구오류("build_bundles 검사에서 문제가 나왔어요 — 패키지를 내놓지 않았어요.",
                         자료={"검사경고": 심각, "장수맞음": 장수맞음})
        os.replace(임시, 최종)
        기록["산출물"] = 실.상대(최종)
        영상자동 = "영상" not in (getattr(공용, "SKIP_KINDS", None) or {})  # 공용 모듈이 영상을 묶음에 넣게 되면 True

    묶음요약 = [{"번호": b["번호"], "블록": b["블록"], "종류": b["종류"], "방식": b["방식"], "장수": b["장수"],
              "합계MB": round(b["합계크기"] / 1048576, 2), "업로드묶음수": b["업로드묶음수"], "경고": b["경고"]}
             for b in 응답["묶음"]]
    return 실.끝({
        "편ID": 편, "패키지": 실.상대(최종), "사진묶음폴더": 실.상대(묶음폴더),
        "묶음수": 응답["묶음수"], "사진수": 응답["사진수"], "합계MB": round(응답["합계크기"] / 1048576, 2),
        "가장큰파일MB": round(max((f["크기"] for b in 응답["묶음"] for f in b["파일"]), default=0) / 1048576, 2),
        "가장큰묶음장수": max((b["장수"] for b in 응답["묶음"]), default=0),
        "묶음": 묶음요약, "건너뜀": 응답["건너뜀"], "경고": 경고 + 응답["경고"],
        "영상": {"수": 영상수, "합계MB": round(영상합계 / 1048576, 2), "도우미가올림": 영상자동},
        "검사": "공용/발행서버.py build_bundles() 로 다시 읽어 확인(GPS·기기 정보 없음, 장당 10MB 이하, 묶음 10장 이하)",
        "다음할일": ["여기서 멈춤 — 사람이 화면 ⑦ 발행에서 [네이버 임시저장]을 누름(Claude는 작업을 만들지 않음)",
                  f"확인용 묶음 주소(확장): http://localhost:8765/api/발행/묶음?여행={실.여행ID}&일차={패키지['일차']}",
                  ("영상 블록은 블로그 도우미가 올림(업로드 경로)" if 영상자동 else
                   "영상 블록은 네이버 에디터의 '동영상' 버튼으로 사람이 올림(업로드 경로의 mp4 — 메타 지운 사본)")],
    })


def main() -> int:
    ap = 인자틀("배치 + 업로드 사본 → 발행 패키지(누수 점검, build_bundles 로 검사)",
              "예) python 도구/발행패키지.py --여행 2026-09_제주 --편 1일차")
    ap.add_argument("--편", required=True, help="편ID(원고/배치_<편ID>.json)")
    ap.add_argument("--나누기", action="store_true", help="10장 넘는 그룹 사진을 10장씩 나눔(기본은 멈추고 알려 줌)")
    a = ap.parse_args()
    return 실행틀("발행패키지", 본문, a, 편ID=a.편)


if __name__ == "__main__":
    sys.exit(main())
