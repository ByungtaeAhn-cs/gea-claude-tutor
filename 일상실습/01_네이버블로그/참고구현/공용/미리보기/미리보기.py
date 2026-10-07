# -*- coding: utf-8 -*-
"""미리보기.py — 배치 JSON(글 한 편)을 '네이버식 미리보기' HTML 한 파일로 만듭니다.

단체 블로그·여행 블로그 공용. 표준 라이브러리만 씁니다(설치할 것 없음). Windows·Mac 공용.
배치 JSON 형식: 여행스튜디오_규약.md 2.3 ('블록' 목록). 발행 패키지(2.4)를 넣어도 됩니다.

사용 예
  python 미리보기.py 배치_헤켈배아.json
  python 미리보기.py 배치_헤켈배아.json --출력 미리보기.html --이미지 내장
  python 미리보기.py 여행/2026-09_제주/배치_1일차.json --목록 여행/2026-09_제주/목록.json

옵션
  --이미지 상대   (기본) 이미지를 상대경로로 연결 → HTML과 이미지 폴더를 함께 옮겨야 보임
  --이미지 내장   이미지를 HTML 안에 넣음(data URI) → 파일 하나로 보낼 수 있지만 용량이 커짐
  --열기          만든 뒤 기본 브라우저(Chrome·Edge 등)로 열기 — 상대경로 그림도 잘 보임
  ※ 보안: --출력 은 배치 파일 폴더 안의 .html 만, --템플릿 은 이 스크립트와 같은 폴더의 .html 만 받습니다.
     그림 내장은 그림·영상 파일만 합니다.
  ※ Code 탭 Browser 창은 내 PC의 HTML을 '정적 스냅숏'으로 엽니다(리허설 관찰). 상대경로 그림은 안 보이고,
     약 500KB가 넘는 파일은 열리지 않았습니다. Browser 창에서 보려면 '--이미지 내장' + 사진 수·크기를 줄이거나,
     '--열기'로 기본 브라우저에서 보세요.
  --목록          여행 블로그처럼 사진을 ID(p0001)로 적었을 때 ID → 파일을 찾는 목록.json
  --기준폴더      배치 안의 상대경로를 해석할 폴더(기본: 배치 파일이 있는 폴더)

블록 종류(규약 v2 2.4): 본문 · 소제목 · 사진 · 그룹사진(콜라주/슬라이드/개별) · 영상 · 지도 · 장소 · 인용구(출처) · 꿀팁 · 구분선
  · 참고자료 {"종류":"참고자료","목록":[…],"제목"?}
맨 위 선택 키: "AI활용표시": true|false, "승인": {"상태":"미승인|승인됨","승인자","시각"} → 점검판에 표시
누수 점검: 글에 [S3] 같은 카드 번호, '내부용', '발행 금지', '예상 반론'이 남으면 '고칠 것'으로 표시
단체 블로그용 선택 키(다른 도구는 무시해도 됨)
  - 사진 블록 "자리": "무엇을 보여 줄지" → 아직 사진이 없을 때 점선 상자로 표시
  - 본문 블록 "역할": "출처" | "AI표기" → 작은 글씨로 표시(에디터에는 본문으로 입력)
  - 인용구 블록 "출처": "…" → 인용구 아래 출처 줄
  - 맨 위 "제목후보": [..] → 점검판에만 표시
마지막 줄에 JSON 요약을 출력합니다.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import html
import json
import mimetypes
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
MAX_GROUP, MAX_PLACES, MAX_TAGS, MAX_MB = 10, 5, 30, 10


class Ctx:
    def __init__(self, batch_path: str, base: str | None, list_path: str | None, embed: bool, out_path: str):
        self.batch_dir = os.path.dirname(os.path.abspath(batch_path))
        self.base = os.path.abspath(base) if base else self.batch_dir
        self.embed = embed
        self.out_dir = os.path.dirname(os.path.abspath(out_path))
        self.items, self.list_dir = {}, None
        lp = list_path
        if not lp:  # 여행 블로그: 배치 옆이나 한 단계 위의 목록.json
            for cand in (os.path.join(self.base, "목록.json"), os.path.join(os.path.dirname(self.base), "목록.json")):
                if os.path.exists(cand):
                    lp = cand
                    break
        if lp and os.path.exists(lp):
            with open(lp, encoding="utf-8") as f:
                data = json.load(f)
            seq = data if isinstance(data, list) else data.get("항목", data.get("목록", []))
            self.items = {it.get("id"): it for it in seq if isinstance(it, dict)}
            self.list_dir = os.path.dirname(os.path.abspath(lp))
        self.warn: list[str] = []
        self.problems: list[str] = []
        self.stats = {"사진": 0, "자리": 0, "없는파일": 0, "큰파일": 0}

    def find(self, rel: str) -> str | None:
        if os.path.isabs(rel):
            return rel if os.path.exists(rel) else None
        for b in (self.base, self.list_dir, self.batch_dir, os.path.dirname(self.base)):
            if b:
                p = os.path.normpath(os.path.join(b, rel))
                if os.path.exists(p):
                    return p
        return None

    def resolve(self, ref) -> str | None:
        """사진 참조 → 실제 파일 경로. 경로 문자열 / ID(목록.json) / {"파일": …}"""
        if isinstance(ref, dict):
            ref = ref.get("파일") or ref.get("경로") or ref.get("업로드") or ref.get("id") or ""
        ref = str(ref or "").strip()
        if not ref:
            return None
        looks_path = ("/" in ref or "\\" in ref or os.path.splitext(ref)[1].lower() in IMG_EXT + VID_EXT)
        if looks_path:
            return self.find(ref)
        it = self.items.get(ref)
        if it:
            for k in ("업로드사본", "미리보기", "썸네일", "원본"):
                if it.get(k):
                    p = self.find(it[k])
                    if p:
                        return p
        return None

    def src(self, path: str) -> str:
        if self.embed:
            # 보안: 그림·영상 파일만 HTML 안에 넣음(다른 파일 내용이 미리보기에 실리지 않게)
            if os.path.splitext(path)[1].lower() not in IMG_EXT + VID_EXT:
                raise ValueError(f"그림·영상 파일이 아니라서 넣지 않음: {os.path.basename(path)}")
            mime = mimetypes.guess_type(path)[0] or "image/jpeg"
            with open(path, "rb") as f:
                return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")
        return os.path.relpath(path, self.out_dir).replace("\\", "/")


def inside(path: str, folder: str) -> bool:
    """path가 folder 안(또는 그 아래)에 있는지. 바로가기를 따라간 실제 경로로, Windows 대소문자 무시."""
    p = os.path.normcase(os.path.realpath(path))
    f = os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([p, f]) == f
    except ValueError:  # 드라이브가 다름
        return False


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def inline(text: str) -> str:
    """본문 글: 이스케이프 → **굵게** → 주소 자동 링크 → 줄바꿈"""
    t = esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(https?://[^\s<]+[^\s<.,)\]])", r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)
    return t.replace("\n", "<br>")


def paragraphs(text: str, cls: str = "") -> str:
    parts = [p for p in re.split(r"\n\s*\n", str(text or "").strip()) if p.strip()]
    c = f' class="{cls}"' if cls else ""
    return "\n".join(f"<p{c}>{inline(p)}</p>" for p in parts)


def photo_refs(block: dict) -> list:
    for k in ("업로드", "파일", "사진"):
        v = block.get(k)
        if v:
            return v if isinstance(v, list) else [v]
    return []


def img_tag(ctx: Ctx, ref, alt: str = "") -> str:
    p = ctx.resolve(ref)
    ctx.stats["사진"] += 1
    if not p:
        ctx.stats["없는파일"] += 1
        ctx.problems.append(f"사진 파일을 찾지 못함: {ref}")
        return f'<div class="없음">사진 파일을 찾지 못했습니다: {esc(ref)}</div>'
    if os.path.splitext(p)[1].lower() not in IMG_EXT + VID_EXT:
        ctx.problems.append(f"그림·영상 파일이 아님: {ref}")
        return f'<div class="없음">그림·영상 파일이 아닙니다: {esc(ref)}</div>'
    mb = os.path.getsize(p) / 1048576
    if mb > MAX_MB:
        ctx.stats["큰파일"] += 1
        ctx.warn.append(f"{os.path.basename(p)}: {mb:.1f}MB → 업로드 전 10MB 이하로 줄이기")
    # loading="lazy"를 쓰지 않음: Code 탭 Browser 창(정적 스냅숏)에서 지연 로딩 그림이 끝내 안 뜨는 것을 리허설에서 확인
    return f'<img src="{esc(ctx.src(p))}" alt="{esc(alt)}">'


def render_block(ctx: Ctx, b: dict, i: int) -> str:
    kind = b.get("종류", "")
    cap = b.get("설명", "")
    if kind == "본문":
        role = b.get("역할", "")
        if role == "AI표기":
            return f'<div class="AI표기">{inline(b.get("글", ""))}</div>'
        return paragraphs(b.get("글", ""), "작게" if role == "출처" else "")
    if kind == "소제목":
        return f'<h2 class="소제목">{inline(b.get("글", ""))}</h2>'
    if kind == "인용구":
        src = f'<div class="출처">{inline(b["출처"])}</div>' if b.get("출처") else ""
        return (f'<blockquote class="인용구"><div class="따옴표">&ldquo;</div>'
                f'<div class="말">{inline(b.get("글", ""))}</div>{src}</blockquote>')
    if kind == "구분선":
        return '<hr class="구분선">'
    if kind == "꿀팁":
        return f'<div class="꿀팁"><div class="이름">꿀팁</div>{inline(b.get("글", ""))}</div>'
    if kind == "참고자료":
        items = "".join(f"<li>{inline(x)}</li>" for x in (b.get("목록") or []))
        title = esc(b.get("제목") or "참고 자료")
        return f'<div class="참고자료"><div class="이름">{title}</div><ul>{items}</ul></div>'
    if kind == "사진":
        refs = photo_refs(b)
        rep = '<span class="대표표시">대표</span>' if b.get("대표") else ""
        if not refs:
            ctx.stats["자리"] += 1
            what = b.get("자리") or "(무엇을 보여 줄지 적혀 있지 않음)"
            ctx.warn.append(f"블록 {i}: 사진 자리 — {what}")
            return (f'<figure><div class="자리"><b>사진 자리</b>{inline(what)}</div>'
                    f'{f"<figcaption>{inline(cap)}{rep}</figcaption>" if cap or rep else ""}</figure>')
        imgs = "".join(img_tag(ctx, r, cap) for r in refs)
        return f'<figure>{imgs}{f"<figcaption>{inline(cap)}{rep}</figcaption>" if cap or rep else ""}</figure>'
    if kind == "그룹사진":
        refs = photo_refs(b)
        how = b.get("방식", "콜라주")
        if len(refs) > MAX_GROUP:
            ctx.problems.append(f"블록 {i}: 그룹 사진 {len(refs)}장 → 한 묶음 {MAX_GROUP}장 이하로 나누기")
        if not refs:
            ctx.stats["자리"] += 1
            ctx.warn.append(f"블록 {i}: 그룹 사진 자리 — {b.get('자리', '')}")
            return f'<figure><div class="자리"><b>{esc(how)} 자리</b>{inline(b.get("자리", ""))}</div></figure>'
        if how == "슬라이드":
            imgs = "".join(img_tag(ctx, r, cap) for r in refs)
            body = (f'<div class="슬라이드">{imgs}<button type="button" class="앞" aria-label="이전">&#8249;</button>'
                    f'<button type="button" class="뒤" aria-label="다음">&#8250;</button><span class="번호"></span></div>')
        elif how in ("개별", "개별 사진"):
            figs = [img_tag(ctx, r, cap) for r in refs]
            last = f"<figcaption>{inline(cap)}</figcaption>" if cap else ""
            return "\n".join(f"<figure>{t}{last if k == len(figs) - 1 else ''}</figure>" for k, t in enumerate(figs))
        else:  # 콜라주
            n = len(refs)
            wide = n % 2 == 1 and n >= 3          # 홀수 장이면 첫 장을 넓게, 나머지를 격자로
            rest = n - 1 if wide else n
            cols = {1: 1, 2: 2, 4: 2, 6: 3, 8: 4, 10: 5}.get(rest, 3)
            cells = []
            for k, r in enumerate(refs):
                t = img_tag(ctx, r, cap)
                if wide and k == 0 and t.startswith("<img"):
                    t = t.replace("<img ", '<img class="넓게" ', 1)
                cells.append(t)
            body = f'<div class="콜라주" style="--칸:{cols}">{"".join(cells)}</div>'
        return f'<figure>{body}{f"<figcaption>{inline(cap)}</figcaption>" if cap else ""}</figure>'
    if kind == "영상":
        ref = b.get("영상") or b.get("업로드") or ""
        if isinstance(ref, list):
            ref = ref[0] if ref else ""
        p = ctx.resolve(ref)
        if p and p.lower().endswith(VID_EXT):
            return f'<figure><video controls preload="metadata" style="max-width:100%" src="{esc(ctx.src(p))}"></video>' \
                   f'{f"<figcaption>{inline(cap)}</figcaption>" if cap else ""}</figure>'
        if p:
            return f'<figure><span class="영상">{img_tag(ctx, ref, cap)}</span>' \
                   f'{f"<figcaption>{inline(cap)}</figcaption>" if cap else ""}</figure>'
        ctx.warn.append(f"블록 {i}: 영상 파일을 찾지 못함 — {ref}")
        return f'<figure><div class="자리"><b>영상 자리</b>{esc(ref)}</div></figure>'
    if kind == "지도":
        ref = b.get("이미지", "")
        if not ref:
            return f'<figure class="지도"><div class="자리"><b>지도 자리</b>{inline(b.get("자리", ""))}</div></figure>'
        return f'<figure class="지도">{img_tag(ctx, ref, "지도")}' \
               f'{f"<figcaption>{inline(cap)}</figcaption>" if cap else ""}</figure>'
    if kind == "장소":
        places = b.get("장소") or []
        if len(places) > MAX_PLACES:
            ctx.problems.append(f"블록 {i}: 장소 {len(places)}곳 → 에디터 '장소'는 한 번에 {MAX_PLACES}곳까지(나누기)")
        rows = "".join(f'<div class="장소"><span class="핀"></span><span>{esc(p if isinstance(p, str) else p.get("이름", ""))}</span></div>'
                       for p in places)
        return f'<div class="장소들"><div class="머리">장소 {len(places)}곳 (실제 에디터에서는 지도 카드로 보임)</div>{rows}</div>'
    ctx.warn.append(f"블록 {i}: 모르는 종류 '{kind}' → 본문으로 표시")
    return paragraphs(b.get("글", ""))


LEAK_STOP = re.compile(r"\[S\d+\]|\[담당자 확인|내부용|발행 금지|예상 ?반론")
LEAK_WARN = re.compile(r"확인 필요|TODO|XXX|\?\?\?")


def leak_check(ctx: Ctx, d: dict):
    """발행하면 안 되는 내부 표시(카드 번호·내부 메모 문구)가 글에 남았는지."""
    pairs = [("제목", d.get("제목", ""))]
    for i, b in enumerate(d.get("블록") or [], 1):
        for k in ("글", "설명", "출처"):
            if b.get(k):
                pairs.append((f"블록 {i}", str(b[k])))
        pairs += [(f"블록 {i}", str(x)) for x in (b.get("목록") or [])]
    for where, text in pairs:
        m = LEAK_STOP.search(text)
        if m:
            ctx.problems.append(f"누수: {where}에 내부 표시 '{m.group(0)}' — 지우기")
        w = LEAK_WARN.search(text)
        if w:
            ctx.warn.append(f"{where}에 '{w.group(0)}'가 남아 있음")


def checklist(ctx: Ctx, d: dict) -> str:
    tags = d.get("태그") or []
    blocks = d.get("블록") or []
    leak_check(ctx, d)
    if len(tags) > MAX_TAGS:
        ctx.problems.append(f"태그 {len(tags)}개 → {MAX_TAGS}개 이하로")
    if not d.get("제목"):
        ctx.problems.append("제목이 비어 있음")
    if "제목후보" in d and len(d.get("제목후보") or []) != 3:
        ctx.warn.append(f"제목 후보가 {len(d.get('제목후보') or [])}개(규칙: 3개)")
    has_ai = any(b.get("역할") == "AI표기" for b in blocks)
    has_src = any(b.get("역할") == "출처" or b.get("종류") == "참고자료" for b in blocks)
    out = ["<h2>작성자용 점검 <span class=\"설명\">(블로그에는 안 나옴)</span></h2>"]
    if d.get("제목후보"):
        out.append("<div><b>제목 후보</b><ul>" + "".join(f"<li>{esc(t)}</li>" for t in d["제목후보"]) + "</ul></div>")
    out.append(f"<div>카테고리: <b>{esc(d.get('카테고리', '(없음)'))}</b> · 공개: <b>{esc(d.get('공개', '(없음)'))}</b></div>")
    out.append(f"<div>블록 {len(blocks)}개 · 사진 {ctx.stats['사진']}장 · 사진 자리 {ctx.stats['자리']}곳 · 태그 {len(tags)}개</div>")
    out.append(f"<div>출처 블록: {'있음' if has_src else '없음'} · AI 사용 표기(본문): {'있음' if has_ai else '없음'}</div>")
    if "AI활용표시" in d:
        out.append(f"<div>에디터 'AI 활용 설정': <b>{'켬' if d.get('AI활용표시') else '끔'}</b></div>")
    if "승인" in d:
        ap = d.get("승인") or {}
        st = ap.get("상태", "미승인")
        who = f" ({esc(ap.get('승인자', ''))} {esc(ap.get('시각', ''))})" if st == "승인됨" else ""
        out.append(f"<div>승인: <b>{esc(st)}</b>{who}</div>")
    if ctx.problems:
        out.append('<div class="문제"><b>고칠 것</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in ctx.problems) + "</ul></div>")
    if ctx.warn:
        out.append('<div class="주의"><b>확인할 것</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in ctx.warn) + "</ul></div>")
    if not ctx.problems and not ctx.warn:
        out.append('<div class="좋음">점검에 걸린 것이 없습니다.</div>')
    out.append('<p class="설명">이 화면은 모양 참고용입니다. 사실·인용 확인은 팩트체크 판정표로 합니다.</p>')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="배치 JSON → 네이버식 미리보기 HTML")
    ap.add_argument("배치", help="배치 JSON(또는 발행 패키지 JSON)")
    ap.add_argument("--출력", "--output", dest="output")
    ap.add_argument("--이미지", "--images", dest="images", choices=["상대", "내장", "relative", "embed"], default="상대")
    ap.add_argument("--목록", "--list", dest="list_path")
    ap.add_argument("--기준폴더", "--base", dest="base")
    ap.add_argument("--템플릿", "--template", dest="template", default=os.path.join(HERE, "템플릿.html"))
    ap.add_argument("--열기", "--open", dest="open", action="store_true", help="만든 뒤 내 PC의 기본 브라우저로 열기")
    a = ap.parse_args()

    # 보안(검수 H1): 이 스크립트가 아무 곳에나 아무 내용을 쓰지 못하게
    #  - 출력은 배치 파일 폴더(그 아래 폴더 포함) 안의 .html 만
    #  - 템플릿은 이 스크립트 옆(같은 폴더)의 .html 만
    batch_dir = os.path.dirname(os.path.abspath(a.배치))
    out = os.path.abspath(a.output or os.path.splitext(os.path.abspath(a.배치))[0] + "_미리보기.html")
    if os.path.splitext(out)[1].lower() != ".html" or not inside(out, batch_dir):
        sys.exit("--출력 은 배치 파일이 있는 폴더 안의 .html 파일만 됩니다: " + out)
    if os.path.splitext(a.template)[1].lower() != ".html" or not inside(a.template, HERE):
        sys.exit("--템플릿 은 미리보기.py 와 같은 폴더의 .html 파일만 됩니다: " + a.template)

    with open(a.배치, encoding="utf-8") as f:
        d = json.load(f)
    ctx = Ctx(a.배치, a.base, a.list_path, a.images in ("내장", "embed"), out)

    body = "\n".join(render_block(ctx, b, i) for i, b in enumerate(d.get("블록") or [], 1))
    tags = " ".join(f"<span>#{esc(str(t).lstrip('#'))}</span>" for t in (d.get("태그") or []))
    today = _dt.date.today().strftime("%Y. %m. %d.")
    who = esc(d.get("글쓴이") or d.get("블로그") or "")
    with open(a.template, encoding="utf-8") as f:
        tpl = f.read()
    page = (tpl.replace("{{문서제목}}", esc("미리보기 — " + (d.get("제목") or "")))
               .replace("{{카테고리}}", esc(d.get("카테고리", "")))
               .replace("{{제목}}", esc(d.get("제목", "")))
               .replace("{{글쓴이}}", (who + " · " if who else "") + today + " (미리보기)")
               .replace("{{태그}}", tags)
               .replace("{{본문}}", body)
               .replace("{{점검}}", checklist(ctx, d)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    summary = {"미리보기": out, "블록": len(d.get("블록") or []), "사진": ctx.stats["사진"], "사진자리": ctx.stats["자리"],
               "없는파일": ctx.stats["없는파일"], "고칠것": len(ctx.problems), "확인할것": len(ctx.warn),
               "용량KB": round(os.path.getsize(out) / 1024)}
    for p in ctx.problems:
        print("고칠 것: " + p, file=sys.stderr)
    if ctx.embed and summary["용량KB"] > 500:
        print("※ 파일이 약 500KB를 넘습니다. Code 탭 Browser 창은 이보다 큰 파일을 열지 못했습니다"
              "(리허설: 500KB 열림, 520KB 거부) → --열기로 기본 브라우저에서 보거나 사진을 줄이세요.", file=sys.stderr)
    if not ctx.embed and ctx.stats["사진"]:
        print("※ 이미지가 상대경로입니다. Code 탭 Browser 창은 내 PC 파일을 '정적 스냅숏'으로 열어 상대경로 그림이 "
              "안 보입니다 → Browser 창에서 보려면 --이미지 내장, 아니면 --열기(기본 브라우저).", file=sys.stderr)
    if a.open:
        import pathlib
        import webbrowser
        webbrowser.open(pathlib.Path(out).resolve().as_uri())
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
