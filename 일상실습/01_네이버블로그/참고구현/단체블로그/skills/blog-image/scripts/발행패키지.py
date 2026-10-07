# -*- coding: utf-8 -*-
"""발행패키지.py — 배치 JSON을 '발행 패키지'(naver-draft 스킬·블로그 도우미 확장의 입력)로 만듭니다.

Windows·Mac 공용. 표준 라이브러리 + **Pillow**(사진 메타데이터 제거용 — '표준 라이브러리만' 원칙의 예외).
  Pillow 설치(프로젝트 가상환경에): Windows `.venv\\Scripts\\pip install pillow` / Mac `.venv/bin/pip install pillow`
  Pillow가 없으면 사진을 내보내지 않고 멈춥니다(위치 정보가 섞인 사진이 나가는 것보다 멈추는 쪽이 안전).

하는 일
  1. 누수 점검: 글에 내부 표시([S3] 같은 카드 번호, '내부용', '발행 금지', '예상 반론')가 남았으면 멈춤
  2. 형식 점검: 사진 '자리'가 남았는지, 제목, 태그 30개 이하, 그룹 사진 10장 이하, 장소 5곳 이하, 파일 10MB 이하
  3. 업로드 사본: 사진을 '발행/사진묶음_<이름>/<블록>_<방식>/<블록>_<순번>.jpg'(영문 파일명)으로 복사
     - 모든 사진을 Pillow로 **다시 저장**합니다: 방향을 그림에 반영한 뒤 EXIF·GPS·기기 정보·XMP·IPTC,
       JPEG 꼬리(모션 포토 MP4·보조 이미지), PNG·WebP 메타 청크를 모두 버립니다. 색 프로필(ICC)만 남깁니다.
     - 다시 저장한 사본을 다시 열어 GPS·기기 정보·JPEG 꼬리가 없는지 확인하고, 하나라도 남거나 실패하면 멈춥니다.
     - 출처대장 '변경사항'에 AI 변환·생성 표시가 있는 이미지는 출처 정보(C2PA)를 지우면 안 되므로 다시 저장하지 않고
       그대로 복사하되, GPS·기기 정보·JPEG 꼬리가 있으면 멈춥니다(사람이 확인).
     - 다시 저장한 사본이 10MB를 넘으면 멈추고 알려 줍니다.
  ※ 보안: --이름 은 글자·숫자·_·- 만(경로 기호·'..' 금지). 사진·지도 그림 경로는 배치 파일 폴더 기준 상대경로만
     (절대경로·드라이브·'..' 금지, 바로가기를 따라간 실제 위치도 그 폴더 안). 지도 그림도 사진처럼 메타를 지운 사본을 씁니다.
     사본 폴더를 지우기 전에 그 폴더가 '발행/' 안인지 확인합니다.
  4. 묶음 계산: '업로드묶음' 번호와 최종 점검은 공용 `발행서버.py`의 build_bundles()로 합니다(규약 2.5: 직접 구현 금지).
     발행서버.py를 못 찾으면 번호 없이 만들고 경고합니다(서버가 받을 때 계산함).

패키지 형식(이 스크립트가 쓰는 것) — 배치 JSON과 같고, 사진 블록마다 두 키가 붙습니다
  "업로드": ["사진묶음_<이름>/02_photo/02_01.jpg", …]   ← 패키지 파일이 있는 폴더 기준 상대경로
  "업로드묶음": [1, …]                                    ← 1회 합계 10MB 미만 묶음 번호(정보용)
  맨 위 "패키지": {"만든시각", "원본배치", "사진수", "합계MB", "승인", "메모"}

사용 예
  python 발행패키지.py 배치_헤켈배아.json --대장 출처대장.csv
  python 발행패키지.py 배치_헤켈배아.json --공용 "C:/…/도구"     (발행서버.py가 있는 폴더를 직접 지정)
마지막 줄에 JSON 요약. 고칠 것이 있으면 패키지를 만들지 않고 종료 코드 1.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as _dt
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

KIND_EN = {"사진": "photo", "콜라주": "collage", "슬라이드": "slide", "개별": "single", "개별 사진": "single",
           "지도": "map"}
MAX_BYTES = 10 * 1024 * 1024
# 누수 점검: 발행하면 안 되는 내부 표시
LEAK_STOP = re.compile(r"\[S\d+\]|\[담당자 확인|내부용|발행 금지|예상 ?반론")
LEAK_WARN = re.compile(r"확인 필요|TODO|XXX|\?\?\?")
# AI 변환·생성 표시(대소문자 구분: 'main', 'detail' 같은 영어 단어에 걸리지 않게)
AI_MARK = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능|삽화풍 변환|생성형")


# ───────── 사진 메타데이터 (Pillow) ─────────
NAME_OK = re.compile(r"[\w가-힣-]{1,40}")
OUT_FORMAT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "PNG", ".bmp": "PNG"}
GPS_TAG, MAKE_TAG, MODEL_TAG, BODY_SERIAL, LENS_MAKE, LENS_MODEL = 0x8825, 0x010F, 0x0110, 0xA431, 0xA433, 0xA434


def need_pillow():
    try:
        from PIL import Image, ImageOps
        return Image, ImageOps
    except ImportError:
        print("고칠 것: 사진의 위치·기기 정보를 지우려면 Pillow가 필요합니다. 프로젝트 가상환경에 설치하세요:\n"
              "  Windows: .venv\\Scripts\\pip install pillow   /   Mac: .venv/bin/pip install pillow\n"
              "  (설치 전에는 사진을 내보내지 않습니다)", file=sys.stderr)
        print(json.dumps({"패키지": None, "고칠것": ["Pillow 없음 — 사진 메타데이터를 지울 수 없음"]}, ensure_ascii=False))
        sys.exit(1)


def leftovers(path: Path, Image) -> list:
    """사본을 다시 열어 남은 개인정보를 찾음: GPS, 기기(제조사·모델·일련번호·렌즈), JPEG 꼬리."""
    bad = []
    data = path.read_bytes()
    with Image.open(path) as im:
        exif = im.getexif()
        if GPS_TAG in exif:
            bad.append("GPS")
        sub = exif.get_ifd(0x8769) if exif else {}
        if any(t in exif for t in (MAKE_TAG, MODEL_TAG)) or any(t in sub for t in (BODY_SERIAL, LENS_MAKE, LENS_MODEL)):
            bad.append("기기 정보")
        fmt = im.format
    if fmt == "JPEG" and jpeg_tail(data):
        bad.append("JPEG 꼬리(모션 포토 영상·보조 이미지 등)")
    return bad


def jpeg_tail(data: bytes) -> bool:
    """첫 그림의 끝(EOI) 뒤에 다른 데이터가 붙어 있는지. 마지막 FFD9를 찾으면 꼬리 속 보조 JPEG의 끝을
    잡을 수 있으므로, 머리 세그먼트를 따라 첫 SOS까지 간 뒤 그 뒤의 첫 FFD9(그림 데이터 안의 FF는 FF00)를 씀."""
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m == 0xDA:
            break
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    eoi = data.find(b"\xff\xd9", i)
    return eoi == -1 or bool(data[eoi + 2:].strip(b"\x00"))


def clean_copy(sp: Path, dp: Path, Image, ImageOps) -> list:
    """다시 저장해 메타데이터를 모두 버림. 남은 것(빈 목록이면 깨끗)을 돌려줌."""
    fmt = OUT_FORMAT[dp.suffix.lower()]
    with Image.open(sp) as im:
        im.load()
        icc = im.info.get("icc_profile")
        out = ImageOps.exif_transpose(im)  # 방향을 그림에 반영(방향 값 없이도 바로 보임)
        if fmt == "JPEG" and out.mode not in ("RGB", "L"):
            out = out.convert("RGB")
        if fmt == "PNG" and out.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            out = out.convert("RGBA")
        out.info = {}
        opts = {"icc_profile": icc} if icc else {}
        if fmt == "JPEG":
            out.save(dp, "JPEG", quality=90, optimize=True, **opts)
        elif fmt == "WEBP":
            out.save(dp, "WEBP", quality=90, **opts)
        else:
            out.save(dp, "PNG", optimize=True, **opts)
    return leftovers(dp, Image)


def inside(path: Path, folder: Path) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    f = os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([p, f]) == f
    except ValueError:
        return False


def image_refs(b: dict) -> list:
    """블록이 가리키는 그림 경로들: 사진·그룹사진은 '사진' 목록, 지도는 '이미지' 하나."""
    if b.get("종류") == "지도":
        return [b["이미지"]] if b.get("이미지") else []
    refs = b.get("사진") or []
    return refs if isinstance(refs, list) else [refs]


def photo_path(base: Path, ref) -> tuple[Path | None, str]:
    """배치에 적힌 사진·그림 경로 → 실제 파일. 규칙(보안 재검수 N1):
    배치 파일 폴더 기준 **상대경로만**(절대경로·드라이브·UNC·'~' 금지), '..'로 위로 올라가기 금지,
    바로가기를 따라간 실제 위치도 배치 파일 폴더 안이어야 함. 문제가 있으면 (None, 이유)."""
    if not isinstance(ref, str) or not ref.strip():
        return None, "경로가 글자가 아님"
    r = ref.strip()
    if (os.path.isabs(r) or re.match(r"^[A-Za-z]:", r) or r.startswith(("/", "\\", "~"))
            or "\x00" in r or ":" in r):
        return None, "절대경로·드라이브·특수 경로는 쓸 수 없음(배치 파일 폴더 기준 상대경로만)"
    if any(part == ".." for part in re.split(r"[\\/]+", r)):
        return None, "'..'로 위 폴더를 가리킬 수 없음"
    p = base / r
    if not inside(p, base):
        return None, "배치 파일 폴더 밖을 가리킴(바로가기 포함)"
    return p, ""


# ───────── 공용 발행서버 찾기 ─────────
def find_shared(script: Path, batch: Path, given: str | None) -> Path | None:
    cands = []
    if given:
        cands.append(Path(given))
    if os.environ.get("BLOG_SHARED_DIR"):
        cands.append(Path(os.environ["BLOG_SHARED_DIR"]))
    if len(script.parents) > 4:  # 참고구현/단체블로그/skills/blog-image/scripts → 참고구현/공용
        cands.append(script.parents[4] / "공용")
    for up in [batch.parent, *batch.parents]:
        cands += [up / "도구", up / "공용"]
    for c in cands:
        if (c / "발행서버.py").is_file():
            return c / "발행서버.py"
    return None


def load_server(path: Path):
    spec = importlib.util.spec_from_file_location("발행서버_공용", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass 등이 모듈을 찾을 수 있게 먼저 등록
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    return mod


def texts_of(d: dict):
    yield "제목", d.get("제목", "")
    for i, b in enumerate(d.get("블록") or [], 1):
        for k in ("글", "설명", "출처"):
            if b.get(k):
                yield f"블록 {i}({b.get('종류')})", str(b[k])
        for item in b.get("목록") or []:
            yield f"블록 {i}({b.get('종류')})", str(item)
    for t in d.get("태그") or []:
        yield "태그", str(t)


def main():
    ap = argparse.ArgumentParser(description="배치 JSON → 발행 패키지")
    ap.add_argument("배치")
    ap.add_argument("--대장", "--ledger", dest="ledger", default=None, help="출처대장.csv(있으면 AI 변환 이미지 판별)")
    ap.add_argument("--이름", "--name", dest="name", default=None, help="패키지 이름(기본: 배치 파일 이름에서)")
    ap.add_argument("--공용", "--shared", dest="shared", default=None, help="발행서버.py가 있는 폴더")
    a = ap.parse_args()

    src = Path(a.배치).resolve()
    base = src.parent
    d = json.loads(src.read_text(encoding="utf-8-sig"))  # 메모장이 붙이는 BOM도 받음
    name = a.name or re.sub(r"^배치_?", "", src.stem) or "글"
    if not NAME_OK.fullmatch(name):
        sys.exit(f"--이름 '{name}' 은 쓸 수 없습니다. 글자·숫자·_·- 만, 40자 이하(경로 기호·'..'·띄어쓰기 금지).")
    ledger = {}
    lp = Path(a.ledger) if a.ledger else base / "출처대장.csv"
    if lp.exists():
        with open(lp, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                ledger[os.path.basename(r.get("파일", ""))] = r

    problems, notes = [], []
    # 1) 누수 점검
    for where, text in texts_of(d):
        m = LEAK_STOP.search(text)
        if m:
            problems.append(f"누수: {where}에 내부 표시 '{m.group(0)}'가 남아 있음 → 지우고 다시")
        w = LEAK_WARN.search(text)
        if w:
            notes.append(f"확인: {where}에 '{w.group(0)}'")
    # 2) 형식 점검
    blocks = d.get("블록") or []
    if not d.get("제목"):
        problems.append("제목이 비어 있음")
    if len(d.get("태그") or []) > 30:
        problems.append(f"태그 {len(d['태그'])}개 → 30개 이하")
    for i, b in enumerate(blocks, 1):
        k = b.get("종류")
        if k in ("사진", "그룹사진", "지도"):
            refs = image_refs(b)
            if not refs:
                problems.append(f"블록 {i}: 사진 자리가 남아 있음 — {b.get('자리', '')}")
            if k == "그룹사진" and len(refs) > 10:
                problems.append(f"블록 {i}: 그룹 사진 {len(refs)}장 → 10장 이하로 나누기")
            for r in refs:
                p, why = photo_path(base, r)
                if p is None:
                    problems.append(f"블록 {i}: {why} — {r}")
                elif not p.is_file():
                    problems.append(f"블록 {i}: 파일 없음 — {r}")
                elif p.suffix.lower() not in OUT_FORMAT:
                    problems.append(f"블록 {i}: 사진 형식이 아님(jpg·png·webp·gif·bmp만) — {r}")
                elif p.stat().st_size > MAX_BYTES:
                    problems.append(f"블록 {i}: {r} 가 10MB를 넘음 → 줄인 뒤 다시")
        if k == "장소" and len(b.get("장소") or []) > 5:
            problems.append(f"블록 {i}: 장소 {len(b['장소'])}곳 → 5곳씩 블록 나누기")
    if problems:
        for p in problems:
            print("고칠 것: " + p, file=sys.stderr)
        print(json.dumps({"패키지": None, "고칠것": problems}, ensure_ascii=False))
        sys.exit(1)

    # 3) 업로드 사본
    Image, ImageOps = need_pillow()
    out_dir = base / "발행"
    photo_dir = out_dir / f"사진묶음_{name}"
    if photo_dir.exists():
        if not (inside(photo_dir, out_dir) and photo_dir.resolve() != out_dir.resolve()):
            sys.exit(f"지우려는 폴더가 발행/ 안이 아닙니다 — 멈춤: {photo_dir}")
        shutil.rmtree(photo_dir)  # 이 스크립트가 만든 사본 폴더만 새로 만듦(원본은 건드리지 않음)
    pkg = copy.deepcopy(d)
    total, count, fail = 0, 0, []
    for i, b in enumerate(pkg.get("블록") or [], 1):
        if b.get("종류") not in ("사진", "그룹사진", "지도"):
            continue
        how = {"사진": "사진", "지도": "지도"}.get(b["종류"]) or b.get("방식", "콜라주")
        sub = photo_dir / f"{i:02d}_{KIND_EN.get(how, 'group')}"
        sub.mkdir(parents=True, exist_ok=True)
        ups = []
        for k, r in enumerate(image_refs(b), 1):
            sp, why = photo_path(base, r)  # 위 점검과 같은 규칙으로 한 번 더(복사 직전)
            if sp is None:
                fail.append(f"{r}: {why}")
                continue
            row = ledger.get(os.path.basename(r))
            is_ai = bool(row and AI_MARK.search(row.get("변경사항", "")))
            ext = sp.suffix.lower()
            ext = ".jpg" if ext == ".jpeg" else ext
            if not is_ai and OUT_FORMAT[ext] == "PNG":
                ext = ".png"  # gif·bmp는 png로 다시 저장
            dp = sub / f"{i:02d}_{k:02d}{ext}"  # 글 안에서 겹치지 않는 영문 파일명
            try:
                if is_ai:
                    shutil.copyfile(sp, dp)  # 출처 정보(C2PA)를 지키려고 다시 저장하지 않음
                    left = leftovers(dp, Image)
                    notes.append(f"{r}: AI 변환·생성 이미지라 그대로 복사(출처 정보 보존)")
                else:
                    left = clean_copy(sp, dp, Image, ImageOps)
            except Exception as e:  # 열 수 없는 사진 등 → 멈춤
                left = [f"처리 실패({type(e).__name__}: {e})"]
            if left:
                dp.unlink(missing_ok=True)
                fail.append(f"{r}: " + ", ".join(left)
                            + (" — AI 이미지는 출처 정보를 지킬 방법을 사람이 정해야 함" if is_ai else ""))
                continue
            size = dp.stat().st_size
            if size > MAX_BYTES:
                fail.append(f"{r}: 다시 저장한 사본이 {size / 1048576:.1f}MB — 10MB 이하로 줄인 뒤 다시")
            ups.append(dp.relative_to(out_dir).as_posix())
            total += size
            count += 1
        b["업로드"] = ups
    if fail:  # 하나라도 개인정보가 남거나 실패하면 패키지를 만들지 않음(fail-closed)
        shutil.rmtree(photo_dir, ignore_errors=True)
        for x in fail:
            print("고칠 것: " + x, file=sys.stderr)
        print(json.dumps({"패키지": None, "고칠것": fail}, ensure_ascii=False))
        sys.exit(1)
    pkg["패키지"] = {
        "만든시각": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "원본배치": os.path.relpath(src, out_dir).replace("\\", "/"),
        "사진수": count, "합계MB": round(total / 1048576, 2),
        "승인": (d.get("승인") or {}).get("상태", "미승인"),
        "메모": notes, "경로기준": "이 패키지 파일이 있는 폴더",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    pp = out_dir / f"패키지_{name}.json"
    pp.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4) 공용 build_bundles로 묶음 번호·최종 점검
    server = find_shared(Path(__file__).resolve(), src, a.shared)
    warn_all = []
    if server:
        mod = load_server(server)
        resp, _ = mod.build_bundles(mod.load_package(pp))
        by_block = {bd["블록"]: [f["업로드묶음"] for f in bd["파일"]] for bd in resp["묶음"]}
        for i, b in enumerate(pkg["블록"], 1):
            if i in by_block:
                b["업로드묶음"] = by_block[i]
        warn_all = resp.get("경고", []) + [w for bd in resp["묶음"] for w in bd.get("경고", [])]
        pkg["패키지"]["묶음점검"] = {"도구": str(server.name), "묶음수": resp["묶음수"], "경고": warn_all}
        pp.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        notes.append("공용 발행서버.py를 찾지 못해 업로드묶음 번호를 붙이지 않음(--공용 으로 위치 지정 가능)")
    bad = [w for w in warn_all if "GPS" in w or "기기" in w]
    if bad:
        print("고칠 것: 업로드 사본에 위치·기기 정보가 남음 → " + "; ".join(bad), file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"패키지": str(pp), "사진": count, "합계MB": round(total / 1048576, 2),
                      "승인": pkg["패키지"]["승인"], "묶음점검": "발행서버.py" if server else "생략",
                      "경고": warn_all, "메모": notes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
