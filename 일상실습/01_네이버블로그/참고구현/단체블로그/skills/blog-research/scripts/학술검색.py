# -*- coding: utf-8 -*-
"""학술검색.py — 주제어로 학술 자료를 찾아 '출처 카드' 초안을 만듭니다.

표준 라이브러리만 씁니다(설치할 것 없음). Windows·Mac 공용.

찾는 곳 (모두 무료·공식 API)
  openalex   : 전 분야. 피인용수·오픈액세스 정보. (키 없이 하루 사용액 $0.10 → 검색 약 100회)
  crossref   : DOI가 있는 거의 모든 학술 자료. 서지 정확도가 높음
  europepmc  : 생명과학·의학. 초록과 글 종류(뉴스·서한·리뷰)를 알려 줌
  ※ 구글 스칼라는 자동으로 조회하지 않습니다(공식 API 없음, robots.txt·약관상 자동 수집 금지).
     사람이 브라우저에서 보조로 확인하는 것은 괜찮습니다.

사용 예
  python 학술검색.py --검색어 "Haeckel embryo drawings" --개수 8 --출력 출처카드_후보.md
  python 학술검색.py --검색어 "Haeckel embryos fraud" --곳 crossref,europepmc --연도 1990-2025
  python 학술검색.py --doi 10.1007/s004290050082 10.1086/504734 --출력 출처카드_DOI.md

옵션
  --이메일  Crossref·OpenAlex 연락처. 기본은 환경변수 BLOG_CONTACT_EMAIL, 없으면 비움(공용 경로, 느릴 수 있음)
  --간격    요청 사이 쉬는 초(기본 1)
  --json    카드 원자료를 JSON으로도 저장

카드의 '핵심 문장 후보'는 초록에서 자동으로 뽑은 것입니다. 원문을 확인하기 전에는 '불확실'로 둡니다.
"""
from __future__ import annotations

import argparse
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
MAX_WAIT = 60  # 서버가 이보다 오래 기다리라고 하면 기다리지 않고 알려 줌


