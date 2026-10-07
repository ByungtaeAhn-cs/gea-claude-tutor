# -*- coding: utf-8 -*-
"""문장대조.py — 다듬기 전·후 원고를 문장 단위로 맞대어, 바뀌면 안 되는 문장은 되돌리고 뜻이 바뀌었을 수 있는 문장을 표시합니다.

표준 라이브러리만 씁니다. Windows·Mac 공용.

보호 문장(바뀌면 자동 복원)
  - 카드 번호([S3])·숫자·따옴표(" " ' ' 『』「」)·영문(고유명사·학명·논문 제목)이 든 문장
  - 제목(#)·목록(-, 1.)·인용(>)·표(|) 줄, '사진'·'캡션' 줄
표시만 하는 것(사람/Claude가 뜻을 대조해 판단)
  - 부정 표현 수 변화(않·없·못·아니·안·말-), 단정↔추측 변화(-ㄹ 수 있·것 같·듯·추정·가능성·보인다)
  - 앞부분 생략(원문 첫 두 어절이 사라짐) — 한국어는 앞부분이 빠지면 주어·조건이 바뀌기 쉬움
  - 주어·화제(…은/는/이/가) 사라짐, 길이가 40% 넘게 줄어듦

사용 예
  python 문장대조.py 원고_헤켈배아.md 원고_헤켈배아_다듬음.md --출력 다듬기대조_헤켈배아.md --복원본 원고_헤켈배아_다듬음.md
  (--복원본을 다듬은 파일과 같은 경로로 주면 그 파일에 자동 복원을 반영)
마지막 줄에 JSON 요약.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROTECT = re.compile(r"\[S\d+\]|\d|[\"“”‘’『』「」]|'[^']+'|[A-Za-z]{2,}")
LINE_PROTECT = re.compile(r"^\s*(#|>|\||-\s|\*\s|\d+\.\s|\[사진|캡션:|태그:|사진 출처|이 글은 AI)")
NEG = re.compile(r"않|없|못|아니|안 |말[고라아]")
HEDGE = re.compile(r"ㄹ 수 있|수 있|것 같|듯|추정|가능성|보인다|보입니다|여겨|알려져")
TOPIC = re.compile(r"(\S+?)(은|는|이|가)\s")
SENT_END = re.compile(r"(?<=[.!?。])\s+(?!\[S\d)|(?<=\d\])\s+(?!\[S\d)")  # 카드 번호([S7]) 뒤에서도 끊음


def units(text: str):
    """(시작, 끝, 문장, 줄보호) 목록. 빈 줄·구분선은 건너뜀."""
    out, pos = [], 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if body.strip() and body.strip() != "---":
            if LINE_PROTECT.match(body):
                s = pos + (len(body) - len(body.lstrip()))
                out.append((s, pos + len(body), body.strip(), True))
            else:
                start = 0
                for m in list(SENT_END.finditer(body)) + [None]:
                    end = m.start() if m else len(body)
                    seg = body[start:end]
                    if seg.strip():
                        lead = len(seg) - len(seg.lstrip())
                        out.append((pos + start + lead, pos + end, seg.strip(), False))
                    if m:
                        start = m.end()
        pos += len(line)
    return out


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def protected_tokens(s: str) -> list:
    return sorted(re.findall(r"\[S\d+\]|\d+(?:[.,]\d+)?|[A-Za-z][A-Za-z'’\-]+|[\"“”『』「」][^\"“”『』「」]*[\"“”『』「」]", s))


def check_pair(o: str, p: str, line_prot: bool) -> tuple[str, list]:
    reasons = []
    if line_prot or PROTECT.search(o):
        if protected_tokens(o) != protected_tokens(p) or line_prot:
            return "자동 복원", ["보호 문장(사실·숫자·인용·고유명사·구조 줄)이 바뀜"]
        reasons.append("보호 문장의 표현이 바뀜(숫자·인용·영문은 같음) — 뜻 대조")
    if len(NEG.findall(o)) != len(NEG.findall(p)):
        reasons.append(f"부정 표현 수 변화({len(NEG.findall(o))}→{len(NEG.findall(p))})")
    if bool(HEDGE.search(o)) != bool(HEDGE.search(p)):
        reasons.append("단정↔추측 표현 변화")
    ow = [w for w in re.findall(r"\S+", o)][:2]
    if ow and not all(re.sub(r"[^\w가-힣]", "", w)[:2] in p for w in ow):
        reasons.append("앞부분(첫 두 어절)이 사라지거나 바뀜")
    t = TOPIC.match(o + " ")
    if t and t.group(1) not in p:
        reasons.append(f"주어·화제 '{t.group(1)}{t.group(2)}'가 사라짐")
    if len(p) < 0.6 * len(o):
        reasons.append("길이가 40% 넘게 줄어듦(내용이 빠졌는지)")
    return ("확인 필요" if reasons else "통과"), reasons


def fine_align(o_idx: list, p_idx: list, ou, pu) -> list:
    """바뀐 덩어리 안에서 문장을 순서대로 짝짓기(비슷함 0.3 이상, 앞으로 3문장 안에서). (원문i|None, 다듬은j|None) 목록."""
    pairs, j = [], 0
    for i in o_idx:
        best, best_r = None, 0.3
        for jj in range(j, min(j + 3, len(p_idx))):
            r = difflib.SequenceMatcher(None, norm(ou[i][2]), norm(pu[p_idx[jj]][2])).ratio()
            if r > best_r:
                best, best_r = jj, r
        if best is None:
            pairs.append((i, None))
            continue
        for skipped in range(j, best):
            pairs.append((None, p_idx[skipped]))
        pairs.append((i, p_idx[best]))
        j = best + 1
    for rest in range(j, len(p_idx)):
        pairs.append((None, p_idx[rest]))
    return pairs


def main():
    ap = argparse.ArgumentParser(description="다듬기 전·후 문장 대조")
    ap.add_argument("원문")
    ap.add_argument("다듬은글")
    ap.add_argument("--출력", "--report", dest="report", help="대조 보고서(마크다운)")
    ap.add_argument("--복원본", "--restored", dest="restored", help="보호 문장을 되돌린 원고를 저장할 경로")
    a = ap.parse_args()
    otext = Path(a.원문).read_text(encoding="utf-8")
    ptext = Path(a.다듬은글).read_text(encoding="utf-8")
    ou, pu = units(otext), units(ptext)
    sm = difflib.SequenceMatcher(None, [norm(u[2]) for u in ou], [norm(u[2]) for u in pu], autojunk=False)
    rows, restore = [], []
    same = 0
    last_end = 0  # 지금까지 본 다듬은 문장의 끝 위치(빠진 문장을 되살릴 자리)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            same += i2 - i1
            last_end = pu[j2 - 1][1]
            continue
        for oi, pj in fine_align(list(range(i1, i2)), list(range(j1, j2)), ou, pu):
            o_seg = ou[oi][2] if oi is not None else ""
            p_seg = pu[pj][2] if pj is not None else ""
            if oi is None:  # 새 문장
                verdict, reasons = "확인 필요", ["새 문장이 생김 — 사실을 새로 넣지 않았는지"]
                if PROTECT.search(p_seg) or pu[pj][3]:
                    verdict, reasons = "자동 복원", ["새 문장·줄에 숫자·인용·영문·카드 번호·구조 표시가 있음(다듬기에서 사실 추가 금지) → 지움"]
                span, rep = (pu[pj][0], pu[pj][1]), ""
                last_end = pu[pj][1]
            elif pj is None:  # 빠진 문장 → 바로 앞 문장 뒤에 되살림
                prot = ou[oi][3] or bool(PROTECT.search(o_seg))
                verdict, reasons = ("자동 복원" if prot else "확인 필요"), ["문장이 빠짐"]
                span, rep = (last_end, last_end), (" " if last_end else "") + o_seg
            else:
                verdict, reasons = check_pair(o_seg, p_seg, ou[oi][3])
                span, rep = (pu[pj][0], pu[pj][1]), o_seg
                last_end = pu[pj][1]
            rows.append({"원문": o_seg, "다듬은문장": p_seg, "판정": verdict, "사유": reasons})
            if verdict == "자동 복원":
                restore.append((span, rep))
    out_text = ptext
    for (s, e), rep in sorted(restore, key=lambda x: x[0][0], reverse=True):
        out_text = out_text[:s] + rep + out_text[e:]
    if a.restored:
        Path(a.restored).write_text(out_text, encoding="utf-8")
    counts = {}
    for r in rows:
        counts[r["판정"]] = counts.get(r["판정"], 0) + 1
    if a.report:
        lines = ["# 다듬기 대조", "", f"- 원문: `{Path(a.원문).name}` · 다듬은 글: `{Path(a.다듬은글).name}`",
                 f"- 그대로인 문장 {same} · 바뀐 곳 {len(rows)} → " + ", ".join(f"{k} {v}" for k, v in counts.items()),
                 "- '자동 복원'은 이미 원문으로 되돌렸습니다(--복원본). '확인 필요'는 뜻을 대조해 바뀌었으면 원문으로 되돌립니다.", "",
                 "| # | 판정 | 원문 | 다듬은 문장 | 사유 |", "|---|---|---|---|---|"]
        for i, r in enumerate(rows, 1):
            cell = lambda s: s.replace("|", "/").replace("\n", " ")
            lines.append(f"| {i} | {r['판정']} | {cell(r['원문'])} | {cell(r['다듬은문장'])} | {cell('; '.join(r['사유']))} |")
        Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"그대로": same, "바뀐곳": len(rows), "판정": counts, "자동복원": len(restore),
                      "보고서": a.report, "복원본": a.restored}, ensure_ascii=False))


if __name__ == "__main__":
    main()
