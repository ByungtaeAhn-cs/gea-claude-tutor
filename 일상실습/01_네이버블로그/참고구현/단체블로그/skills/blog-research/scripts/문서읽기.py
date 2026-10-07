# -*- coding: utf-8 -*-
"""문서읽기.py — 공공기관·법령·교육청 자료(PDF·HWP·HWPX)에서 글자를 꺼내, 찾는 말이 있는 부분만 보여 줍니다.

원칙
  - 저장하지 않음: 인터넷 주소를 주면 임시 폴더에 받았다가 읽은 뒤 바로 지웁니다. 필요한 문장만 출처 카드로 옮깁니다.
  - 크기 제한: 기본 30MB, 최대 400쪽(바꾸려면 --최대MB, --최대쪽).
  - 찾는 말(--찾기)을 주면 그 말이 있는 문단과 앞뒤만 보여 줍니다(전체를 화면에 쏟지 않음).

형식별 준비물
  HWPX(한글 새 형식) : 설치할 것 없음(표준 라이브러리)
  HWP(한글 옛 형식)  : olefile (BSD 라이선스)   →  pip install olefile
  PDF                : pypdf  (BSD-3 라이선스)  →  pip install pypdf
  ※ 설치가 어렵거나 막혀 있으면: PDF는 Claude Code의 Read 도구로 직접 읽을 수 있습니다(한 번에 20쪽까지).
     HWP는 한글 프로그램에서 'HWPX' 또는 'PDF'로 다른 이름 저장한 뒤 읽습니다.
  ※ 글자가 거의 안 나오는 PDF는 스캔본(그림)입니다 → Read 도구로 쪽 그림을 보고 필요한 부분만 옮겨 적거나(OCR),
     기관에 텍스트본(HWP·HWPX)을 요청합니다. 큰 스캔본 전체 OCR은 이 실습 범위 밖입니다.
  ※ 배포용(암호화) HWP는 읽을 수 없습니다 → PDF본을 찾습니다.

사용 예
  python 문서읽기.py "https://www.korea.kr/common/download.do?fileId=198298163&tblKey=GMN" --찾기 고교학점제 진로
  python 문서읽기.py 자료/교육과정.pdf --쪽 3-10 --찾기 진화
  python 문서읽기.py 자료/공문.hwp --최대글자 3000
마지막 줄에 JSON 요약(형식·쪽/구역 수·글자 수·찾은 곳 수).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
import zlib
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

UA = "GEA-blog-research/1.1 (document reader; " + (f"mailto:{os.environ['BLOG_CONTACT_EMAIL']}" if os.environ.get("BLOG_CONTACT_EMAIL") else "no contact set") + ")"


def fetch(url: str, max_mb: float) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        size = int(r.headers.get("Content-Length") or 0)
        if size and size > max_mb * 1048576:
            raise SystemExit(f"파일이 {size / 1048576:.1f}MB로 제한({max_mb}MB)을 넘습니다. --최대MB 로 늘리거나 필요한 쪽만 받으세요.")
        name = ""
        cd = r.headers.get("Content-Disposition") or ""
        m = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)", cd)
        if m:
            name = urllib.parse.unquote(m.group(1) or m.group(2))
            try:  # 일부 서버는 UTF-8 이름을 latin-1로 보냄
                name = name.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        buf, limit = io.BytesIO(), int(max_mb * 1048576)
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > limit:
                raise SystemExit(f"받는 중 제한({max_mb}MB)을 넘어 멈췄습니다.")
        return buf.getvalue(), name


def kind_of(data: bytes, name: str) -> str:
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        return "hwp"
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(n.startswith("Contents/section") for n in z.namelist()):
                    return "hwpx"
        except zipfile.BadZipFile:
            pass
        return "zip"
    ext = os.path.splitext(name)[1].lower()
    return {".txt": "text", ".md": "text", ".html": "html", ".htm": "html"}.get(ext, "모름")


# ───────── HWPX: 표준 라이브러리 ─────────
def read_hwpx(data: bytes) -> list[tuple[str, str]]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        secs = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                      key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        for si, n in enumerate(secs, 1):
            xml = z.read(n)
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:  # 정상 HWPX에는 없음 → 악성 XML(엔티티 폭탄 등) 차단
                raise SystemExit(f"{n}: 문서 형식 선언(DTD)이 들어 있어 안전을 위해 읽지 않습니다.")
            root = ET.fromstring(xml)
            for p in root.iter():
                if p.tag.rsplit("}", 1)[-1] != "p":
                    continue
                # 이 문단에 직접 속한 글자(t)만: 표 안 문단은 따로 나오므로 중복을 피하려고 run(t) 깊이 2까지만
                parts = []
                for run in p:
                    if run.tag.rsplit("}", 1)[-1] != "run":
                        continue
                    for t in run:
                        if t.tag.rsplit("}", 1)[-1] == "t":
                            parts.append("".join(t.itertext()))
                txt = "".join(parts).strip()
                if txt:
                    out.append((f"구역{si}", txt))
    return out


# ───────── HWP 5.0: olefile 필요 ─────────
CHAR_CTRL = {0, 10, 13} | set(range(24, 32))
def _para_text(b: bytes) -> str:
    """HWP 문단 글자(UTF-16LE). 글자 단위를 모아 한꺼번에 풀어야 이모지·한자 확장 같은 '짝 글자'가 깨지지 않음."""
    out, units, i, n = [], [], 0, len(b) // 2

    def flush():
        if units:
            out.append(struct.pack(f"<{len(units)}H", *units).decode("utf-16-le", errors="replace"))
            units.clear()
    while i < n:
        c = struct.unpack_from("<H", b, i * 2)[0]
        if c >= 32:
            units.append(c)
            i += 1
        elif c in CHAR_CTRL:
            flush()
            if c in (10, 13):
                out.append("\n")
            i += 1
        else:  # 인라인·확장 컨트롤은 8글자(16바이트) 차지
            flush()
            if c == 9:
                out.append("\t")
            i += 8
    flush()
    return "".join(out)


def read_hwp(data: bytes) -> list[tuple[str, str]]:
    try:
        import olefile
    except ImportError:
        raise SystemExit("HWP를 읽으려면 olefile이 필요합니다: pip install olefile "
                         "(설치가 어려우면 한글에서 HWPX나 PDF로 저장한 뒤 읽으세요)")
    ole = olefile.OleFileIO(io.BytesIO(data))
    header = ole.openstream("FileHeader").read()
    flags = struct.unpack_from("<I", header, 36)[0]
    compressed, encrypted, distribution = bool(flags & 1), bool(flags & 2), bool(flags & 4)
    if encrypted or distribution:
        raise SystemExit("암호가 걸렸거나 '배포용' HWP라 읽을 수 없습니다. PDF본을 찾거나 기관에 요청하세요.")
    out, si = [], 0
    while ole.exists(f"BodyText/Section{si}"):
        raw = ole.openstream(f"BodyText/Section{si}").read()
        if compressed:
            raw = zlib.decompress(raw, -15)
        pos = 0
        while pos + 4 <= len(raw):
            h = struct.unpack_from("<I", raw, pos)[0]
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            pos += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", raw, pos)[0]
                pos += 4
            if tag == 67:  # HWPTAG_PARA_TEXT
                txt = _para_text(raw[pos:pos + size]).strip()
                if txt:
                    out.append((f"구역{si + 1}", txt))
            pos += size
        si += 1
    return out


# ───────── PDF: pypdf 필요 ─────────
def read_pdf(data: bytes, pages: tuple[int, int] | None, max_pages: int) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("PDF를 읽으려면 pypdf가 필요합니다: pip install pypdf "
                         "(설치가 어려우면 Claude Code의 Read 도구로 PDF를 직접 읽으세요. 한 번에 20쪽까지)")
    r = PdfReader(io.BytesIO(data))
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            raise SystemExit("암호가 걸린 PDF입니다.")
    total = len(r.pages)
    a, b = pages or (1, total)
    b = min(b, total, a + max_pages - 1)
    out = []
    for i in range(a - 1, b):
        txt = (r.pages[i].extract_text() or "").strip()
        for para in re.split(r"\n\s*\n", txt):
            para = re.sub(r"[ \t]+\n", "\n", para).strip()
            if para:
                out.append((f"{i + 1}쪽", para))
    return out


def one_line(s: str) -> str:
    """줄바꿈을 한 칸 띄어쓰기로(화면 출력용)."""
    return re.sub(r"\s*\n\s*", " ", s)


def main():
    ap = argparse.ArgumentParser(description="PDF·HWP·HWPX에서 글자 꺼내기(저장하지 않음)")
    ap.add_argument("대상", help="파일 경로 또는 http(s) 주소")
    ap.add_argument("--찾기", "--find", dest="find", nargs="*", default=[], help="찾을 말(여러 개 가능)")
    ap.add_argument("--앞뒤", "--context", dest="ctx", type=int, default=1, help="찾은 문단 앞뒤로 더 보여 줄 문단 수")
    ap.add_argument("--쪽", "--pages", dest="pages", help="PDF 쪽 범위 예: 3-10")
    ap.add_argument("--최대MB", "--max-mb", dest="max_mb", type=float, default=30)
    ap.add_argument("--최대쪽", "--max-pages", dest="max_pages", type=int, default=400)
    ap.add_argument("--최대글자", "--max-chars", dest="max_chars", type=int, default=6000)
    a = ap.parse_args()

    tmp = None
    try:
        if re.match(r"https?://", a.대상):
            data, name = fetch(a.대상, a.max_mb)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(name)[1])  # 읽는 동안만
            tmp.write(data)
            tmp.close()
        else:
            if os.path.getsize(a.대상) > a.max_mb * 1048576:
                raise SystemExit(f"파일이 제한({a.max_mb}MB)을 넘습니다.")
            data, name = open(a.대상, "rb").read(), os.path.basename(a.대상)
        kind = kind_of(data, name)
        pages = None
        if a.pages:
            x, _, y = a.pages.partition("-")
            pages = (int(x), int(y or x))
        if kind == "hwpx":
            paras = read_hwpx(data)
        elif kind == "hwp":
            paras = read_hwp(data)
        elif kind == "pdf":
            paras = read_pdf(data, pages, a.max_pages)
        elif kind in ("text", "html"):
            t = data.decode("utf-8", "replace")
            if kind == "html":
                t = re.sub(r"<[^>]+>", "\n", t)
            paras = [("본문", p.strip()) for p in re.split(r"\n\s*\n", t) if p.strip()]
        else:
            raise SystemExit(f"읽을 수 없는 형식입니다({kind}). PDF·HWP·HWPX·텍스트만 됩니다.")
    finally:
        if tmp and os.path.exists(tmp.name):
            os.remove(tmp.name)  # 저장하지 않음 원칙: 임시 파일 바로 삭제

    chars = sum(len(p) for _, p in paras)
    print(f"# {name or a.대상}  ({kind}, 문단 {len(paras)}개, 글자 {chars:,}자)\n")
    hits = []
    if a.find:
        squash = lambda s: re.sub(r"\s+", "", s.lower())  # 줄바꿈·띄어쓰기 차이 무시(슬라이드 PDF는 낱말 중간에서 줄이 바뀜)
        keys = [squash(k) for k in a.find]
        hit_idx = [i for i, (_, p) in enumerate(paras) if any(k in squash(p) for k in keys)]
        shown = set()
        for i in hit_idx:
            for j in range(max(0, i - a.ctx), min(len(paras), i + a.ctx + 1)):
                if j in shown:
                    continue
                shown.add(j)
                mark = "▶ " if j == i else "  "
                flat = one_line(paras[j][1])[:800]
                print(f"{mark}[{paras[j][0]}] {flat}")
            print("—")
        hits = hit_idx
    else:
        used = 0
        for where, p in paras:
            if used > a.max_chars:
                print(f"… (이하 생략, --최대글자 {a.max_chars}. 찾을 말을 --찾기 로 주면 그 부분만 봅니다)")
                break
            flat = one_line(p)
            print(f"[{where}] {flat}")
            used += len(p)
    scanned = kind == "pdf" and paras and chars / max(1, len({w for w, _ in paras})) < 30
    if kind == "pdf" and (not paras or scanned):
        print("※ 글자가 거의 없습니다. 스캔본(그림) PDF로 보입니다 → Read 도구로 쪽 그림을 보고 필요한 부분만 옮겨 적거나 텍스트본을 요청하세요.")
    print(json.dumps({"형식": kind, "문단": len(paras), "글자": chars, "찾은곳": len(hits),
                      "구역·쪽": len({w for w, _ in paras}), "저장": "안 함(임시 파일 삭제)"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