class Http:
    def __init__(self, email: str, gap: float):
        self.email = email.strip()
        self.gap = max(gap, 0.2)
        self.last = 0.0
        contact = "; ".join(x for x in (HOME, f"mailto:{self.email}" if self.email else "") if x) or "no contact set"
        self.ua = f"GEA-blog-research/{VERSION} ({contact}) python-urllib"
        self.openalex_left = None

    def get(self, url: str, tries: int = 4):
        for attempt in range(tries):
            wait = self.gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": self.ua})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    if "openalex" in url:
                        self.openalex_left = r.headers.get("X-RateLimit-Remaining-USD", self.openalex_left)
                    return r.status, json.loads(r.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < tries - 1:
                    ra = e.headers.get("Retry-After")
                    pause = float(ra) if ra and ra.isdigit() else 5 * (attempt + 1)
                    if pause > MAX_WAIT:
                        print(f"  ! {e.code} 응답: 서버가 {pause:.0f}초 뒤에 다시 하라고 합니다. 기다리지 않고 멈춥니다.",
                              file=sys.stderr)
                        return e.code, None
                    print(f"  … {e.code} 응답, {pause:.0f}초 기다렸다 다시 시도", file=sys.stderr)
                    time.sleep(pause)
                    continue
                return e.code, None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < tries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                print(f"  ! 네트워크 오류: {e}", file=sys.stderr)
                return 0, None
        return 0, None


def strip_tags(s: str) -> str:
    # 이스케이프된 태그(&lt;subtitle&gt;)도 지우도록: 풀기 → 태그 지우기 → 한 번 더
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    s = re.sub(r"<[^>]+>", " ", html.unescape(s))
    return re.sub(r"\s+", " ", s).strip()


def inverted_to_text(inv):
    if not inv:
        return ""
    pos = {}
    for w, ps in inv.items():
        for p in ps:
            pos[p] = w
    return " ".join(pos[i] for i in sorted(pos))


def first_sentences(text: str, n: int = 2, limit: int = 320) -> str:
    """초록 앞 두 문장. 옛 책은 '초록' 자리에 본문 OCR이 통째로 오기도 하므로 길이를 자릅니다."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = " ".join(parts[:n]).strip()
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + " …"


def norm_doi(s: str) -> str:
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (s or "").strip(), flags=re.I).lower()


def year_of(m: dict):
    for k in ("published-print", "published-online", "issued"):
        dp = (m.get(k) or {}).get("date-parts") or []
        if dp and dp[0] and dp[0][0]:
            return int(dp[0][0])
    return None


def card(**kw) -> dict:
    base = {"제목": "", "저자": [], "연도": None, "학술지": "", "권": "", "쪽": "", "doi": "", "url": "",
            "글종류": "", "피인용수": None, "오픈액세스": None, "초록": "", "찾은곳": []}
    base.update(kw)
    return base


# ───────── 각 API ─────────
def from_openalex(http: Http, q: str, n: int, years: str | None) -> list:
    flt = []
    if years:
        a, _, b = years.partition("-")
        flt.append(f"publication_year:{a}-{b}" if b else f"publication_year:{a}")
    url = "https://api.openalex.org/works?per-page=%d&search=%s" % (n, urllib.parse.quote(q))
    if flt:
        url += "&filter=" + ",".join(flt)
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        url += "&api_key=" + urllib.parse.quote(key)  # 요청에만 씀 — 이 주소는 파일·화면에 남기지 않음(L11)
    code, data = http.get(url)
    out = []
    for w in (data or {}).get("results", []) if code == 200 else []:
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {})
        bib = w.get("biblio") or {}
        pages = "-".join(x for x in (bib.get("first_page"), bib.get("last_page")) if x)
        out.append(card(
            제목=w.get("title") or "", 저자=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])[:6]],
            연도=w.get("publication_year"), 학술지=src.get("display_name") or "", 권=bib.get("volume") or "", 쪽=pages,
            doi=norm_doi(w.get("doi") or ""), url=(w.get("open_access") or {}).get("oa_url") or loc.get("landing_page_url") or "",
            글종류=w.get("type") or "", 피인용수=w.get("cited_by_count"), 오픈액세스=(w.get("open_access") or {}).get("is_oa"),
            초록=inverted_to_text(w.get("abstract_inverted_index")), 찾은곳=["OpenAlex"],
            철회=bool(w.get("is_retracted"))))
    return out


def from_crossref(http: Http, q: str, n: int, years: str | None) -> list:
    url = "https://api.crossref.org/works?rows=%d&query.bibliographic=%s" % (n, urllib.parse.quote(q))
    if years:
        a, _, b = years.partition("-")
        url += f"&filter=from-pub-date:{a},until-pub-date:{b or a}"
    # 연락처 이메일은 URL에 넣지 않고 User-Agent에만 넣음(보안 검수 L11)
    code, data = http.get(url)
    out = []
    for m in (data or {}).get("message", {}).get("items", []) if code == 200 else []:
        out.append(card(
            제목=strip_tags((m.get("title") or [""])[0]),
            저자=[(a.get("family") or a.get("name") or "") + (", " + a["given"] if a.get("given") else "") for a in (m.get("author") or [])[:6]],
            연도=year_of(m), 학술지=strip_tags((m.get("container-title") or [""])[0]) if m.get("container-title") else "",
            권=m.get("volume", ""), 쪽=m.get("page", ""), doi=norm_doi(m.get("DOI", "")), url=m.get("URL", ""),
            글종류=m.get("type", ""), 초록=strip_tags(m.get("abstract", "")), 찾은곳=["Crossref"],
            정정공지=[u.get("type") for u in (m.get("updated-by") or [])]))
    return out


def from_europepmc(http: Http, q: str, n: int, years: str | None) -> list:
    # 그냥 검색하면 본문 전체에서 찾아 관련 없는 논문이 섞임 → 제목·초록에서만 찾기
    query = q if (":" in q or q.startswith("(")) else f"TITLE_ABS:({q})"
    if years:
        a, _, b = years.partition("-")
        query += f" AND PUB_YEAR:[{a} TO {b or a}]"
    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?resultType=core&format=json&pageSize=%d&query=%s"
           % (n, urllib.parse.quote(query)))
    code, data = http.get(url)
    out = []
    for r in ((data or {}).get("resultList") or {}).get("result", []) if code == 200 else []:
        types = ((r.get("pubTypeList") or {}).get("pubType")) or []
        if isinstance(types, str):
            types = [types]
        out.append(card(
            제목=strip_tags(r.get("title", "")), 저자=[x.strip() for x in (r.get("authorString") or "").split(",")[:6] if x.strip()],
            연도=int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
            학술지=((r.get("journalInfo") or {}).get("journal") or {}).get("title", ""),
            권=(r.get("journalInfo") or {}).get("volume", ""), 쪽=r.get("pageInfo", ""), doi=norm_doi(r.get("doi", "")),
            url=("https://europepmc.org/article/MED/" + r["pmid"]) if r.get("pmid") else "",
            글종류=", ".join(types), 오픈액세스=r.get("isOpenAccess") == "Y", 초록=strip_tags(r.get("abstractText", "")),
            찾은곳=["Europe PMC"]))
    return out


def by_doi(http: Http, doi: str) -> dict | None:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    # 연락처 이메일은 URL에 넣지 않고 User-Agent에만 넣음(보안 검수 L11)
    code, data = http.get(url)
    if code != 200 or not data:
        return None
    m = data["message"]
    c = card(
        제목=strip_tags((m.get("title") or [""])[0]),
        저자=[(a.get("family") or a.get("name") or "") + (", " + a["given"] if a.get("given") else "") for a in (m.get("author") or [])[:6]],
        연도=year_of(m), 학술지=strip_tags((m.get("container-title") or [""])[0]) if m.get("container-title") else "",
        권=m.get("volume", ""), 쪽=m.get("page", ""), doi=norm_doi(m.get("DOI", "")), url=m.get("URL", ""),
        글종류=m.get("type", ""), 초록=strip_tags(m.get("abstract", "")), 찾은곳=["Crossref"],
        정정공지=[u.get("type") for u in (m.get("updated-by") or [])])
    # 초록·글 종류 보강 (Europe PMC)
    ep = from_europepmc(http, 'DOI:"%s"' % doi, 1, None)
    if ep:
        c["글종류"] = (c["글종류"] + " / " + ep[0]["글종류"]).strip(" /")
        c["초록"] = c["초록"] or ep[0]["초록"]
        c["찾은곳"].append("Europe PMC")
    return c


def merge(cards: list) -> list:
    seen, out = {}, []
    for c in cards:
        key = c["doi"] or re.sub(r"\W+", "", c["제목"].lower())[:80]
        if key in seen:
            o = seen[key]
            for k, v in c.items():
                if k == "찾은곳":
                    o[k] = sorted(set(o[k]) | set(v))
                elif not o.get(k) and v:
                    o[k] = v
        else:
            seen[key] = c
            out.append(c)
    return out


def to_md(cards: list, header: str) -> str:
    lines = [header, ""]
    for i, c in enumerate(cards, 1):
        authors = "; ".join(a for a in c["저자"] if a) or "확인 필요"
        where = f"*{c['학술지']}*" + (f" {c['권']}" if c.get("권") else "") + (f": {c['쪽']}" if c.get("쪽") else "")
        lines += [
            f"### 후보 {i}. {c['제목'] or '(제목 없음)'}",
            f"- 저자: {authors}",
            f"- 연도: {c['연도'] or '확인 필요'} · 실린 곳: {where if c['학술지'] else '확인 필요'}",
            f"- DOI: {c['doi'] or '없음'}" + (f" · URL: {c['url']}" if c.get("url") else ""),
            f"- 글 종류: {c['글종류'] or '확인 필요'} · 피인용수(OpenAlex): {c['피인용수'] if c['피인용수'] is not None else '-'}"
            f" · 무료 원문: {'있음' if c['오픈액세스'] else ('없음' if c['오픈액세스'] is False else '확인 필요')}",
            f"- 찾은 곳: {', '.join(c['찾은곳'])}",
        ]
        if c.get("철회"):
            lines.append("- ⛔ **철회된 논문**(OpenAlex is_retracted) — 근거로 쓰지 않습니다.")
        if c.get("정정공지"):
            lines.append(f"- ⚠️ 정정·철회 공지: {', '.join(x for x in c['정정공지'] if x)}")
        if c["초록"]:
            lines.append(f"- 핵심 문장 후보(초록 자동 발췌, **불확실** — 원문 확인 전): \"{first_sentences(c['초록'])}\"")
        else:
            lines.append("- 핵심 문장 후보: 초록 없음 → 원문에서 직접 확인")
        lines += ["- 쪽수: (원문 확인 후 기입)", "- 확실/불확실: 서지=API 확인(확실) / 내용=원문 확인 전(불확실)", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="주제어로 학술 자료를 찾아 출처 카드 초안을 만듭니다.")
    ap.add_argument("--검색어", "--query", dest="query", help="찾을 말(영어 검색이 결과가 많습니다)")
    ap.add_argument("--doi", nargs="*", default=[], help="DOI로 바로 카드 만들기")
    ap.add_argument("--곳", "--sources", dest="sources", default="openalex,crossref,europepmc")
    ap.add_argument("--개수", "--rows", dest="rows", type=int, default=8, help="곳마다 가져올 개수(기본 8)")
    ap.add_argument("--연도", "--years", dest="years", help="예: 1990-2025")
    ap.add_argument("--출력", "--output", dest="output", help="마크다운 저장 경로(없으면 화면)")
    ap.add_argument("--json", dest="json_out", help="원자료 JSON 저장 경로")
    ap.add_argument("--이메일", "--mailto", dest="email", default=os.environ.get("BLOG_CONTACT_EMAIL", ""))
    ap.add_argument("--간격", "--gap", dest="gap", type=float, default=1.0)
    a = ap.parse_args()
    if not a.query and not a.doi:
        ap.error("--검색어 또는 --doi 가 필요합니다.")

    http = Http(a.email, a.gap)
    cards = []
    if a.query:
        fn = {"openalex": from_openalex, "crossref": from_crossref, "europepmc": from_europepmc}
        for s in [x.strip().lower() for x in a.sources.split(",") if x.strip()]:
            if s in ("scholar", "googlescholar", "google"):
                print("※ 구글 스칼라는 자동 조회하지 않습니다(약관·robots.txt). 건너뜁니다.", file=sys.stderr)
                continue
            if s not in fn:
                print(f"※ 모르는 곳: {s} (openalex·crossref·europepmc 중에서 고르세요)", file=sys.stderr)
                continue
            print(f"찾는 중: {s} ← {a.query}", file=sys.stderr)
            cards += fn[s](http, a.query, a.rows, a.years)
    for d in a.doi:
        print(f"DOI 카드: {d}", file=sys.stderr)
        c = by_doi(http, norm_doi(d))
        if c:
            cards.append(c)
        else:
            print(f"  ! {d}: Crossref에서 찾지 못함(오타·가짜 DOI·다른 등록기관 가능)", file=sys.stderr)
    cards = merge(cards)

    now = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    header = (f"## 학술 출처 카드 후보 — 검색어: {a.query or '(DOI 지정)'}\n\n"
              f"- 조회: {now}, 곳: {a.sources if a.query else 'Crossref(+Europe PMC)'}, 도구: 학술검색.py {VERSION}\n"
              f"- 이 목록은 **후보**입니다. 글에 쓸 것만 골라 원문을 확인한 뒤 `자료조사_<주제>.md`의 출처 카드로 옮깁니다.")
    md = to_md(cards, header)
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)
    print(json.dumps({"카드수": len(cards), "OpenAlex남은하루사용액USD": http.openalex_left}, ensure_ascii=False))


if __name__ == "__main__":
    main()
