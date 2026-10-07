# -*- coding: utf-8 -*-
"""_사진.py — 사진 열기(HEIC 포함)·회전 반영·sRGB·EXIF 읽기·메타 점검 (Pillow + pillow-heif)

여러 도구가 함께 씁니다. 원본은 '읽기'만 합니다.
"""
from __future__ import annotations

import io
import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _공통 import 필요

Image, ImageOps = None, None
사진확장자 = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp"}
영상확장자 = {".mov", ".mp4", ".m4v", ".3gp", ".avi", ".mts", ".mkv"}
RAW확장자 = {".dng", ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf", ".rw2"}


def 준비():
    """Pillow + pillow-heif 를 가져오고 HEIC 열기를 켬(한 번만)."""
    global Image, ImageOps
    if Image is None:
        PIL, pillow_heif = 필요("PIL", "pillow_heif")
        from PIL import Image as _I, ImageOps as _O
        pillow_heif.register_heif_opener()
        Image, ImageOps = _I, _O
        Image.MAX_IMAGE_PIXELS = 300_000_000  # 파노라마 사진도 열리게(기본 경고 한도 상향)
    return Image


def 열기(경로: Path, 최대변: int | None = None):
    """사진을 열어 EXIF 회전을 반영한 RGB 이미지로. 최대변을 주면 JPEG 는 draft 로 빠르게 줄여 읽음."""
    준비()
    im = Image.open(경로)
    if 최대변 and im.format == "JPEG":
        try:
            im.draft("RGB", (최대변, 최대변))
        except Exception:
            pass
    im = ImageOps.exif_transpose(im)
    im = sRGB로(im)
    if 최대변:
        im.thumbnail((최대변, 최대변), Image.LANCZOS)
    return im


def sRGB로(im):
    """색 프로필(ICC)이 있으면 sRGB 로 바꾸고, 모드를 RGB 로 맞춤(아이폰 Display P3 색 바램 방지)."""
    준비()
    icc = im.info.get("icc_profile")
    if icc:
        try:
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            im = ImageCms.profileToProfile(im, src, dst, outputMode="RGB")
        except Exception:
            pass
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        바탕 = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        바탕.paste(im, mask=im.split()[-1])
        im = 바탕
    elif im.mode != "RGB":
        im = im.convert("RGB")
    im.info.pop("icc_profile", None)
    return im


# ───────────────────────────────────────────── EXIF
def _도(값) -> float | None:
    try:
        d, m, s = (float(x) for x in 값)
        return d + m / 60 + s / 3600
    except Exception:
        try:
            return float(값)
        except Exception:
            return None


def exif읽기(경로: Path) -> dict:
    """{'촬영': 'YYYY-MM-DDTHH:MM:SS' 또는 None, '오프셋': '+09:00'|None, '초이하': '123', 'GPS': {위도,경도}|None,
        'GPS시각': aware datetime|None, '제조사','모델','방향','크기':(w,h),'형식'} — 못 읽으면 빈 값."""
    준비()
    결과 = {"촬영": None, "오프셋": None, "초이하": None, "GPS": None, "GPS시각": None,
          "제조사": None, "모델": None, "방향": None, "크기": None, "형식": None, "날짜태그": None}
    try:
        with Image.open(경로) as im:
            결과["크기"], 결과["형식"] = im.size, im.format
            ex = im.getexif()
    except Exception as e:
        결과["오류"] = f"{type(e).__name__}: {e}"
        return 결과
    if not ex:
        return 결과
    sub = ex.get_ifd(0x8769) if 0x8769 in ex else {}
    gps = ex.get_ifd(0x8825) if 0x8825 in ex else {}

    def 글(v):
        if isinstance(v, bytes):
            v = v.decode("utf-8", "ignore")
        return str(v).strip("\x00 ").strip() if v is not None else None

    결과["제조사"], 결과["모델"] = 글(ex.get(0x010F)), 글(ex.get(0x0110))
    결과["방향"] = ex.get(0x0112)
    원래 = 글(sub.get(0x9003)) or 글(sub.get(0x9004))
    결과["날짜태그"] = "DateTimeOriginal" if 글(sub.get(0x9003)) else ("DateTimeDigitized" if 원래 else None)
    if not 원래:
        원래 = 글(ex.get(0x0132))
        결과["날짜태그"] = "DateTime" if 원래 else None
    if 원래:
        m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", 원래)
        if m and m.group(1) != "0000":
            결과["촬영"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}"
    오프 = 글(sub.get(0x9011)) or 글(sub.get(0x9010))
    if 오프 and re.fullmatch(r"[+-]\d{2}:\d{2}", 오프):
        결과["오프셋"] = 오프
    결과["초이하"] = 글(sub.get(0x9291))
    if gps:
        위, 경 = _도(gps.get(2)), _도(gps.get(4))
        if 위 is not None and 경 is not None and not (abs(위) < 1e-9 and abs(경) < 1e-9):
            if 글(gps.get(1)) == "S":
                위 = -위
            if 글(gps.get(3)) == "W":
                경 = -경
            if -90 <= 위 <= 90 and -180 <= 경 <= 180:
                결과["GPS"] = {"위도": round(위, 6), "경도": round(경, 6)}
        날, 시 = 글(gps.get(29)), gps.get(7)
        if 날 and 시:
            try:
                h, mi, s = (float(x) for x in 시)
                d = datetime.strptime(날, "%Y:%m:%d").replace(tzinfo=timezone.utc)
                결과["GPS시각"] = d + timedelta(hours=h, minutes=mi, seconds=s)
            except Exception:
                pass
    return 결과


# ───────────────────────────────────────────── 메타 점검(업로드 사본 다시 읽어 확인)
def jpeg조각들(경로: Path) -> list[tuple[int, bytes]]:
    """JPEG 의 APPn·COM 조각 목록 [(marker, 앞 16바이트)]."""
    with open(경로, "rb") as f:
        data = f.read()
    if data[:2] != b"\xff\xd8":
        return []
    i, 결과 = 2, []
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:
            break
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        n = struct.unpack(">H", data[i + 2:i + 4])[0]
        결과.append((marker, data[i + 4:i + 4 + 16]))
        i += 2 + n
    return 결과


def 메타점검(경로: Path) -> dict:
    """업로드 사본(JPEG)에 남은 것 — 하나라도 True 면 올리면 안 됨(fail-closed).
    GPS·기기·EXIF·XMP·IPTC·주석, MPF(아이폰 HDR·심도 보조 JPEG), 꼬리(끝 표시 뒤 데이터 = 모션 포토 MP4 등),
    여러그림(JPEG 안에 다른 JPEG), JPEG아님."""
    준비()
    결과 = {"GPS": False, "기기": False, "EXIF": False, "XMP": False, "IPTC": False,
          "주석": False, "MPF": False, "꼬리": False, "여러그림": False, "JPEG아님": False}
    with open(경로, "rb") as f:
        data = f.read()
    if data[:3] != b"\xff\xd8\xff":
        결과["JPEG아님"] = True
        return 결과
    # 엔트로피 데이터 안의 0xFF 는 0xFF00 으로 바뀌므로 'FFD8FF'(새 그림 시작)는 진짜 두 번째 그림일 때만 나옴
    결과["여러그림"] = data.count(b"\xff\xd8\xff") > 1
    결과["꼬리"] = data.rfind(b"\xff\xd9") != len(data) - 2
    for marker, 머리 in jpeg조각들(경로):
        if marker == 0xE1 and 머리.startswith(b"Exif\x00\x00"):
            결과["EXIF"] = True
        if marker == 0xE1 and 머리.startswith(b"http://ns.adobe"):
            결과["XMP"] = True
        if marker == 0xED:
            결과["IPTC"] = True
        if marker == 0xFE:
            결과["주석"] = True
        if marker == 0xE2 and 머리.startswith(b"MPF\x00"):
            결과["MPF"] = True
    with Image.open(경로) as im:
        ex = im.getexif()
        if 0x8825 in ex and ex.get_ifd(0x8825):
            결과["GPS"] = True
        if ex.get(0x010F) or ex.get(0x0110):
            결과["기기"] = True
        if im.info.get("xmp"):
            결과["XMP"] = True
    return 결과
