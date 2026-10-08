# -*- coding: utf-8 -*-
"""시계보정.py — 기기 시계 오차(기기보정초)를 목록에만 적용합니다. 원본 파일은 그대로. (규약 2.1·4절)

세 가지 쓰임
  1) 적용:   python 도구/시계보정.py --여행 2026-09_제주
             여행정보.json 의 기기보정초를 목록.json 에 반영 → 촬영시각·일차 다시 계산
  2) 쌍 계산: python 도구/시계보정.py --여행 2026-09_제주 --쌍 IMG_4824.JPG DSC01525.JPG [--저장]
             '같은 순간'을 찍은 두 장(앞 = 시계가 맞는 기기, 뒤 = 맞출 기기)의 차이로 오차 계산.
             --저장 을 붙이면 기기보정초에 적고 바로 적용(사람이 '같은 순간'이라고 확인한 뒤에만!)
  3) 쌍 찾기: python 도구/시계보정.py --여행 2026-09_제주 --쌍찾기
             다른 기기끼리 같은 장면을 찍은 것 같은 사진 쌍 후보(특징점 맞추기) → 콘택트 시트로 보여 주고 질문 카드로 확인
  직접 입력: --기기 카메라 --초 4020  (예: 카메라 화면 속 시계 사진으로 오차를 이미 알 때)
'시각출처'가 '사용자'인 사진(사람이 직접 정한 시각)은 바꾸지 않습니다. '사용자결정'은 건드리지 않습니다.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _공통 import 도구오류, 시각읽기, 오프셋글, 인자틀, 일차계산, 실행틀, 초글, 필요  # noqa: E402


def 찾기(목록: list[dict], 이름: str) -> dict:
    """id(p0012) 또는 파일 이름(IMG_4824.JPG, 아이폰/IMG_4824.JPG)으로 항목 찾기."""
    for x in 목록:
        if x.get("id") == 이름:
            return x
    키 = 이름.replace("\\", "/").lower()
    맞음 = [x for x in 목록 if str(x.get("원본", "")).lower().endswith("/" + 키) or str(x.get("원본", "")).lower() == 키]
    if len(맞음) == 1:
        return 맞음[0]
    if not 맞음:
        raise 도구오류(f"'{이름}' 사진을 목록에서 찾지 못했어요(id 나 파일 이름으로 알려 주세요).")
    raise 도구오류(f"'{이름}' 이(가) 여러 개예요: " + ", ".join(f"{x['id']}({x['기기']})" for x in 맞음) + " → id 로 알려 주세요.")


def 보정전(x: dict):
    t = 시각읽기(x.get("촬영시각"))
    return None if t is None else t - timedelta(seconds=int(x.get("보정초") or 0))


def 쌍찾기(실, 목록: list[dict], 개수: int) -> list[dict]:
    """다른 기기의 사진끼리 ORB 특징점을 맞춰 같은 장면(같은 순간 후보)을 찾음. 미리보기(이미 회전 반영)를 씀."""
    np, cv2 = 필요("numpy", "cv2")
    import _사진 as 사진
    사진.준비()
    orb = cv2.ORB_create(1000)
    특징 = []
    for x in 목록:
        if x.get("종류") != "사진" or x.get("원본없음"):
            continue
        p = 실.여행 / str(x.get("미리보기") or "")
        if not p.is_file():
            continue
        im = 사진.Image.open(p).convert("L")
        im.thumbnail((640, 640))
        kp, des = orb.detectAndCompute(np.asarray(im), None)
        if des is not None and len(kp) >= 20:
            특징.append((x, kp, des))
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    후보 = []
    for i in range(len(특징)):
        for j in range(i + 1, len(특징)):
            a, b = 특징[i], 특징[j]
            if a[0]["기기"] == b[0]["기기"]:
                continue
            ta, tb = 보정전(a[0]), 보정전(b[0])
            if ta and tb and abs((ta - tb).total_seconds()) > 36 * 3600:  # 하루 반 넘게 차이 나면 같은 순간일 리 없음
                continue
            짝 = bf.knnMatch(a[2], b[2], k=2)
            좋은 = [m for m, *n in 짝 if n and m.distance < 0.75 * n[0].distance]
            if len(좋은) < 12:
                continue
            p1 = np.float32([a[1][m.queryIdx].pt for m in 좋은])
            p2 = np.float32([b[1][m.trainIdx].pt for m in 좋은])
            _, 표 = cv2.findHomography(p1, p2, cv2.RANSAC, 5.0)
            맞음 = int(표.sum()) if 표 is not None else 0
            if 맞음 >= 15:
                후보.append((맞음, a[0], b[0]))
    후보.sort(key=lambda t: -t[0])
    결과 = []
    for 맞음, a, b in 후보[:개수]:
        # 시계가 더 믿을 만한 쪽(EXIF+Offset 등)을 기준으로
        if a.get("시각출처") == "EXIF" and b.get("시각출처") != "EXIF":
            a, b = b, a
        ta, tb = 보정전(a), 보정전(b)
        차 = (ta - tb).total_seconds() if ta and tb else None
        결과.append({"기준": a["id"], "기준파일": f"{a['기기']}/{Path(a['원본']).name}",
                   "맞출": b["id"], "맞출파일": f"{b['기기']}/{Path(b['원본']).name}",
                   "특징점일치": 맞음, "확신": "강함" if 맞음 >= 100 else ("보통" if 맞음 >= 40 else "약함(같은 장소일 뿐일 수 있음)"),
                   "시각차초": 차, "시각차": 초글(차) if 차 is not None else None})
    return 결과


def 적용(실, 정보: dict) -> dict:
    """기기보정초 → 목록의 보정초·촬영시각·일차. (사용자결정은 목록합치기가 지킴)"""
    보정표 = {str(k): int(v) for k, v in (정보.get("기기보정초") or {}).items()}
    고칠것, 바뀐기기 = {}, {}
    for x in 실.목록():
        if x.get("시각출처") == "사용자":
            continue
        새 = 보정표.get(x.get("기기"), 0)
        옛 = int(x.get("보정초") or 0)
        기준 = 보정전(x)
        if 기준 is None:
            continue
        촬영 = 오프셋글((기준 + timedelta(seconds=새)).replace(microsecond=0))
        일차 = 일차계산(촬영, 정보)
        if 새 != 옛 or 촬영 != x.get("촬영시각") or 일차 != x.get("일차"):
            고칠것[x["id"]] = {"보정초": 새, "촬영시각": 촬영, "일차": 일차}
            바뀐기기[x.get("기기")] = 바뀐기기.get(x.get("기기"), 0) + 1
    결과 = 실.목록합치기(고칠것)
    return {"바뀐사진수": len(고칠것), "기기별": 바뀐기기, "목록": 결과}


def 본문(실):
    인자 = 실.인자
    정보 = 실.정보()
    요약 = {}
    if 인자.쌍찾기:
        with 실.단계("같은 순간 쌍 찾기") as 기록:
            후보 = 쌍찾기(실, 실.목록(), 인자.개수)
            요약["쌍후보"] = 후보
            요약["안내"] = ("후보를 콘택트 시트로 보여 주고(python 도구/콘택트시트.py --여행 … --id <기준> <맞출>) "
                          "'같은 순간인가요?' 질문 카드로 확인한 뒤 --쌍 <기준> <맞출> --저장")
            기록["산출물"] = None
        return 실.끝(요약)

    if 인자.쌍:
        with 실.단계("쌍으로 오차 계산"):
            목록 = 실.목록()
            a, b = 찾기(목록, 인자.쌍[0]), 찾기(목록, 인자.쌍[1])
            if a["기기"] == b["기기"]:
                raise 도구오류("두 사진이 같은 기기예요. 시계가 맞는 기기 한 장 + 맞출 기기 한 장을 골라 주세요.")
            ta = 시각읽기(a.get("촬영시각"))  # 기준 쪽은 (이미 보정됐다면) 보정된 시각을 믿음
            tb = 보정전(b)
            if ta is None or tb is None:
                raise 도구오류("두 사진 중 촬영 시각이 없는 것이 있어요.")
            오차 = int(round((ta - tb).total_seconds()))
            방향 = "늦어요" if 오차 > 0 else ("빨라요" if 오차 < 0 else "맞아요")
            요약.update({"기준": {"id": a["id"], "기기": a["기기"], "파일": Path(a["원본"]).name, "시각": a["촬영시각"], "출처": a["시각출처"]},
                       "맞출": {"id": b["id"], "기기": b["기기"], "파일": Path(b["원본"]).name, "기록시각": b.get("기록시각")},
                       "오차초": 오차, "오차": 초글(오차),
                       "설명": f"{b['기기']} 시계가 실제보다 {초글(abs(오차))} {방향} → 기기보정초.{b['기기']} = {오차}"})
            if a.get("시각출처") in ("EXIF", "파일명", "파일수정시각") and a["기기"] not in (정보.get("기기보정초") or {}):
                요약["주의"] = f"기준 사진({a['기기']})의 시각도 약한 출처({a.get('시각출처')})예요. 시계가 맞는 기기를 앞에 두세요."
        if not 인자.저장:
            요약["저장안함"] = "사람이 '같은 순간'이라고 확인한 뒤 --저장 을 붙여 다시 실행하세요."
            return 실.끝(요약)
        인자.기기, 인자.초 = b["기기"], 오차

    if 인자.기기 is not None:
        if 인자.초 is None:
            raise 도구오류("--기기 와 함께 --초 를 알려 주세요(늦으면 +, 빠르면 -).")
        with 실.단계("기기보정초 저장") as 기록:
            def 고치기(d):
                표 = dict(d.get("기기보정초") or {})
                표[인자.기기] = int(인자.초)
                d["기기보정초"] = 표
            정보 = 실.정보고치기(고치기)
            기록["산출물"] = "여행정보.json"
            실.알림(f"기기보정초.{인자.기기} = {인자.초} ({초글(인자.초)})")

    with 실.단계("목록에 적용") as 기록:
        요약.update(적용(실, 정보))
        요약["기기보정초"] = 정보.get("기기보정초") or {}
        기록["산출물"] = "목록.json"
    요약["다음할일"] = [f"python 도구/지도.py --여행 '{실.여행ID}'  (시각이 바뀌면 GPS 없는 사진의 장소 추정도 달라져요)"]
    return 실.끝(요약)


def main() -> int:
    ap = 인자틀("기기 시계 오차 → 목록에만 반영(원본 그대로). 쌍 계산·쌍 찾기 포함",
              "예) python 도구/시계보정.py --여행 2026-09_제주 --쌍 IMG_4824.JPG DSC01525.JPG --저장")
    ap.add_argument("--쌍", nargs=2, metavar=("기준", "맞출"), help="같은 순간 두 장: 시계가 맞는 기기 사진, 맞출 기기 사진(id 또는 파일 이름)")
    ap.add_argument("--저장", action="store_true", help="--쌍 으로 계산한 오차를 여행정보.json 기기보정초에 적고 적용")
    ap.add_argument("--쌍찾기", action="store_true", help="다른 기기끼리 같은 장면 사진 쌍 후보 찾기(바꾸지 않음)")
    ap.add_argument("--개수", type=int, default=5, help="--쌍찾기 후보 수(기본 5)")
    ap.add_argument("--기기", help="직접 입력할 기기 이름(원본 하위 폴더 이름)")
    ap.add_argument("--초", type=int, help="그 기기 시계 오차(초). 실제보다 늦으면 +, 빠르면 -")
    return 실행틀("시계보정", 본문, ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
