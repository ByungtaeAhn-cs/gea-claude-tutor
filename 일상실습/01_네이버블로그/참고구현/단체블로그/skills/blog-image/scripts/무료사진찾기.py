# -*- coding: utf-8 -*-
"""무료사진찾기.py — 저작권 걱정이 적은 무료 이미지를 찾고, 받고, 출처 대장에 적습니다.

표준 라이브러리만 씁니다(설치할 것 없음). Windows·Mac 공용.

찾는 곳
  openverse  : CC 라이선스 이미지 모음(키 불필요)
  wikimedia  : 위키미디어 공용(키 불필요). 옛 그림·퍼블릭 도메인 자료가 많음
  pexels     : 환경변수 PEXELS_API_KEY 가 있을 때만
  pixabay    : 환경변수 PIXABAY_API_KEY 가 있을 때만
  ※ Unsplash는 API로 받지 않습니다. Unsplash API는 '핫링크'(Unsplash 주소를 그대로 걸기)를 요구해서,
     사진을 네이버 서버에 올리는 블로그 방식과 맞지 않습니다. 필요하면 사람이 웹에서 직접 받습니다.

라이선스 기준 (단체 블로그는 기부 링크가 있으므로 '상업 이용'으로 보고 보수적으로)
  기본 허용 : CC0 · 퍼블릭 도메인(PDM·PD) · CC BY · Pexels · Pixabay · 공공누리 1유형
  --넓게    : + CC BY-SA(리터칭하면 결과물도 CC BY-SA로 표기) + CC BY-ND·공공누리 3유형(리터칭 금지)
  항상 제외 : NC(비영리 한정, 공공누리 2·4유형 포함) · GFDL만 있는 것 · 라이선스를 알 수 없는 것

사용 예
  python 무료사진찾기.py 검색 --검색어 "Haeckel embryos" --곳 wikimedia,openverse --출력 이미지후보.json
  python 무료사진찾기.py 받기 --후보 이미지후보.json --번호 2 5 --폴더 이미지 --대장 출처대장.csv
  python 무료사진찾기.py 표기 --대장 출처대장.csv          (글 끝 '사진 출처' 문구 만들기)

연락처: 위키미디어는 요청에 연락처를 넣으라고 합니다. --이메일 또는 환경변수 BLOG_CONTACT_EMAIL.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

VERSION = "1.1"
HOME = os.environ.get("BLOG_TOOL_URL", "").strip()  # (선택) 도구 안내 주소. 기본은 비움
MAX_UPLOAD = 10 * 1024 * 1024  # 네이버 업로드 권장 상한(장당 10MB)
MAX_WAIT = 60  # 서버가 이보다 오래 기다리라고 하면 기다리지 않고 알려 줌
LEDGER_COLS = ["파일", "서비스", "제목", "원본URL", "이미지URL", "작가", "작가URL", "라이선스", "라이선스URL",
               "표기문구", "변경사항", "리터칭", "주의", "받은날짜"]


class Http:
    def __init__(self, email: str, gap: float):
        self.email = email.strip()
        self.gap = max(gap, 0.3)
        self.last = 0.0
        # 위키미디어 요청 예절: 도구 이름 + 연락처(이메일 BLOG_CONTACT_EMAIL, 선택 주소 BLOG_TOOL_URL)를 User-Agent에.
        # 1차 리허설에서 연락처 없는 요청이 429(10분 대기)를 받은 적이 있음 → 60초 넘는 대기는 하지 않고 연락처 설정을 안내.
        contact = "; ".join(x for x in (HOME, f"mailto:{self.email}" if self.email else "") if x) or "no contact set"
        self.ua = f"GEA-blog-images/{VERSION} ({contact}) python-urllib/{sys.version_info.major}.{sys.version_info.minor}"

    def get(self, url: str, headers: dict | None = None, raw: bool = False, tries: int = 4):
        for attempt in range(tries):
            wait = self.gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            h = {"User-Agent": self.ua}
            h.update(headers or {})
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                    body = r.read()
                    return r.status, (body if raw else json.loads(body.decode("utf-8", errors="replace")))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < tries - 1:
                    ra = e.headers.get("Retry-After")
                    pause = float(ra) if ra and ra.isdigit() else 5 * (attempt + 1)
                    if pause > MAX_WAIT:
                        print(f"  ! {e.code} 응답: 서버가 {pause:.0f}초 뒤에 다시 하라고 합니다. 기다리지 않고 멈춥니다. "
                              "연락처(BLOG_CONTACT_EMAIL)를 설정하고 잠시 뒤 다시 해 보세요.", file=sys.stderr)
                        return e.code, None
                    print(f"  … {e.code} 응답, {pause:.0f}초 기다렸다 다시 시도", file=sys.stderr)
                    time.sleep(pause)
                    continue
                if e.code == 403:
                    print("  ! 403 응답(접근 거부): 요청 예절(User-Agent·연락처) 문제일 수 있습니다.", file=sys.stderr)
                return e.code, None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < tries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                print(f"  ! 네트워크 오류: {e}", file=sys.stderr)
                return 0, None
        return 0, None


def clean(s) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def wm_artist(s: str) -> str:
    """위키미디어 Artist 칸에서 올린 사람·설명 페이지 작성자 같은 부분을 빼고 작가만 남김."""
    s = re.sub(r"^Creator:\s*", "", s or "")
    parts = [p.strip(" ,") for p in s.split(";")]
    keep = [p for p in parts if p and not re.search(r"uploaded|description page|User:", p, re.I)]
    return "; ".join(keep)


def no_utm(url: str) -> str:
    """주소 끝의 추적용 utm_ 꼬리표 제거"""
    u = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if not k.startswith("utm_")]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), u.fragment))


# ───────── 라이선스 분류 ─────────
def classify(name: str, version: str = "") -> dict:
    """라이선스 이름 → {코드, 표시, 허용(기본/넓게/제외), 리터칭, 주의}"""
    n = (name or "").lower().replace("_", " ").replace("-", " ").strip()
    v = f" {version}" if version else ""
    def r(code, label, allow, retouch, warn=""):
        return {"코드": code, "표시": label, "허용": allow, "리터칭": retouch, "주의": warn}
    if not n:
        return r("unknown", "라이선스 정보 없음", "제외", "-", "라이선스를 알 수 없어 쓰지 않습니다")
    if "kogl" in n or "공공누리" in n:
        t = re.search(r"([1-4])", n)
        t = t.group(1) if t else "?"
        if t == "1":
            return r("kogl1", "공공누리 제1유형", "기본", "가능", "출처 표시 필수(공식 문구)")
        if t == "3":
            return r("kogl3", "공공누리 제3유형", "넓게", "금지", "변경 금지 → 리터칭·자르기 금지")
        return r(f"kogl{t}", f"공공누리 제{t}유형", "제외", "-", "비영리 한정 → 단체 블로그에서 제외")
    if "pexels" in n:
        return r("pexels", "Pexels License", "기본", "가능", "인물을 부정적 맥락·보증처럼 쓰지 않기")
    if "pixabay" in n:
        return r("pixabay", "Pixabay Content License", "기본", "가능", "상표·인물이 보이면 주의")
    if re.search(r"\bnc\b", n) or "noncommercial" in n or "non commercial" in n:
        return r("nc", f"CC {name.upper()}{v}".strip(), "제외", "-", "비영리 한정(NC) → 단체 블로그에서 제외")
    if n in ("cc0", "cc0 1.0", "cc zero") or n.startswith("cc0"):
        return r("cc0", "CC0" + v, "기본", "가능")
    if n in ("pdm", "public domain mark") or "public domain" in n or n.startswith("pd ") or n.startswith("pd") and len(n) <= 12:
        return r("pd", "퍼블릭 도메인", "기본", "가능")
    if "gfdl" in n and "cc" not in n:
        return r("gfdl", "GFDL", "제외", "-", "GFDL은 라이선스 전문을 함께 실어야 해서 블로그에 부적합")
    if re.search(r"\bnd\b", n) or "noderiv" in n:
        return r("by-nd", f"CC BY-ND{v}", "넓게", "금지", "변경 금지(ND) → 리터칭·자르기 금지")
    if re.search(r"\bsa\b", n) or "sharealike" in n:
        return r("by-sa", f"CC BY-SA{v}", "넓게", "조건부",
                 "리터칭하면 결과 이미지도 CC BY-SA로 공개·표기해야 함")
    if re.search(r"\bby\b", n) or n == "attribution" or n.startswith("cc by"):
        return r("by", f"CC BY{v}", "기본", "가능", "저작자·출처·라이선스 표기 필수")
    return r("unknown", name, "제외", "-", "알 수 없는 라이선스 → 사람이 원본 페이지에서 확인")


def credit_text(c: dict) -> str:
    title = c.get("제목") or "제목 없음"
    who = c.get("작가") or "작가 미상"
    lic = c["라이선스"]["표시"]
    svc = c["서비스"]
    if c["라이선스"]["코드"] == "pexels":
        return f"Photo by {who} on Pexels ({c.get('원본URL', '')})"
    if c["라이선스"]["코드"] == "pixabay":
        return f"Image by {who} from Pixabay ({c.get('원본URL', '')})"
    if c["라이선스"]["코드"] in ("pd", "cc0"):
        return f"\"{title}\", {who} / {svc} / {lic}"
    url = c.get("라이선스URL") or ""
    return f"\"{title}\" by {who} / {svc} / {lic}" + (f" ({url})" if url else "")


# ───────── 검색 ─────────
def search_openverse(http: Http, q: str, n: int, wide: bool) -> list:
    lic = "cc0,pdm,by" + (",by-sa,by-nd" if wide else "")
    url = ("https://api.openverse.org/v1/images/?q=%s&license=%s&page_size=%d&mature=false"
           % (urllib.parse.quote(q), lic, n))
    code, data = http.get(url)
    out = []
    for it in (data or {}).get("results", []) if code == 200 else []:
        L = classify(it.get("license", ""), it.get("license_version", ""))
        out.append({
            "서비스": "Openverse(" + (it.get("source") or it.get("provider") or "?") + ")",
            "id": it.get("id", ""), "제목": clean(it.get("title")), "작가": clean(it.get("creator")),
            "작가URL": it.get("creator_url") or "", "원본URL": it.get("foreign_landing_url") or "",
            "이미지URL": it.get("url") or "", "미리보기URL": it.get("thumbnail") or "",
            "라이선스": L, "라이선스URL": it.get("license_url") or "",
            "가로": it.get("width"), "세로": it.get("height"), "용량": it.get("filesize"),
            "영문표기": it.get("attribution") or "", "제한": "",
        })
    return out


def search_wikimedia(http: Http, q: str, n: int, wide: bool) -> list:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
        "gsrsearch": "filetype:bitmap " + q, "gsrlimit": str(n),
        # 위키미디어 썸네일은 표준 폭(…500·960·1280·1920…)만 허용(2026-07 기준). 네이버 본문 폭 700px이면 1280으로 충분
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1280",
        "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|UsageTerms|AttributionRequired|Restrictions|ObjectName|Credit|DateTimeOriginal",
    }
    code, data = http.get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    pages = sorted(((data or {}).get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)) if code == 200 else []
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        g = lambda k: clean((md.get(k) or {}).get("value", ""))
        L = classify(g("LicenseShortName"))
        title = g("ObjectName") or re.sub(r"^File:|\.\w+$", "", p.get("title", ""))
        # 원본 파일보다 썸네일(폭 1280px)이 빠르고 업로드 용량에도 맞음. 원본이 더 작으면 원본 주소가 옴.
        thumb = ii.get("thumburl") or ii.get("url")
        out.append({
            "서비스": "Wikimedia Commons", "id": str(p.get("pageid", "")), "제목": title,
            "작가": wm_artist(g("Artist")) or "작가 미상", "작가URL": "", "원본URL": ii.get("descriptionurl") or "",
            "이미지URL": no_utm(thumb or ii.get("url") or ""), "미리보기URL": no_utm(ii.get("thumburl") or ""),
            "라이선스": L, "라이선스URL": g("LicenseUrl"), "가로": ii.get("width"), "세로": ii.get("height"),
            "용량": ii.get("size"), "영문표기": g("Credit"), "제한": g("Restrictions"),
            "원본날짜": g("DateTimeOriginal"),
        })
    return out


def search_pexels(http: Http, q: str, n: int, wide: bool) -> list:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        print("※ PEXELS_API_KEY 가 없어 Pexels는 건너뜁니다.", file=sys.stderr)
        return []
    code, data = http.get("https://api.pexels.com/v1/search?per_page=%d&query=%s" % (n, urllib.parse.quote(q)),
                          headers={"Authorization": key})
    out = []
    for it in (data or {}).get("photos", []) if code == 200 else []:
        src = it.get("src") or {}
        out.append({
            "서비스": "Pexels", "id": str(it.get("id", "")), "제목": clean(it.get("alt")), "작가": clean(it.get("photographer")),
            "작가URL": it.get("photographer_url") or "", "원본URL": it.get("url") or "",
            "이미지URL": src.get("large2x") or src.get("original") or "", "미리보기URL": src.get("medium") or "",
            "라이선스": classify("pexels"), "라이선스URL": "https://www.pexels.com/license/",
            "가로": it.get("width"), "세로": it.get("height"), "용량": None, "영문표기": "", "제한": "",
        })
    return out


def search_pixabay(http: Http, q: str, n: int, wide: bool) -> list:
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        print("※ PIXABAY_API_KEY 가 없어 Pixabay는 건너뜁니다.", file=sys.stderr)
        return []
    url = ("https://pixabay.com/api/?key=%s&q=%s&per_page=%d&safesearch=true"
           % (urllib.parse.quote(key), urllib.parse.quote(q), max(3, n)))
    code, data = http.get(url)
    out = []
    for it in (data or {}).get("hits", []) if code == 200 else []:
        out.append({
            "서비스": "Pixabay", "id": str(it.get("id", "")), "제목": clean(it.get("tags")), "작가": clean(it.get("user")),
            "작가URL": f"https://pixabay.com/users/{it.get('user', '')}-{it.get('user_id', '')}/",
            "원본URL": it.get("pageURL") or "", "이미지URL": it.get("largeImageURL") or "",
            "미리보기URL": it.get("previewURL") or "", "라이선스": classify("pixabay"),
            "라이선스URL": "https://pixabay.com/service/license-summary/", "가로": it.get("imageWidth"),
            "세로": it.get("imageHeight"), "용량": it.get("imageSize"), "영문표기": "", "제한": "",
        })
    return out


def cmd_search(a, http: Http):
    fns = {"openverse": search_openverse, "wikimedia": search_wikimedia, "pexels": search_pexels, "pixabay": search_pixabay}
    found = []
    for s in [x.strip().lower() for x in a.sources.split(",") if x.strip()]:
        if s == "unsplash":
            print("※ Unsplash는 API로 받지 않습니다(핫링크 의무가 네이버 업로드와 충돌). 필요하면 사람이 웹에서 직접 받으세요.",
                  file=sys.stderr)
            continue
        if s not in fns:
            print(f"※ 모르는 곳: {s}", file=sys.stderr)
            continue
        print(f"찾는 중: {s} ← {a.query}", file=sys.stderr)
        found += fns[s](http, a.query, a.rows, a.wide)
    allowed = {"기본"} | ({"넓게"} if a.wide else set())
    keep, dropped = [], []
    for c in found:
        warn = [c["라이선스"]["주의"]] if c["라이선스"]["주의"] else []
        if c.get("제한"):
            warn.append(f"원본 페이지 제한 표시: {c['제한']}(초상권·상표 등) → 확인")
        if c.get("용량") and c["용량"] > MAX_UPLOAD:
            warn.append("원본이 10MB를 넘음 → 줄여서 올리기")
        if c["서비스"] == "Wikimedia Commons" and c["라이선스"]["코드"] == "pd":
            warn.append("옛 그림의 복제 사진이면 한국법상 복제 사진 권리는 불확실(조사 03 1-2) → PD 표시가 분명한 것만")
        warn.append("받기 전에 원본 페이지에서 라이선스를 한 번 더 확인")
        c["주의"] = warn
        c["표기문구"] = credit_text(c)
        (keep if c["라이선스"]["허용"] in allowed else dropped).append(c)
    for i, c in enumerate(keep, 1):
        c["번호"] = i
    out = {"검색어": a.query, "조회시각": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "넓게": a.wide, "후보": keep, "제외": [{"서비스": c["서비스"], "제목": c["제목"], "라이선스": c["라이선스"]["표시"],
                                                  "사유": c["라이선스"]["주의"] or "허용 범위 밖"} for c in dropped]}
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        with open(a.output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        md_path = os.path.splitext(a.output)[0] + ".md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"## 이미지 후보 — {a.query}\n\n| 번호 | 미리보기 | 제목 | 작가 | 라이선스 | 리터칭 | 원본 페이지 | 주의 |\n|---|---|---|---|---|---|---|---|\n")
            for c in keep:
                f.write(f"| {c['번호']} | ![]({c['미리보기URL']}) | {c['제목'][:60]} | {c['작가'][:40]} | {c['라이선스']['표시']} | "
                        f"{c['라이선스']['리터칭']} | {c['원본URL']} | {' / '.join(c['주의'][:-1]) or '-'} |\n")
            if dropped:
                f.write(f"\n제외 {len(dropped)}건(NC·라이선스 불명 등)은 JSON의 '제외'에 있습니다.\n")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"후보": len(keep), "제외": len(dropped)}, ensure_ascii=False))


def safe_name(i: int, c: dict, ext: str) -> str:
    svc = re.sub(r"[^a-z]", "", c["서비스"].lower())[:10] or "img"
    stem = re.sub(r"[^A-Za-z0-9]+", "_", c.get("제목") or "")[:30].strip("_").lower() or str(c.get("id", ""))[:12]
    return f"{i:02d}_{svc}_{stem}{ext}"


def cmd_get(a, http: Http):
    with open(a.candidates, encoding="utf-8") as f:
        data = json.load(f)
    pool = {c["번호"]: c for c in data.get("후보", [])}
    os.makedirs(a.folder, exist_ok=True)
    existing = len([x for x in os.listdir(a.folder) if not x.startswith(".")])
    new_ledger = not os.path.exists(a.ledger)
    rows, report = [], []
    for k, num in enumerate(a.nums, 1):
        c = pool.get(num)
        if not c:
            report.append({"번호": num, "결과": "후보 목록에 없음"})
            continue
        if c["라이선스"]["허용"] == "제외":
            report.append({"번호": num, "결과": "허용되지 않는 라이선스라 받지 않음"})
            continue
        code, body = http.get(c["이미지URL"], raw=True)
        if code != 200 or not body:
            report.append({"번호": num, "결과": f"받기 실패(HTTP {code})"})
            continue
        ext = os.path.splitext(urllib.parse.urlparse(c["이미지URL"]).path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".png" if body[:4] == b"\x89PNG" else ".jpg"
        name = safe_name(existing + k, c, ".jpg" if ext == ".jpeg" else ext)
        path = os.path.join(a.folder, name)
        with open(path, "wb") as f:
            f.write(body)
        warn = list(c.get("주의", [])[:-1])
        if len(body) > MAX_UPLOAD:
            warn.append(f"파일이 {len(body)/1048576:.1f}MB → 업로드 전 줄이기 필요")
        rows.append({
            "파일": os.path.relpath(path, os.path.dirname(os.path.abspath(a.ledger))).replace("\\", "/"),
            "서비스": c["서비스"], "제목": c["제목"], "원본URL": c["원본URL"], "이미지URL": c["이미지URL"],
            "작가": c["작가"], "작가URL": c.get("작가URL", ""), "라이선스": c["라이선스"]["표시"],
            "라이선스URL": c.get("라이선스URL", "") or ("해당 없음(퍼블릭 도메인) — 원본 페이지에서 표시 확인"
                                                        if c["라이선스"]["코드"] in ("pd", "cc0") else "확인 필요"),
            "표기문구": c["표기문구"], "변경사항": "없음",
            "리터칭": c["라이선스"]["리터칭"], "주의": " / ".join(warn),
            "받은날짜": _dt.date.today().isoformat(),
        })
        report.append({"번호": num, "결과": "받음", "파일": path, "KB": round(len(body) / 1024)})
    if rows:
        with open(a.ledger, "a", encoding="utf-8-sig" if new_ledger else "utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
            if new_ledger:
                w.writeheader()
            w.writerows(rows)
    print(json.dumps({"받기": report, "대장": a.ledger}, ensure_ascii=False, indent=2))


def cmd_credit(a, http: Http):
    with open(a.ledger, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    lines = ["사진 출처"]
    for r in rows:
        line = f"- {r['표기문구']}"
        if r.get("변경사항") and r["변경사항"] not in ("없음", ""):
            line += f" — {r['변경사항']}"
        lines.append(line)
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="무료 이미지 찾기·받기·출처 대장")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("검색", aliases=["search"])
    s.add_argument("--검색어", "--query", dest="query", required=True)
    s.add_argument("--곳", "--sources", dest="sources", default="openverse,wikimedia,pexels,pixabay")
    s.add_argument("--개수", "--rows", dest="rows", type=int, default=12)
    s.add_argument("--넓게", "--wide", dest="wide", action="store_true", help="BY-SA·BY-ND·공공누리 3유형도 후보에 포함")
    s.add_argument("--출력", "--output", dest="output")
    g = sub.add_parser("받기", aliases=["get"])
    g.add_argument("--후보", "--candidates", dest="candidates", required=True)
    g.add_argument("--번호", "--nums", dest="nums", type=int, nargs="+", required=True)
    g.add_argument("--폴더", "--folder", dest="folder", default="이미지")
    g.add_argument("--대장", "--ledger", dest="ledger", default="출처대장.csv")
    c = sub.add_parser("표기", aliases=["credit"])
    c.add_argument("--대장", "--ledger", dest="ledger", default="출처대장.csv")
    for p in (s, g, c):
        p.add_argument("--이메일", "--mailto", dest="email", default=os.environ.get("BLOG_CONTACT_EMAIL", ""))
        p.add_argument("--간격", "--gap", dest="gap", type=float, default=1.0)
    a = ap.parse_args()
    http = Http(a.email, a.gap)
    {"검색": cmd_search, "search": cmd_search, "받기": cmd_get, "get": cmd_get,
     "표기": cmd_credit, "credit": cmd_credit}[a.cmd](a, http)


if __name__ == "__main__":
    main()
