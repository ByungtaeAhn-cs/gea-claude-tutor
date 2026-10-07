/*
 * 블로그 도우미 — 동영상 다리(video-bridge.html 의 스크립트)
 * ---------------------------------------------------------------------------
 * 글쓰기 화면(content.js)이 숨은 iframe 으로 이 확장 페이지를 열고, MessageChannel 의 한쪽 포트를 넘깁니다.
 *  1) 포트로 받은 '표'를 서비스 워커에 보여 주고(일회용·2분·같은 탭만) 받을 파일 주소 목록을 받음
 *  2) 확장 토큰으로 내 PC 서버(127.0.0.1:8765)에서 스트리밍으로 받아 8MB 조각 Blob 으로 모음
 *     (브라우저가 큰 Blob 을 디스크에 둠 — base64·JSON 메시지를 쓰지 않음)
 *  3) File 목록을 같은 포트로 돌려줌(복사 없이 넘어감). 진행률은 '진행' 메시지로
 * 네이버 페이지 스크립트는 표를 모르고 포트도 볼 수 없으므로 이 창에 받기를 시키거나 파일을 엿볼 수 없습니다.
 * 토큰은 확장 저장소(chrome.storage.local)에서 읽어 요청 헤더에만 쓰고 네이버 페이지로 넘기지 않습니다.
 * 외부 서버로는 아무것도 보내지 않습니다.
 */
'use strict';

const TOKEN_HEADER = 'X-Blog-Helper-Token';
const PART_BYTES = 8 * 1024 * 1024;

const PAGE_ORIGIN = 'https://blog.naver.com';

window.addEventListener('message', (ev) => {
  // 검수 L5: 이 창을 품은 글쓰기 화면(부모 창, blog.naver.com)이 보낸 것만 — 다른 창·출처는 무시
  if (ev.source !== window.parent || ev.origin !== PAGE_ORIGIN) return;
  const port = ev.ports && ev.ports[0];
  const d = ev.data;
  if (!port || !d || d['종류'] !== '영상다리' || typeof d['표'] !== 'string') return;
  port.postMessage({ 종류: '연결됨' });
  const ctrl = new AbortController();
  port.onmessage = (e) => { if (e.data && e.data['종류'] === '멈춤') ctrl.abort(); };
  run(port, d['표'], ctrl.signal).catch((err) => {
    try { port.postMessage({ 종류: '오류', 오류: String((err && err.message) || err), 코드: (err && err.code) || null }); } catch (_) { /* 닫힘 */ }
  });
});

function codeError(message, code) {
  const e = new Error(message);
  e.code = code || null;
  return e;
}

async function run(port, ticket, signal) {
  const t = await chrome.runtime.sendMessage({ 종류: '영상표받기', 표: ticket });
  if (!t || !t.ok) throw codeError((t && t['오류']) || '표를 확인하지 못함', t && t['코드']);
  const token = (await chrome.storage.local.get('token')).token;
  if (!token) throw codeError('확장 연결이 필요합니다(확장 아이콘 → 연결 코드).', '연결필요');
  const list = t['파일'] || [];
  const out = [];
  for (let i = 0; i < list.length; i++) {
    const f = list[i];
    const res = await get(t['서버목록'] || [], f['주소'], token, signal);
    if (!res.ok) {
      let msg = 'HTTP ' + res.status;
      let code = null;
      try { const j = await res.json(); msg = j['오류'] || msg; code = j['코드']; } catch (_) { /* JSON 아님 */ }
      throw codeError(msg + ' — ' + f['이름'], code);
    }
    const total = Number(res.headers.get('content-length')) || Number(f['크기']) || 0;
    const reader = res.body.getReader();
    const parts = [];
    let chunk = [];
    let chunkBytes = 0;
    let got = 0;
    let tick = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunk.push(value);
      chunkBytes += value.byteLength;
      got += value.byteLength;
      if (chunkBytes >= PART_BYTES) { parts.push(new Blob(chunk)); chunk = []; chunkBytes = 0; }
      if (Date.now() - tick > 400) {
        tick = Date.now();
        port.postMessage({ 종류: '진행', 번호: i + 1, 전체수: list.length, 받은: got, 크기: total });
      }
    }
    if (chunk.length) parts.push(new Blob(chunk));
    if (total && got !== total) throw codeError('동영상을 끝까지 받지 못함(' + got + '/' + total + '바이트) — ' + f['이름'], '확인필요');
    port.postMessage({ 종류: '진행', 번호: i + 1, 전체수: list.length, 받은: got, 크기: total });
    out.push(new File(parts, f['이름'], { type: f['형식'] || res.headers.get('content-type') || 'video/mp4', lastModified: Date.now() }));
  }
  port.postMessage({ 종류: '파일', 파일: out });
}

/** 내 PC 서버에서만 받음(127.0.0.1 → 안 되면 localhost). 다른 주소는 거부 */
async function get(bases, path, token, signal) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) throw codeError('주소 형식이 이상합니다.', '잘못된_요청');
  let last = null;
  for (const base of bases) {
    const url = new URL(path, base);
    if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url.origin) || url.origin !== new URL(base).origin) {
      throw codeError('로컬 서버가 아닌 주소는 받지 않습니다.', '잘못된_요청');
    }
    try {
      return await fetch(url, { headers: { [TOKEN_HEADER]: token }, cache: 'no-store', credentials: 'omit', signal });
    } catch (err) {
      if (err && err.name === 'AbortError') throw codeError('멈춤', '시간초과');
      last = err;
    }
  }
  throw codeError('로컬 서버에 연결할 수 없습니다' + (last ? ' (' + last.message + ')' : ''), '서버꺼짐');
}
