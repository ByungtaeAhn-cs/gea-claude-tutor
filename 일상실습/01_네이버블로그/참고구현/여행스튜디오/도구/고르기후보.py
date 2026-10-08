# -*- coding: utf-8 -*-
"""고르기후보.py — 흐림·눈 감음·연사 묶음·대표 후보를 계산해 '점수'·'판정'만 씁니다. (규약 2.2·4절)

지우지 않습니다. '제외 후보'로 표시만 하고, 결정('사용자결정')은 사람이 화면에서 합니다.
  - 선명도: 라플라시안 분산(장변 960px 흑백). 고정 임계값 대신 '상대 비교'
      · 연사 묶음 안: 묶음 최고 대비 비율(선명도_묶음비) → 가장 선명한 한 장만 남기고 나머지는 제외 후보
      · 묶음 밖(낱장): 같은 기기 사진들의 중앙값 대비 10% 미만이면 '흐림' 제외 후보
  - 연사 묶음: 같은 기기 + 2초 이내 + 지각 해시(phash) 거리 12 이하
  - 눈 감음: MediaPipe Face Landmarker(Tasks API)의 eyeBlinkLeft/Right (모델은 처음에 버전 고정 주소에서 받아
    도구/모델/ 에 캐시하고, 쓸 때마다 SHA-256 확인. 못 받거나 해시가 다르면 눈 감음 점수 없이 계속).
    얼굴이 크게 나온 사진은 '대표로 쓰기 전 확인' 사유를 붙임
  - 대표 후보: 선명도(기기 안 상대값)·색감·노출로 일차마다 몇 장 → Claude가 콘택트 시트로 다시 고름
다시 돌려도 Claude가 붙인 판정 사유(이 도구가 붙인 것이 아닌 것)는 지킵니다.

사용  python 도구/고르기후보.py --여행 2026-09_제주   [--눈감음끄기]
"""
from __future__ import annotations

import hashlib
import os
import statistics
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import 도구오류, 시각읽기, 인자틀, 실행틀, 필요  # noqa: E402
import _사진 as 사진  # noqa: E402

# 버전 고정 + 해시 확인(2026-10-08 확인: 버전 1 = latest, 3,758,596바이트). 모델을 바꿀 때는 두 값을 함께 고침
모델주소 = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
모델SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
도구사유머리 = ("흐림", "연사", "눈 감음", "얼굴", "노출", "아주 짧은")
흐림비율 = 0.10      # 같은 기기 중앙값의 10% 미만 = 흐림 후보
흐림하한 = 8.0       # 이보다 낮으면 기기와 관계없이 흐림 후보(장변 960px 기준)
연사초 = 2.0
연사해시 = 12
눈감음기준 = 0.6
큰얼굴비율 = 0.03     # 얼굴 상자가 사진 넓이의 3% 이상


def 점수재기(경로: Path, 원본: Path) -> dict:
    np, cv2, imagehash = 필요("numpy", "cv2", "imagehash")
    with 사진.Image.open(원본) as 원래:  # 화소 수는 원본 기준(미리보기는 줄어 있음)
        화소 = 원래.size[0] * 원래.size[1]
    im = 사진.열기(경로, 최대변=960)
    회 = np.asarray(im.convert("L"))
    선명 = float(cv2.Laplacian(회, cv2.CV_64F).var())
    작은 = im.copy()
    작은.thumbnail((320, 320))
    a = np.asarray(작은).astype("float32")
    rg, yb = a[..., 0] - a[..., 1], 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    색감 = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    밝기 = float(회.mean())
    날림 = float(((회 >= 250) | (회 <= 5)).mean())
    return {"선명도": round(선명, 1), "색감": round(색감, 1), "밝기": round(밝기, 1), "날림비율": round(날림, 3),
            "해시": str(imagehash.phash(작은)), "화소": 화소}


