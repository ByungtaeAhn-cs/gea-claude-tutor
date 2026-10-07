# -*- coding: utf-8 -*-
"""발행연동.py — 여행 스튜디오 서버가 '공용/발행서버.py'(단체 블로그와 같은 모듈)를 가져다 쓰는 다리.

규약 v2 2.5·8절, 공용/발행API.md 10절: 사진 묶음·확장 연결(연결 코드·토큰)·발행 작업(job)은 모두
공용 모듈의 PublishAPI 가 처리합니다. 스튜디오는 직접 다시 만들지 않고, 이 파일에서
  - 공용 모듈을 찾아 불러오고(이 서버가 든 여행스튜디오의 공용/ → 참고구현 개발용 ../공용/),
  - PublishAPI(TripFolderSource(스튜디오), …) 를 한 번 만들어 서버에 건네기만 합니다.
  - 예약 발행의 '승인'·'자동 예약 허락'은 공용 모듈의 ApprovalStore(서버만 아는 키로 서명)가 확인합니다(보안 검수 M3).
보안(검수 H1): 코드는 '이 파일이 든 폴더' 쪽에서만 찾습니다. 서버의 --폴더(데이터 폴더) 안의 공용/ 은 보지 않음
— 여행/ 처럼 Claude 가 쓸 수 있는 곳에 심은 발행서버.py 가 불려 실행되는 일을 막음.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

_모듈 = None
_모듈경로: Path | None = None
_api = None
브라우저값 = {"chrome": "chrome", "edge": "edge", "default": "default"}  # 설정 화면 값 = 공용 open_in_browser 값


def 공용폴더후보(스튜디오: Path | None = None) -> list[Path]:
    """코드(발행서버.py·미리보기.py)를 찾을 곳. 데이터 폴더(스튜디오 인자)는 쓰지 않음 — 위 '보안' 참고."""
    여기 = Path(__file__).resolve().parent.parent  # 이 파일이 든 여행스튜디오 폴더
    교재속공용 = Path("일상실습") / "01_네이버블로그" / "참고구현" / "공용"
    # ① 스튜디오 공용/(공용가져오기.py 로 복사한 것) ② 참고구현의 ../공용 ③ 실습공간에 복사한 스튜디오 → 교재 저장소의 공용
    후보 = [여기 / "공용", 여기.parent / "공용", 여기.parent.parent / 교재속공용]
    결과, 본것 = [], set()
    for p in 후보:
        k = str(p.resolve())
        if k not in 본것:
            본것.add(k)
            결과.append(p)
    return 결과


def 공용파일(스튜디오: Path, 이름: str) -> Path | None:
    """공용 폴더에서 파일 찾기(참고구현 원본은 공용/미리보기/미리보기.py 처럼 하위 폴더에 있음)."""
    for 폴더 in 공용폴더후보(스튜디오):
        for 후보 in (폴더 / 이름, 폴더 / Path(이름).stem / 이름):
            if 후보.is_file():
                return 후보
    return None


def 모듈(스튜디오: Path):
    """공용 발행서버 모듈(없으면 None). 한 번 불러오면 기억."""
    global _모듈, _모듈경로
    if _모듈 is not None:
        return _모듈
    파일 = 공용파일(스튜디오, "발행서버.py")
    if not 파일:
        return None
    spec = importlib.util.spec_from_file_location("공용_발행서버", 파일)
    m = importlib.util.module_from_spec(spec)
    sys.modules["공용_발행서버"] = m          # dataclass 가 모듈 이름으로 자기를 찾으므로 먼저 등록
    spec.loader.exec_module(m)
    _모듈, _모듈경로 = m, 파일
    return m


def 다시불러오기() -> None:
    """공용 파일을 새로 가져온 뒤(화면 [공용 파일 갱신]) 서버를 끄지 않고 새 모듈을 쓰게 함."""
    global _모듈, _모듈경로, _api
    _모듈, _모듈경로, _api = None, None, None
    sys.modules.pop("공용_발행서버", None)


def 파일해시(경로: Path) -> str:
    return hashlib.sha256(Path(경로).read_bytes()).hexdigest()


def 모듈경로() -> str | None:
    return str(_모듈경로) if _모듈경로 else None


def api(스튜디오: Path, 포트: int, 설정함수, 사건함수):
    """공용 PublishAPI 하나(서버가 켜져 있는 동안 계속 씀). 공용 모듈이 없거나 v1 이면 None."""
    global _api
    if _api is None:
        m = 모듈(스튜디오)
        if m is None or not hasattr(m, "PublishAPI") or not hasattr(m, "TripFolderSource") or not hasattr(m, "ApprovalStore"):
            return None  # 승인 서명(ApprovalStore)이 없는 옛 공용 모듈은 쓰지 않음 → 화면에 [공용 파일 갱신]
        _api = m.PublishAPI(m.TripFolderSource(스튜디오), port=포트, server_name="여행스튜디오",
                            settings=설정함수, on_event=사건함수)
    return _api


def 처리할주소(경로: str) -> bool:
    m = _모듈
    return bool(m is not None and hasattr(m, "PublishAPI") and m.PublishAPI.handles(경로))
