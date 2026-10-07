# -*- coding: utf-8 -*-
"""인용검증.py — DOI(논문 고유번호)로 서지·철회·인용문을 확인합니다.

표준 라이브러리만 씁니다(설치할 것 없음). Windows·Mac 공용.

하는 일 (DOI마다)
  1. doi.org      : DOI가 실제로 있는지 (없으면 지어낸 인용일 가능성)
  2. Crossref     : 제목·저자·연도·학술지·권·쪽, 철회·정정 표시(updated-by), 이 DOI를 고친 공지(filter=updates)
  3. OpenAlex     : 철회 여부(is_retracted), 무료 원문 위치, 초록
  4. Europe PMC   : 초록, 글 종류(뉴스·서한·논평 등), 무료 원문(있으면 본문까지)
  5. 대조         : '기대' 서지(초안에 적힌 것)와 비교, '인용문'이 제목·초록·본문 어디에 있는지

사용 예
  python 인용검증.py --doi 10.1007/s004290050082 10.1126/science.277.5331.1435a
  python 인용검증.py --입력 주장목록.json --출력 검증결과.json --표 판정표_초안.md

입력 JSON(주장목록) 한 항목 예
  {"번호": "C3", "주장": "…초안 문장…", "doi": "10.1007/s004290050082",
   "기대": {"제목": "…", "제1저자": "Richardson", "연도": 1997, "학술지": "Anatomy and Embryology", "권": "196", "쪽": "91-106"},
   "인용문": ["fraud"], "원문파일": "원문/richardson1997.txt"}
  - doi가 없으면 "서지"(예: "Richardson 1998 Haeckel embryos evolution Science")를 주면 Crossref에서 후보 DOI를 찾아 줍니다(자동 채택 안 함).
  - "학술지"가 DOI 없는 창조과학 학술지(ARJ·Journal of Creation·CRSQ·ORJ 등)면 '원문 PDF 대조 필요'로 표시합니다.

API 예절
  - Crossref에는 연락처 이메일(mailto)을 붙이면 '예의 바른 경로'로 처리됩니다.
    --이메일 또는 환경변수 BLOG_CONTACT_EMAIL 로 주세요. 비워 두면 공용 경로(더 느림)로 갑니다.
  - 요청 사이에 --간격 초(기본 1초)만큼 쉽니다. 429(너무 많음)가 오면 기다렸다 다시 시도합니다.
  - OpenAlex 무료 키가 있으면 환경변수 OPENALEX_API_KEY 에 넣어 두세요(없어도 됩니다).

결과의 '자동판정'은 참고용입니다. 최종 판정은 맥락(앞뒤 문단)을 확인한 뒤 사람이 정합니다.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

VERSION = "1.1"
HOME = os.environ.get("BLOG_TOOL_URL", "").strip()  # (선택) 도구 안내 주소. 기본은 비움
MAX_WAIT = 60  # 서버가 이보다 오래 기다리라고 하면 기다리지 않고 알려 줌
NO_DOI_JOURNALS = [
    # 조사 03 3-4: Crossref에 DOI가 등록돼 있지 않은 창조과학 학술지
    "answers research journal", "arj",
    "journal of creation", "creation ex nihilo technical journal", "tj",
    "creation research society quarterly", "crsq",
    "origin research journal", "orj",
]
RETRACT_WORDS = ("retraction", "retracted", "withdrawal", "withdrawn", "removal")
FIX_WORDS = ("correction", "erratum", "corrigendum", "expression_of_concern", "expression-of-concern", "addendum")


# ───────────────────────── HTTP ─────────────────────────
class Http:
    def __init__(self, email: str, gap: float, cache_path: str | None):
        self.email = email.strip()
        self.gap = max(gap, 0.2)
        self.last = 0.0
        contact = "; ".join(x for x in (HOME, f"mailto:{self.email}" if self.email else "") if x) or "no contact set"
        self.ua = f"GEA-blog-factcheck/{VERSION} ({contact}) python-urllib"
        self.cache_path = cache_path
        self.cache: dict = {}
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (OSError, json.JSONDecodeError):
                self.cache = {}

    def scrub(self, text: str) -> str:
        """캐시·화면에 남기면 안 되는 값(API 키·이메일)을 지움(보안 검수 L11)."""
        text = re.sub(r"([?&])(api_key|mailto)=[^&\s\"']*&?", r"\1", text).rstrip("?&")
        for secret in (self.email, os.environ.get("OPENALEX_API_KEY", "").strip()):
            if secret:
                text = text.replace(secret, "[지움]").replace(urllib.parse.quote(secret), "[지움]")
        return text

    def save_cache(self):
        if not self.cache_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        body = self.scrub(json.dumps(self.cache, ensure_ascii=False))  # 내용에 섞였을 수 있는 키·이메일도 지움
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write(body)

    def get(self, url: str, want: str = "json", tries: int = 4):
        """want: json | text. 반환 (상태코드, 내용). 네트워크 오류는 (0, 오류문구)."""
        key = want + " " + self.scrub(url)  # 캐시 키에 API 키·이메일을 남기지 않음
        if key in self.cache:
            return self.cache[key]
        for attempt in range(tries):
            wait = self.gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    raw = r.read()
                    body = raw.decode("utf-8", errors="replace")
                    out = (r.status, json.loads(body) if want == "json" else body)
                    self.cache[key] = out
                    return out
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < tries - 1:
                    ra = e.headers.get("Retry-After")
                    pause = float(ra) if ra and ra.isdigit() else 5 * (attempt + 1)
                    if pause > MAX_WAIT:
                        print(f"  ! {e.code} 응답: 서버가 {pause:.0f}초 뒤에 다시 하라고 합니다. 기다리지 않고 이 항목은 "
                              "'확인 못 함'으로 둡니다. 잠시 뒤 --캐시와 함께 다시 실행하세요.", file=sys.stderr)
                        return (e.code, "요청 한도 초과")
                    print(f"  … {e.code} 응답, {pause:.0f}초 기다렸다 다시 시도", file=sys.stderr)
                    time.sleep(pause)
                    continue
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                if want == "json":
                    try:
                        out = (e.code, json.loads(body))
                    except json.JSONDecodeError:
                        out = (e.code, body[:300])
                else:
                    out = (e.code, body[:300])
                if e.code in (400, 404, 410):
                    self.cache[key] = out
                return out
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < tries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                return (0, f"네트워크 오류: {e}")
        return (0, "다시 시도 횟수 초과")


# ───────────────────────── 글자 정리 ─────────────────────────
def norm_doi(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s, flags=re.I)
    return s.strip().rstrip(".")


def fold(s: str) -> str:
    """비교용: 악센트 제거, 소문자, 따옴표·하이픈 통일, 공백 하나로."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[‘’‚‛′`´]", "'", s)
    s = re.sub(r"[“”„‟″]", '"', s)
    s = re.sub(r"[‐-―−]", "-", s)
    s = re.sub(r"-\s*\n\s*", "", s)  # 줄 끝 하이픈 이어 붙이기
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def title_key(s: str) -> str:
    return re.sub(r"[^a-z0-9가-힣 ]", "", fold(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def strip_tags(s: str) -> str:
    # 이스케이프된 태그(&lt;jats:p&gt;)도 지우도록: 풀기 → 태그 지우기 → 한 번 더
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    s = re.sub(r"<[^>]+>", " ", html.unescape(s))
    return re.sub(r"\s+", " ", s).strip()


def inverted_to_text(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {}
    for w, ps in inv.items():
        for p in ps:
            pos[p] = w
    return " ".join(pos[i] for i in sorted(pos))


def year_of(msg: dict) -> int | None:
    for k in ("published-print", "published-online", "issued", "created"):
        dp = (msg.get(k) or {}).get("date-parts") or []
        if dp and dp[0] and dp[0][0]:
            return int(dp[0][0])
    return None


def snippet(text: str, idx: int, n: int, width: int = 160) -> str:
    a, b = max(0, idx - width), min(len(text), idx + n + width)
    return ("…" if a > 0 else "") + text[a:b] + ("…" if b < len(text) else "")


# ───────────────────────── 각 API ─────────────────────────
def check_handle(http: Http, doi: str) -> dict:
    code, data = http.get("https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/"))
    rc = data.get("responseCode") if isinstance(data, dict) else None
    meaning = {1: "있음", 100: "없는 DOI", 200: "값 없음", 2: "오류"}.get(rc, "확인 못 함")
    return {"응답코드": rc, "결과": meaning, "http": code}


def check_ra(http: Http, doi: str) -> str:
    code, data = http.get("https://doi.org/ra/" + urllib.parse.quote(doi, safe="/"))
    if code == 200 and isinstance(data, list) and data:
        return data[0].get("RA") or data[0].get("status", "")
    return ""


def crossref_work(http: Http, doi: str) -> dict:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    # 연락처 이메일은 URL에 넣지 않고 User-Agent에만 넣음(보안 검수 L11)
    code, data = http.get(url)
    if code != 200 or not isinstance(data, dict):
        return {"찾음": False, "http": code}
    m = data.get("message", {})
    authors = []
    for a in m.get("author", []) or []:
        authors.append((a.get("family") or a.get("name") or "").strip() + (", " + a["given"] if a.get("given") else ""))
    updated_by = []
    for u in m.get("updated-by", []) or []:
        updated_by.append({"종류": u.get("type", ""), "DOI": u.get("DOI", ""), "출처": u.get("source", ""),
                           "표시": u.get("label", "")})
    update_to = [{"종류": u.get("type", ""), "DOI": u.get("DOI", "")} for u in (m.get("update-to") or [])]
    return {
        "찾음": True,
        "제목": strip_tags((m.get("title") or [""])[0]),
        "부제": strip_tags((m.get("subtitle") or [""])[0]) if m.get("subtitle") else "",
        "저자": authors,
        "연도": year_of(m),
        "학술지": strip_tags((m.get("container-title") or [""])[0]) if m.get("container-title") else "",
        "권": m.get("volume", ""),
        "호": m.get("issue", ""),
        "쪽": m.get("page", ""),
        "종류": m.get("type", ""),
        "출판사": m.get("publisher", ""),
        "초록": strip_tags(m.get("abstract", "")),
        "updated_by": updated_by,
        "update_to": update_to,
    }


def crossref_updates(http: Http, doi: str) -> list:
    url = "https://api.crossref.org/works?rows=10&filter=updates:" + urllib.parse.quote(doi, safe="")
    # 연락처 이메일은 URL에 넣지 않고 User-Agent에만 넣음(보안 검수 L11)
    code, data = http.get(url)
    out = []
    if code == 200 and isinstance(data, dict):
        for it in data.get("message", {}).get("items", []) or []:
            kinds = [u.get("type", "") for u in it.get("update-to", []) if norm_doi(u.get("DOI", "")).lower() == doi.lower()]
            out.append({"공지DOI": it.get("DOI", ""), "종류": ",".join(kinds) or it.get("type", ""),
                        "제목": strip_tags((it.get("title") or [""])[0])})
    return out


def openalex_work(http: Http, doi: str) -> dict:
    url = "https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(doi, safe="/")
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        url += "?api_key=" + urllib.parse.quote(key)
    code, data = http.get(url)
    if code != 200 or not isinstance(data, dict):
        return {"찾음": False, "http": code}
    oa = data.get("open_access") or {}
    best = data.get("best_oa_location") or {}
    first = ""
    if data.get("authorships"):
        first = ((data["authorships"][0].get("author") or {}).get("display_name") or "")
    ids = data.get("ids") or {}
    return {
        "찾음": True,
        "제목": data.get("title") or "",
        "연도": data.get("publication_year"),
        "제1저자": first,
        "철회": bool(data.get("is_retracted")),
        "오픈액세스": bool(oa.get("is_oa")),
        "원문URL": oa.get("oa_url") or best.get("pdf_url") or best.get("landing_page_url") or "",
        "초록": inverted_to_text(data.get("abstract_inverted_index")),
        "종류": data.get("type", ""),
        "pmid": (ids.get("pmid") or "").rsplit("/", 1)[-1],
        "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1],
        "피인용수": data.get("cited_by_count"),
    }


def europepmc(http: Http, doi: str) -> dict:
    q = urllib.parse.quote('DOI:"%s"' % doi)
    code, data = http.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=" + q
                          + "&resultType=core&format=json&pageSize=1")
    if code != 200 or not isinstance(data, dict):
        return {"찾음": False, "http": code}
    res = (data.get("resultList") or {}).get("result") or []
    if not res:
        return {"찾음": False, "http": code}
    r = res[0]
    types = ((r.get("pubTypeList") or {}).get("pubType")) or []
    if isinstance(types, str):
        types = [types]
    out = {
        "찾음": True,
        "제목": r.get("title", ""),
        "연도": int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
        "쪽": r.get("pageInfo", ""),
        "글종류": types,
        "초록": strip_tags(r.get("abstractText", "")),
        "pmcid": r.get("pmcid", ""),
        "오픈액세스": r.get("isOpenAccess") == "Y",
        "본문": "",
    }
    if out["pmcid"] and out["오픈액세스"]:
        c2, xml = http.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{out['pmcid']}/fullTextXML", want="text")
        if c2 == 200 and isinstance(xml, str) and "<body" in xml:
            out["본문"] = strip_tags(xml)
    return out


def crossref_find(http: Http, bib: str, rows: int = 3) -> list:
    url = ("https://api.crossref.org/works?rows=%d&query.bibliographic=%s" % (rows, urllib.parse.quote(bib)))
    # 연락처 이메일은 URL에 넣지 않고 User-Agent에만 넣음(보안 검수 L11)
    code, data = http.get(url)
    out = []
    if code == 200 and isinstance(data, dict):
        for it in data.get("message", {}).get("items", []) or []:
            out.append({
                "DOI": it.get("DOI", ""),
                "제목": strip_tags((it.get("title") or [""])[0]),
                "제1저자": ((it.get("author") or [{}])[0].get("family") or ""),
                "연도": year_of(it),
                "학술지": strip_tags((it.get("container-title") or [""])[0]) if it.get("container-title") else "",
                "점수": round(float(it.get("score", 0)), 1),
            })
    return out


# ───────────────────────── 판정 ─────────────────────────
def genre(cr: dict, ep: dict) -> str:
    types = [t.lower() for t in (ep.get("글종류") or [])]
    if any("retracted publication" in t for t in types):
        return "철회된 논문"
    for key, name in (("news", "뉴스 기사"), ("letter", "독자 서한"), ("comment", "논평"),
                      ("editorial", "사설"), ("review", "리뷰 논문")):
        if any(key in t for t in types):
            return name
    t = (cr.get("종류") or "").lower()
    return {"journal-article": "학술지 글", "book": "단행본", "monograph": "단행본", "book-chapter": "책의 장",
            "proceedings-article": "학술대회 논문", "posted-content": "프리프린트", "dataset": "데이터"}.get(t, t or "알 수 없음")


def norm_pages(s) -> str:
    """'1435-1435' → '1435', '91–106' → '91-106', '983, 985-6' → '983'(첫 범위만)"""
    s = re.sub(r"\s", "", re.sub(r"[‐-―−]", "-", str(s or "")))
    s = s.split(",")[0]
    a, _, b = s.partition("-")
    if b and len(b) < len(a) and b.isdigit() and a.isdigit():  # 495-28 → 495-528
        b = a[: len(a) - len(b)] + b
    return a if (not b or a == b) else f"{a}-{b}"


def compare_meta(expect: dict, cr: dict, oa: dict, ep: dict) -> list:
    """기대(초안에 적힌 서지) ↔ 실제. 각 항목 (항목, 판정, 설명)."""
    rows = []
    real_title = cr.get("제목") or oa.get("제목") or ep.get("제목") or ""
    if cr.get("부제"):
        real_title_full = real_title + ": " + cr["부제"]
    else:
        real_title_full = real_title
    real_year = cr.get("연도") or oa.get("연도") or ep.get("연도")
    real_first = ""
    if cr.get("저자"):
        real_first = cr["저자"][0].split(",")[0]
    elif oa.get("제1저자"):
        real_first = oa["제1저자"].split()[-1]
    if expect.get("제목"):
        a, b = title_key(expect["제목"]), title_key(real_title_full)
        r = max(difflib.SequenceMatcher(None, a, b).ratio(), difflib.SequenceMatcher(None, a, title_key(real_title)).ratio())
        v = "✅" if r >= 0.9 else ("⚠️" if r >= 0.7 else "❌")
        rows.append(("제목", v, f"유사도 {r:.2f} / 실제: {real_title_full}"))
    if expect.get("제1저자"):
        ok = fold(expect["제1저자"]).split(",")[0].strip() == fold(real_first)
        rows.append(("제1저자", "✅" if ok else "❌", f"실제: {real_first or '확인 못 함'}"))
    if expect.get("연도"):
        try:
            ey = int(expect["연도"])
            if real_year is None:
                rows.append(("연도", "확인 못 함", "실제 연도 정보 없음"))
            elif ey == real_year:
                rows.append(("연도", "✅", f"실제: {real_year}"))
            elif abs(ey - real_year) == 1:
                rows.append(("연도", "⚠️", f"실제: {real_year} (온라인 선공개·인쇄 연도 차이일 수 있음)"))
            else:
                rows.append(("연도", "❌", f"실제: {real_year}"))
        except (TypeError, ValueError):
            rows.append(("연도", "확인 못 함", "기대 연도를 숫자로 읽지 못함"))
    if expect.get("학술지"):
        a, b = title_key(expect["학술지"]), title_key(cr.get("학술지", ""))
        ok = bool(b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)
        rows.append(("학술지", "✅" if ok else ("확인 못 함" if not b else "❌"), f"실제: {cr.get('학술지') or '정보 없음'}"))
    if expect.get("권"):
        ok = str(expect["권"]).strip() == str(cr.get("권", "")).strip()
        rows.append(("권", "✅" if ok else "❌", f"실제: {cr.get('권') or '정보 없음'}"))
    if expect.get("쪽"):
        e, c, p = norm_pages(expect["쪽"]), norm_pages(cr.get("쪽", "")), norm_pages(ep.get("쪽", ""))
        if e == c:
            rows.append(("쪽", "✅", f"Crossref: {c}"))
        elif p and e == p:
            rows.append(("쪽", "⚠️", f"Europe PMC/PubMed와는 같고 Crossref와 다름(Crossref: {c}, PubMed: {p}) → DOI로 고정 표기 권장"))
        else:
            rows.append(("쪽", "❌", f"Crossref: {c or '정보 없음'} / PubMed: {p or '정보 없음'}"))
    return rows


def check_quotes(quotes: list, title: str, abstract: str, body: str, body_src: str) -> list:
    out = []
    places = [("제목", title), ("초록", abstract)]
    if body:
        places.append((body_src, body))
    for q in quotes:
        fq = fold(q)
        found = []
        for name, text in places:
            ft = fold(text)
            i = ft.find(fq)
            if i >= 0:
                found.append({"위치": name, "앞뒤": snippet(ft, i, len(fq))})
        if found:
            status = "원문에서 확인" if any(f["위치"] not in ("제목", "초록") for f in found) else "제목·초록에서 확인"
            verdict = "✅"
        elif body:
            status, verdict = "원문(본문)에 없음", "❌"
        else:
            status, verdict = "원문 미확보(제목·초록에는 없음)", "확인 못 함"
        out.append({"인용문": q, "결과": status, "판정": verdict, "발견": found})
    return out


def worst(verdicts: list) -> str:
    order = {"❌": 3, "⚠️": 2, "확인 못 함": 1, "✅": 0}
    if not verdicts:
        return "확인 못 함"
    return max(verdicts, key=lambda v: order.get(v, 1))


def is_no_doi_journal(name: str) -> bool:
    k = title_key(name)
    return any(k == j or (len(j) > 4 and j in k) for j in NO_DOI_JOURNALS)


def verify_item(http: Http, item: dict, base_dir: str) -> dict:
    now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    res = {"번호": item.get("번호", ""), "주장": item.get("주장", ""), "확인시각": now, "근거API": []}
    doi = norm_doi(item.get("doi", ""))
    expect = item.get("기대") or {}
    quotes = item.get("인용문") or []
    if isinstance(quotes, str):
        quotes = [quotes]

    if not doi:
        jn = expect.get("학술지", "") or item.get("학술지", "")
        if jn and is_no_doi_journal(jn):
            res["자동판정"] = "확인 못 함"
            res["메모"] = (f"'{jn}'은(는) DOI가 없는 학술지입니다(조사 03 3-4). 학술지 누리집의 원문 PDF를 "
                         "내려받아 제목·저자·연도·쪽과 인용문을 직접 대조해야 합니다. 원문 PDF를 주시면 대조합니다.")
            return res
        if item.get("서지"):
            res["후보DOI"] = crossref_find(http, item["서지"])
            res["근거API"].append("Crossref query.bibliographic")
            res["자동판정"] = "확인 못 함"
            res["메모"] = "DOI가 없어 후보만 찾았습니다. 후보 중 맞는 것을 사람이 고른 뒤 다시 검증하세요."
            return res
        res["자동판정"] = "확인 못 함"
        res["메모"] = "DOI도 서지 문자열도 없습니다. 출처(저자·연도·제목)를 먼저 확보해야 합니다."
        return res

    res["doi"] = doi
    h = check_handle(http, doi)
    res["doi존재"] = h
    res["근거API"].append("doi.org handles")
    if h["응답코드"] == 100:
        res["자동판정"] = "❌"
        res["메모"] = "doi.org에 없는 DOI입니다. 오타이거나 지어낸 인용일 수 있습니다."
        return res

    cr = crossref_work(http, doi)
    res["근거API"].append("Crossref works")
    if not cr.get("찾음"):
        ra = check_ra(http, doi)
        res["등록기관"] = ra
        cr = {}
    upd = crossref_updates(http, doi) if cr else []
    if cr:
        res["근거API"].append("Crossref filter=updates")
    oa = openalex_work(http, doi)
    res["근거API"].append("OpenAlex works")
    ep = europepmc(http, doi)
    res["근거API"].append("Europe PMC search")

    res["서지"] = {
        "제목": cr.get("제목") or oa.get("제목") or ep.get("제목") or "",
        "저자": cr.get("저자") or ([oa["제1저자"]] if oa.get("제1저자") else []),
        "연도": cr.get("연도") or oa.get("연도") or ep.get("연도"),
        "학술지": cr.get("학술지", ""), "권": cr.get("권", ""), "호": cr.get("호", ""),
        "쪽(Crossref)": cr.get("쪽", ""), "쪽(PubMed)": ep.get("쪽", ""),
        "글종류": genre(cr, ep), "피인용수(OpenAlex)": oa.get("피인용수"),
    }

    # 철회·정정
    kinds = [u["종류"].lower() for u in cr.get("updated_by", [])] + [u["종류"].lower() for u in upd]
    retracted = oa.get("철회") or any(any(w in k for w in RETRACT_WORDS) for k in kinds) \
        or "철회된 논문" == res["서지"]["글종류"]
    fixed = [k for k in kinds if any(w in k for w in FIX_WORDS)]
    res["철회정정"] = {
        "철회": bool(retracted),
        "정정·우려표명": fixed,
        "Crossref_updated_by": cr.get("updated_by", []),
        "Crossref_고친공지": upd,
        "OpenAlex_is_retracted": oa.get("철회") if oa.get("찾음") else None,
        "이DOI가공지인가": cr.get("update_to", []),
    }

    # 원문 확보
    abstract = oa.get("초록") or cr.get("초록") or ep.get("초록") or ""
    body, body_src = "", ""
    if item.get("원문파일"):
        p = item["원문파일"]
        if not os.path.isabs(p):
            p = os.path.join(base_dir, p)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                body, body_src = f.read(), "본문(원문파일)"
        except OSError as e:
            res["원문파일오류"] = str(e)
    if not body and ep.get("본문"):
        body, body_src = ep["본문"], "본문(Europe PMC)"
    res["원문"] = {
        "초록": "있음" if abstract else "없음",
        "본문": body_src or "미확보",
        "무료원문URL": oa.get("원문URL", ""),
        "초록문": abstract[:4000],  # 맥락 점검용(내부 확인용, 블로그에 옮기지 않음)
    }

    meta_rows = compare_meta(expect, cr, oa, ep) if expect else []
    res["서지대조"] = [{"항목": a, "판정": b, "설명": c} for a, b, c in meta_rows]
    res["인용문대조"] = check_quotes(quotes, res["서지"]["제목"], abstract, body, body_src) if quotes else []

    verdicts = [r[1] for r in meta_rows] + [q["판정"] for q in res["인용문대조"]]
    memo = []
    if retracted:
        verdicts.append("❌")
        memo.append("철회된 논문입니다. 근거로 쓰면 안 됩니다(철회 사실 자체를 다루는 글이 아니라면).")
    if fixed:
        verdicts.append("⚠️")
        memo.append("정정·우려 표명 공지가 있습니다. 공지 내용을 확인하세요: " + ", ".join(fixed))
    if res["서지"]["글종류"] in ("뉴스 기사", "독자 서한", "논평", "사설"):
        memo.append(f"이 DOI는 '{res['서지']['글종류']}'입니다. 연구 논문처럼 소개하지 않도록 장르를 밝혀 쓰세요.")
    if cr.get("쪽") and ep.get("쪽") and norm_pages(cr["쪽"]).split("-")[0] != norm_pages(ep["쪽"]).split("-")[0]:
        memo.append(f"쪽수가 Crossref({cr['쪽']})와 PubMed({ep['쪽']})에서 다릅니다 → DOI로 고정해 표기하세요.")
    if not cr and not oa.get("찾음"):
        memo.append("Crossref·OpenAlex 모두에서 찾지 못했습니다." + (f" 등록기관: {res.get('등록기관')}" if res.get("등록기관") else ""))
    res["자동판정"] = worst(verdicts) if verdicts else ("✅" if (cr or oa.get("찾음")) and not retracted else "확인 못 함")
    res["메모"] = " ".join(memo)
    return res


# ───────────────────────── 출력 ─────────────────────────
def md_table(results: list) -> str:
    lines = [
        "| 번호 | DOI | 서지(확인된 것) | 글 종류 | 철회·정정 | 서지 대조 | 인용문 대조 | 자동판정 | 메모 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        b = r.get("서지", {})
        first = (b.get("저자") or [""])[0].split(",")[0] if b.get("저자") else ""
        jn = f" *{b['학술지']}* {b.get('권', '')}" if b.get("학술지") else ""
        bib = f"{first} {b.get('연도', '')}. {b.get('제목', '')}.{jn}" if b else ""
        cc = r.get("철회정정", {})
        rc = "철회" if cc.get("철회") else ("정정 있음" if cc.get("정정·우려표명") else ("없음" if cc else "-"))
        meta = "; ".join(f"{m['항목']} {m['판정']}" for m in r.get("서지대조", [])) or "-"
        qs = "; ".join(f"'{q['인용문']}' → {q['결과']}" + (f"({', '.join(f['위치'] for f in q['발견'])})" if q['발견'] else "")
                       for q in r.get("인용문대조", [])) or "-"
        memo = r.get("메모", "").replace("|", "/")
        lines.append(f"| {r.get('번호', '')} | {r.get('doi', '-')} | {bib.strip()} | {b.get('글종류', '-') if b else '-'} | {rc} "
                     f"| {meta} | {qs} | {r.get('자동판정', '')} | {memo} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="DOI로 서지·철회·인용문을 확인합니다 (표준 라이브러리만 사용).")
    ap.add_argument("--doi", nargs="*", default=[], help="확인할 DOI들")
    ap.add_argument("--입력", "--input", dest="input", help="주장목록 JSON 파일")
    ap.add_argument("--출력", "--output", dest="output", help="결과 JSON 파일(없으면 화면에만)")
    ap.add_argument("--표", "--table", dest="table", help="판정표 초안(마크다운) 저장 경로")
    ap.add_argument("--이메일", "--mailto", dest="email", default=os.environ.get("BLOG_CONTACT_EMAIL", ""),
                    help="Crossref 연락처(mailto). 기본: 환경변수 BLOG_CONTACT_EMAIL, 없으면 비움")
    ap.add_argument("--간격", "--gap", dest="gap", type=float, default=1.0, help="요청 사이 쉬는 초(기본 1)")
    ap.add_argument("--캐시", "--cache", dest="cache", default=None, help="응답 캐시 JSON 경로(다시 돌릴 때 빠름)")
    a = ap.parse_args()

    items = []
    base_dir = os.getcwd()
    if a.input:
        with open(a.input, encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("주장", [])
        base_dir = os.path.dirname(os.path.abspath(a.input))
    for i, d in enumerate(a.doi, 1):
        items.append({"번호": f"D{i}", "doi": d})
    if not items:
        ap.error("--doi 또는 --입력 중 하나는 있어야 합니다.")

    http = Http(a.email, a.gap, a.cache)
    if not http.email:
        print("※ 연락처 이메일이 비어 있어 Crossref 공용 경로로 조회합니다(느릴 수 있음). "
              "--이메일 또는 환경변수 BLOG_CONTACT_EMAIL 로 설정할 수 있습니다.", file=sys.stderr)
    results = []
    for it in items:
        label = it.get("번호", "") + " " + (norm_doi(it.get("doi", "")) or it.get("서지", "") or "(출처 없음)")
        print(f"확인 중: {label}", file=sys.stderr)
        results.append(verify_item(http, it, base_dir))
    http.save_cache()

    out = {"도구": f"인용검증.py {VERSION}", "실행시각": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "연락처사용": bool(http.email), "결과": results}
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        with open(a.output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    if a.table:
        os.makedirs(os.path.dirname(os.path.abspath(a.table)), exist_ok=True)
        with open(a.table, "w", encoding="utf-8") as f:
            f.write("<!-- 인용검증.py 자동 생성 초안. 최종 판정은 맥락 확인 후 사람이 정합니다. -->\n\n")
            f.write(md_table(results))
    if not a.output:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    summary = {"건수": len(results), "판정": {}}
    for r in results:
        summary["판정"][r["자동판정"]] = summary["판정"].get(r["자동판정"], 0) + 1
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