def 모델받기(실) -> bytes | None:
    """face_landmarker.task 를 캐시(<여행스튜디오>/도구/모델/)에서 읽거나 버전 고정 주소에서 받음.
    읽을 때마다 SHA-256 을 확인(캐시 파일이 바뀌었거나 상류가 바뀌었으면 쓰지 않음 — 보안 검수 L7)."""
    캐시 = 실.스튜디오 / "도구" / "모델" / "face_landmarker.task"
    if 캐시.is_file():
        data = 캐시.read_bytes()
        if hashlib.sha256(data).hexdigest() == 모델SHA256:
            return data
        실.로그(f"캐시한 눈 감음 모델의 SHA-256 이 달라 쓰지 않고 다시 받음: {캐시}", "경고")
    try:
        실.알림("눈 감음 모델(약 3.6MB)을 처음 한 번 받는 중… (MediaPipe 공식 주소, 버전 1 고정)")
        req = urllib.request.Request(모델주소, headers={"User-Agent": "TravelStudio/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(20_000_000)
        실제 = hashlib.sha256(data).hexdigest()
        if 실제 != 모델SHA256:
            raise ValueError(f"받은 모델의 SHA-256 이 기대값과 다름({실제[:16]}…) — 쓰지 않음")
        캐시.parent.mkdir(parents=True, exist_ok=True)
        임시 = 캐시.with_suffix(".part")
        임시.write_bytes(data)
        os.replace(임시, 캐시)
        return data
    except Exception as e:
        실.로그(f"눈 감음 모델을 쓸 수 없음 → 눈 감음 점수 없이 계속: {e}", "경고")
        return None


def 얼굴재기(모델: bytes, 경로들: dict[str, Path]) -> dict[str, dict]:
    """{id: {'얼굴수','눈감음','얼굴최대비율'}} — MediaPipe Tasks API(FaceLandmarker). 옛 mp.solutions 는 쓰지 않음."""
    np = 필요("numpy")
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision
    옵션 = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_buffer=모델),  # 경로 대신 바이트(한글 경로 문제 피함)
        running_mode=vision.RunningMode.IMAGE, num_faces=6, output_face_blendshapes=True,
        min_face_detection_confidence=0.5)
    결과 = {}
    with vision.FaceLandmarker.create_from_options(옵션) as 탐지:
        for i, p in 경로들.items():
            try:
                im = 사진.열기(p, 최대변=1280)
                화면 = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(np.asarray(im)))
                r = 탐지.detect(화면)
            except Exception:
                continue
            깜빡, 최대 = [], 0.0
            for k, 점들 in enumerate(r.face_landmarks or []):
                xs, ys = [q.x for q in 점들], [q.y for q in 점들]
                최대 = max(최대, (max(xs) - min(xs)) * (max(ys) - min(ys)))
                if r.face_blendshapes and k < len(r.face_blendshapes):
                    표 = {b.category_name: b.score for b in r.face_blendshapes[k]}
                    깜빡.append(min(표.get("eyeBlinkLeft", 0), 표.get("eyeBlinkRight", 0)))
            결과[i] = {"얼굴수": len(r.face_landmarks or []), "눈감음": round(max(깜빡), 3) if 깜빡 else None,
                     "얼굴최대비율": round(최대, 4)}
    return 결과


