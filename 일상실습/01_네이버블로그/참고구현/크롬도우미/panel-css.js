/*
 * 블로그 도우미 — 패널 스타일(닫힌 그림자 루트 안에 <style> 로 넣음, 검수 M2)
 * 패널이 페이지 DOM 밖(그림자 루트)에 있어 네이버 화면의 CSS 와 섞이지 않고, 페이지 스크립트가 패널 글자·로그를 읽지 못합니다.
 * content.js 보다 먼저 로드(manifest content_scripts). 모양을 고치려면 이 문자열만 고치세요.
 */
globalThis.BLOG_HELPER_PANEL_CSS = `
:host { all: initial !important; }
.bh-panel {
  all: initial;
  position: fixed;
  right: 76px;            /* 에디터 오른쪽 아래의 물음표·기기 아이콘을 가리지 않도록 조금 왼쪽 */
  bottom: 16px;
  z-index: 2147483646;
  width: 320px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  background: #ffffff;
  color: #1f2328;
  border: 1px solid #c9d1d9;
  border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  font: 13px/1.45 "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
}
.bh-panel.bh-left { right: auto; left: 16px; }
.bh-panel *,
.bh-panel *::before,
.bh-panel *::after { box-sizing: border-box; font-family: inherit; }

.bh-panel .bh-head {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px;
  background: #03c75a; color: #ffffff;
  border-radius: 9px 9px 0 0;
}
.bh-panel.bh-collapsed .bh-head { border-radius: 9px; }
.bh-panel .bh-title { font-weight: 700; font-size: 13px; color: #ffffff; flex: 1; }
.bh-panel .bh-conn {
  font-size: 12px; padding: 1px 6px; border-radius: 8px;
  background: rgba(255, 255, 255, 0.22); color: #ffffff; white-space: nowrap;
  max-width: 130px; overflow: hidden; text-overflow: ellipsis;
}
.bh-panel .bh-conn::before { content: "● "; }
.bh-panel .bh-conn[data-conn="off"] { background: #d1242f; }
.bh-panel .bh-conn[data-conn="checking"] { background: rgba(0, 0, 0, 0.2); }

.bh-panel .bh-body { padding: 8px 10px 10px; overflow-y: auto; display: block; }
.bh-panel.bh-collapsed .bh-body { display: none; }

.bh-panel .bh-row { display: flex; align-items: center; gap: 6px; margin: 0 0 6px; }
.bh-panel .bh-label { font-size: 12px; color: #57606a; white-space: nowrap; }
.bh-panel .bh-select {
  flex: 1; min-width: 0; height: 28px; padding: 2px 4px;
  font-size: 12px; color: #1f2328; background: #ffffff;
  border: 1px solid #c9d1d9; border-radius: 6px;
}
.bh-panel .bh-tip { margin: 0 0 6px; font-size: 12px; color: #57606a; }

.bh-panel .bh-btn {
  display: inline-block; cursor: pointer;
  font-size: 12px; line-height: 1.2; padding: 5px 8px;
  color: #1f2328; background: #f6f8fa;
  border: 1px solid #c9d1d9; border-radius: 6px;
}
.bh-panel .bh-btn:hover { background: #eef1f4; }
.bh-panel .bh-btn:focus-visible { outline: 2px solid #0969da; outline-offset: 1px; }
.bh-panel .bh-btn:disabled { opacity: 0.5; cursor: default; }
.bh-panel .bh-head .bh-mini { padding: 2px 6px; background: rgba(255, 255, 255, 0.9); border-color: transparent; }
.bh-panel .bh-insert {
  display: block; width: 100%; margin-top: 6px;
  font-size: 13px; font-weight: 700; padding: 7px 8px;
  color: #ffffff; background: #03c75a; border-color: #02a54b;
}
.bh-panel .bh-insert:hover { background: #02b351; }
.bh-panel .bh-item[data-done="1"] .bh-insert { background: #f6f8fa; color: #1f2328; border-color: #c9d1d9; font-weight: 400; }

.bh-panel .bh-list { list-style: none; margin: 0; padding: 0; }
.bh-panel .bh-item { margin: 0 0 8px; padding: 8px; border: 1px solid #d8dee4; border-radius: 8px; }
.bh-panel .bh-item[data-done="1"] { background: #f0fff4; border-color: #9be9a8; }
.bh-panel .bh-meta { font-size: 13px; }
.bh-panel .bh-meta b { font-weight: 700; }
.bh-panel .bh-sub { font-size: 12px; color: #57606a; margin-top: 2px; word-break: keep-all; overflow-wrap: anywhere; }
.bh-panel .bh-warn { font-size: 12px; color: #9a6700; margin-top: 2px; }
.bh-panel .bh-empty { font-size: 12px; color: #57606a; padding: 4px 0; }

.bh-panel .bh-result {
  position: sticky; top: -8px; z-index: 1;
  margin: 0 0 8px; padding: 6px 8px;
  font-size: 12px; white-space: pre-wrap; word-break: keep-all; overflow-wrap: anywhere;
  background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 6px;
}
.bh-panel .bh-result:empty { display: none; }
.bh-panel .bh-result[data-kind="done"] { color: #116329; background: #f0fff4; border-color: #9be9a8; }
.bh-panel .bh-result[data-kind="error"] { color: #d1242f; background: #fff5f5; border-color: #ffc1c0; }
.bh-panel .bh-result[data-kind="busy"] { color: #0969da; }
.bh-panel .bh-result[data-kind="warn"] { color: #7d4e00; background: #fff8c5; border-color: #eac54f; }

.bh-panel .bh-adv { margin-top: 4px; font-size: 12px; color: #57606a; display: block; }
.bh-panel .bh-adv summary { cursor: pointer; display: list-item; }
.bh-panel .bh-log {
  max-height: 140px; overflow: auto; margin: 4px 0; padding: 6px;
  font: 11px/1.4 Consolas, "D2Coding", monospace; white-space: pre-wrap;
  background: #f6f8fa; border-radius: 6px; color: #1f2328;
}
.bh-panel .bh-ver { font-size: 11px; color: #8c959f; }

/* v2: 작업·단계 */
.bh-panel .bh-jobtitle { font-size: 12px; font-weight: 700; margin: 0 0 6px; word-break: keep-all; overflow-wrap: anywhere; }
.bh-panel .bh-jobtitle:empty { display: none; }
.bh-panel .bh-steps { list-style: none; margin: 0 0 6px; padding: 0; max-height: 34vh; overflow-y: auto; border: 1px solid #d8dee4; border-radius: 6px; }
.bh-panel .bh-steps:empty { display: none; }
.bh-panel .bh-step { display: flex; justify-content: space-between; gap: 6px; padding: 3px 8px; font-size: 12px; border-bottom: 1px solid #eef1f4; }
.bh-panel .bh-step:last-child { border-bottom: 0; }
.bh-panel .bh-step-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bh-panel .bh-step-state { white-space: nowrap; color: #57606a; }
.bh-panel .bh-step[data-state="진행"] { background: #ddf4ff; }
.bh-panel .bh-step[data-state="진행"] .bh-step-state { color: #0969da; font-weight: 700; }
.bh-panel .bh-step[data-state="완료"] .bh-step-state,
.bh-panel .bh-step[data-state="사람"] .bh-step-state { color: #116329; }
.bh-panel .bh-step[data-state="주의"] .bh-step-state { color: #9a6700; font-weight: 700; }
.bh-panel .bh-step[data-state="실패"] { background: #fff5f5; }
.bh-panel .bh-step[data-state="실패"] .bh-step-state { color: #d1242f; font-weight: 700; }
.bh-panel .bh-actions { display: flex; flex-wrap: wrap; gap: 4px; margin: 0 0 6px; }
.bh-panel .bh-actions .bh-btn[hidden] { display: none; }
.bh-panel .bh-actions .bh-btn { flex: 1 1 auto; }
.bh-panel .bh-actions .bh-btn[data-bh="retry"],
.bh-panel .bh-actions .bh-btn[data-bh="start-now"] { color: #ffffff; background: #03c75a; border-color: #02a54b; font-weight: 700; }
.bh-panel .bh-tool .bh-list { margin-top: 6px; }
`;