def 해밍(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def 본문(실):
    인자 = 실.인자
    사진.준비()
    목록 = 실.목록()
    사진들 = [x for x in 목록 if x.get("종류") == "사진" and not x.get("원본없음")]

    def 경로(x):
        p = 실.여행 / str(x.get("미리보기") or "")
        return p if p.is_file() else Path(x["원본"])

    with 실.단계("선명도·색감 재기"):
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
            점 = dict(zip([x["id"] for x in 사진들], ex.map(lambda x: 점수재기(경로(x), Path(x["원본"])), 사진들)))
        실.알림(f"사진 {len(점)}장 선명도를 쟀어요")

    얼굴 = {}
    눈상태 = "끔"
    if not 인자.눈감음끄기:
        with 실.단계("눈 감음(MediaPipe)"):
            try:
                필요("mediapipe")
                모델 = 모델받기(실)
                if 모델:
                    얼굴 = 얼굴재기(모델, {x["id"]: 경로(x) for x in 사진들})
                    눈상태 = "계산함"
                else:
                    눈상태 = "모델 없음(건너뜀)"
            except 도구오류 as e:
                눈상태 = "mediapipe 없음(건너뜀)"
                실.로그(f"{e.메시지} → 눈 감음 점수 없이 계속", "경고")
            except Exception as e:  # 인텔 Mac 등에서 mediapipe 가 안 돌아도 나머지는 계속
                눈상태 = f"실패(건너뜀): {type(e).__name__}"
                실.로그(f"눈 감음 계산 실패 → 건너뜀: {e}", "경고")

    with 실.단계("연사 묶음·판정"):
        # 연사 묶음: 기기별 시각순, 앞 사진과 2초 이내 + 해시 거리 12 이하면 같은 묶음
        기기별 = defaultdict(list)
        for x in 사진들:
            기기별[x.get("기기")].append(x)
        묶음 = {}
        묶음번호 = 0
        for dev, xs in 기기별.items():
            xs.sort(key=lambda x: (str(x.get("촬영시각") or ""), x["id"]))
            현재 = [xs[0]] if xs else []
            def 닫기(g):
                nonlocal 묶음번호
                if len(g) >= 2:
                    묶음번호 += 1
                    for y in g:
                        묶음[y["id"]] = f"B{묶음번호:02d}"
            for 앞, 뒤 in zip(xs, xs[1:]):
                ta, tb = 시각읽기(앞.get("촬영시각")), 시각읽기(뒤.get("촬영시각"))
                같음 = (ta and tb and abs((tb - ta).total_seconds()) <= 연사초
                       and 해밍(점[앞["id"]]["해시"], 점[뒤["id"]]["해시"]) <= 연사해시)
                if 같음:
                    현재.append(뒤)
                else:
                    닫기(현재)
                    현재 = [뒤]
            닫기(현재)
        # 묶음 번호를 시각순으로 다시 매김
        첫시각 = {}
        for x in 사진들:
            b = 묶음.get(x["id"])
            if b:
                첫시각[b] = min(첫시각.get(b, "9"), str(x.get("촬영시각")))
        새번호 = {b: f"B{k:02d}" for k, b in enumerate(sorted(첫시각, key=첫시각.get), 1)}
        묶음 = {i: 새번호[b] for i, b in 묶음.items()}

        중앙값 = {dev: statistics.median([점[x["id"]]["선명도"] for x in xs]) or 1.0 for dev, xs in 기기별.items()}
        판정 = {}
        묶음원 = defaultdict(list)
        for x in 사진들:
            if x["id"] in 묶음:
                묶음원[묶음[x["id"]]].append(x)
        베스트 = {}
        for b, xs in 묶음원.items():
            최고 = max(점[x["id"]]["선명도"] for x in xs) or 1.0

            def 순위(x):
                s = 점[x["id"]]["선명도"] / 최고
                눈 = (얼굴.get(x["id"]) or {}).get("눈감음")
                return s - (0.5 if 눈 is not None and 눈 >= 눈감음기준 else 0)
            베스트[b] = max(xs, key=순위)["id"]
        for x in 사진들:
            i, s = x["id"], 점[x["id"]]
            사유, 제외 = [], False
            b = 묶음.get(i)
            묶음비 = None
            if b:
                묶음비 = round(s["선명도"] / (max(점[y["id"]]["선명도"] for y in 묶음원[b]) or 1.0), 3)
                if i != 베스트[b]:
                    제외 = True
                    사유.append(f"연사: 같은 묶음({b})에 더 선명한 사진({베스트[b]}) — 이 사진은 그 {묶음비 * 100:.0f}%")
            기기비 = s["선명도"] / 중앙값[x.get("기기")]
            # 연사 묶음의 나머지 컷은 묶음 안 상대 비교로만 판단(위). 낱장·묶음 베스트만 기기 기준으로 흐림 판정
            if (not b or i == 베스트[b]) and (기기비 < 흐림비율 or s["선명도"] < 흐림하한):
                제외 = True
                사유.append(f"흐림: 선명도 {s['선명도']:.1f} (같은 기기 중앙값 {중앙값[x.get('기기')]:.0f}의 {기기비 * 100:.1f}%)")
            f = 얼굴.get(i) or {}
            if f.get("눈감음") is not None and f["눈감음"] >= 눈감음기준:
                제외 = True
                사유.append(f"눈 감음 의심(점수 {f['눈감음']:.2f})")
            if (f.get("얼굴최대비율") or 0) >= 큰얼굴비율:
                사유.append("얼굴이 크게 나옴 — 대표로 쓰기 전 사람에게 확인")
            if s["밝기"] < 35 or s["밝기"] > 225 or s["날림비율"] > 0.5:
                사유.append(f"노출 확인(밝기 {s['밝기']:.0f}/255)")
            판정[i] = {"제외후보": 제외, "사유": 사유, "묶음베스트": bool(b and 베스트[b] == i), "_묶음비": 묶음비, "_기기비": 기기비}

        # 대표 후보(기술적으로 괜찮은 사진 몇 장 — 최종 고르기는 Claude가 콘택트 시트로, 결정은 사람이):
        # 제외 후보가 아니고, 카메라 정보가 있는 원본(카톡 등으로 받아 줄어든 사본 제외)이며 화소가 여행 중앙값의 60% 이상인 사진 중
        # (여행 전체 선명도 순위 + 색감 순위 + 적정 노출) 상위를 일차마다 몇 장
        화소중앙 = statistics.median([점[x["id"]]["화소"] for x in 사진들]) if 사진들 else 0
        후보들 = [x for x in 사진들 if not 판정[x["id"]]["제외후보"] and x.get("모델")
                and 점[x["id"]]["화소"] >= 0.6 * 화소중앙]
        if 후보들:
            색들 = sorted(점[x["id"]]["색감"] for x in 후보들)
            선들 = sorted(점[x["id"]]["선명도"] for x in 후보들)

            def 백분위(값, 정렬된):
                return sum(1 for v in 정렬된 if v <= 값) / len(정렬된)

            def 대표점수(x):
                s = 점[x["id"]]
                노출 = 1.0 - min(1.0, abs(s["밝기"] - 125) / 125)
                return 0.45 * 백분위(s["선명도"], 선들) + 0.4 * 백분위(s["색감"], 색들) + 0.15 * 노출
            일차별 = defaultdict(list)
            for x in 후보들:
                일차별[x.get("일차")].append(x)
            고름 = set()
            for 일, xs in 일차별.items():
                k = max(1, round(len(xs) * 0.12))
                for x in sorted(xs, key=대표점수, reverse=True)[:k]:
                    if "얼굴이 크게" not in " ".join(판정[x["id"]]["사유"]):
                        고름.add(x["id"])
            for x in 후보들:
                판정[x["id"]]["대표후보"] = x["id"] in 고름
                판정[x["id"]]["_대표점수"] = round(대표점수(x), 3)

    with 실.단계("목록에 점수·판정 쓰기") as 기록:
        고칠것 = {}
        for x in 목록:
            i = x.get("id")
            옛판정 = dict(x.get("판정") or {})
            남길사유 = [r for r in (옛판정.get("사유") or []) if not str(r).startswith(도구사유머리)]
            if x.get("종류") == "영상":
                길이 = x.get("영상길이초")
                새사유 = [f"아주 짧은 영상({길이:.1f}초)"] if 길이 is not None and 길이 < 2 else []
                고칠것[i] = {"판정": {**옛판정, "사유": 남길사유 + 새사유,
                                    "제외후보": bool(옛판정.get("제외후보") and 남길사유) or bool(새사유),
                                    "대표후보": bool(옛판정.get("대표후보") and 남길사유)}}
                continue
            if i not in 판정:
                continue
            p, s, f = 판정[i], 점[i], 얼굴.get(i) or {}
            점수 = {**(x.get("점수") or {}), "선명도": s["선명도"], "선명도_묶음비": p["_묶음비"],
                  "눈감음": f.get("눈감음"), "연사묶음": 묶음.get(i), "얼굴수": f.get("얼굴수"),
                  "색감": s["색감"], "밝기": s["밝기"], "대표점수": p.get("_대표점수")}
            새판정 = {**옛판정,
                    "제외후보": p["제외후보"] or bool(옛판정.get("제외후보") and 남길사유),
                    "사유": 남길사유 + p["사유"],
                    "대표후보": bool(p.get("대표후보")) or bool(옛판정.get("대표후보") and 남길사유),
                    "묶음베스트": p["묶음베스트"]}
            고칠것[i] = {"점수": 점수, "판정": 새판정}
        결과 = 실.목록합치기(고칠것)
        기록["산출물"] = "목록.json"

    def 이름(i):
        x = next(y for y in 사진들 if y["id"] == i)
        return f"{x['기기']}/{Path(x['원본']).name}"
    흐림 = [{"id": i, "파일": 이름(i), "선명도": 점[i]["선명도"]} for i, p in 판정.items()
          if any(r.startswith("흐림") for r in p["사유"])]
    묶음요약 = [{"묶음": b, "사진": [{"id": x["id"], "파일": 이름(x["id"]), "묶음비": 판정[x["id"]]["_묶음비"]} for x in
                                 sorted(xs, key=lambda y: y["id"])], "베스트": 베스트[b], "베스트파일": 이름(베스트[b])}
             for b, xs in sorted(묶음원.items())]
    return 실.끝({
        "사진": len(사진들), "눈감음": 눈상태,
        "제외후보": sum(1 for p in 판정.values() if p["제외후보"]),
        "흐림": 흐림, "연사묶음": 묶음요약,
        "대표후보": [{"id": i, "파일": 이름(i), "점수": 판정[i].get("_대표점수")} for i in 판정 if 판정[i].get("대표후보")],
        "얼굴있는사진": [{"id": i, **v} for i, v in 얼굴.items() if v.get("얼굴수")],
        "목록": 결과,
        "다음할일": [f"python 도구/콘택트시트.py --여행 '{실.여행ID}'  → 서브에이전트로 나눠 보고 판정 합치기(사용자결정은 사람이)"],
    })


def main() -> int:
    ap = 인자틀("흐림·눈 감음·연사 묶음·대표 후보 → 목록의 '점수'·'판정'만 (지우지 않음)",
              "예) python 도구/고르기후보.py --여행 2026-09_제주")
    ap.add_argument("--눈감음끄기", action="store_true", help="MediaPipe 눈 감음 계산을 건너뜀(빠름, 인텔 Mac 등)")
    return 실행틀("고르기후보", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
