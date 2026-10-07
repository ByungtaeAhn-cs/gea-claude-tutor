/*
 * 블로그 도우미 v2 — 서비스 워커(background)
 * ---------------------------------------------------------------------------
 * 하는 일
 *   - 내 PC 의 로컬 서버(127.0.0.1:8765)와만 이야기합니다(외부 서버 전송 없음).
 *   - 연결 코드로 받은 토큰을 chrome.storage.local 에 두고, /api/발행/* 요청마다
 *     X-Blog-Helper-Token 헤더로 붙입니다.
 *   - 작업은 한 탭에서만: 다른 탭이 이미 받은 작업은 넘겨주지 않습니다.
 * 왜 여기서 받나: content.js 는 네이버 페이지의 보안 규칙(CORS·사설망 접근 제한)을 받아 로컬 서버에
 *   직접 요청하기 어렵습니다. 확장 서비스 워커는 manifest 의 host_permissions 로 허락받은 곳에만 요청합니다.
 * Chrome·Edge 공용(chrome.* 이름 그대로 동작).
 *
 * 메시지 약속 (content.js·popup.js → 이 파일)
 *   {종류:'연결', 코드}            → POST /api/확장연결/토큰 → 토큰 저장
 *   {종류:'연결끊기'}              → POST /api/확장연결/해제 + 토큰 지움
 *   {종류:'연결확인'}              → GET  /api/확장연결/확인
 *   {종류:'대기작업', 작업ID?}     → GET  /api/발행/대기작업[?작업ID=…] (작업ID 를 주면 그 작업만)
 *   {종류:'결과', 본문}            → POST /api/발행/결과
 *   {종류:'재시도', 작업ID, 단계}  → POST /api/발행/작업/<id>/재시도
 *   {종류:'작업', 작업ID}          → GET  /api/발행/작업/<id>
 *   {종류:'목록'} {종류:'묶음', 주소} {종류:'파일', 주소}  (보조: 사진 묶음만 넣기)
 *   {종류:'영상표', 파일:[{주소,이름,형식,크기}]}  → 일회용 표(2분, 이 탭만) — 동영상 같은 큰 파일용
 *   {종류:'진단', 본문}            → POST /api/발행/진단 (사람이 [진단 보내기]를 눌렀을 때만, 화면 구조만)
 * video-bridge.html(확장 출처의 숨은 iframe) → 이 파일:
 *   {종류:'영상표받기', 표}         → 표를 한 번만 내주고 지움 {ok, 서버목록, 파일}
 * 응답: {ok:true, 서버, 데이터|파일} 또는 {ok:false, 오류, 코드}
 */
'use strict';

const SERVERS = ['http://127.0.0.1:8765', 'http://localhost:8765'];
const PAGE_ORIGIN = 'https://blog.naver.com';
const TOKEN_HEADER = 'X-Blog-Helper-Token';
const JSON_TIMEOUT_MS = 8000;
const FILE_TIMEOUT_MS = 20000;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const P = {
  pairToken: '/api/확장연결/토큰',
  pairCheck: '/api/확장연결/확인',
  pairRevoke: '/api/확장연결/해제',
  list: '/api/발행/패키지',
  claim: '/api/발행/대기작업',
  report: '/api/발행/결과',
  diag: '/api/발행/진단',
  jobs: '/api/발행/작업',
};

let workingServer = null;

async function getToken() {
  const v = await chrome.storage.local.get('token');
  return v.token || null;
}

function toLocalUrl(base, path) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) {
    throw new Error('주소 형식이 이상합니다(서버 안의 상대 주소만 받습니다): ' + String(path));
  }
  const url = new URL(path, base);
  if (url.origin !== new URL(base).origin) throw new Error('로컬 서버가 아닌 주소는 받지 않습니다.');
  return url;
}

class LocalError extends Error {
  constructor(message, code) { super(message); this.code = code || null; }
}

/** 로컬 서버에 요청. 연결이 안 될 때(TypeError)만 다음 주소로. 시간 제한은 본문 읽기까지. */
async function requestLocal(path, { method = 'GET', body = null, timeoutMs = JSON_TIMEOUT_MS, reader, auth = true } = {}) {
  const order = workingServer ? [workingServer, ...SERVERS.filter((s) => s !== workingServer)] : SERVERS;
  const headers = {};
  if (auth) {
    const token = await getToken();
    if (token) headers[TOKEN_HEADER] = token;
  }
  if (body !== null) headers['Content-Type'] = 'application/json';
  let lastError = null;
  for (const base of order) {
    const url = toLocalUrl(base, path);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, { method, headers, body: body === null ? undefined : JSON.stringify(body),
        signal: ctrl.signal, cache: 'no-store', credentials: 'omit' });
      workingServer = base;
      return { base, value: await (reader || readJson)(res) };
    } catch (err) {
      if (err && err.name === 'AbortError') {
        throw new LocalError('로컬 서버가 ' + Math.round(timeoutMs / 1000) + '초 안에 답하지 않았습니다.', '시간초과');
      }
      if (!(err instanceof TypeError)) throw err;
      lastError = err;
      if (method !== 'GET') break; // POST 는 이미 서버에 닿았을 수 있어 다른 주소로 다시 보내지 않음
    } finally {
      clearTimeout(timer);
    }
  }
  throw new LocalError('로컬 서버(127.0.0.1:8765)에 연결할 수 없습니다. 발행서버(또는 여행 스튜디오)가 켜져 있는지 확인하세요.' +
    (lastError ? ' (' + lastError.message + ')' : ''), '서버꺼짐');
}

async function readJson(res) {
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch (_) { throw new LocalError('서버 응답이 JSON이 아닙니다(HTTP ' + res.status + ').'); }
  if (!res.ok) throw new LocalError((data && data['오류']) || ('HTTP ' + res.status), data && data['코드']);
  return data;
}

async function readImage(res) {
  if (!res.ok) {
    let reason = 'HTTP ' + res.status;
    let code = null;
    try { const d = await res.json(); reason = d['오류'] || reason; code = d['코드']; } catch (_) { /* 무시 */ }
    throw new LocalError('사진을 받지 못했습니다: ' + reason, code);
  }
  const declared = Number(res.headers.get('content-length') || 0);
  if (declared > MAX_FILE_BYTES) throw new LocalError('사진 한 장이 너무 큽니다(' + declared + '바이트).');
  const buf = new Uint8Array(await res.arrayBuffer());
  if (buf.length > MAX_FILE_BYTES) throw new LocalError('사진 한 장이 너무 큽니다(' + buf.length + '바이트).');
  let binary = '';
  for (let i = 0; i < buf.length; i += 0x8000) binary += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return { base64: btoa(binary), 형식: res.headers.get('content-type') || 'application/octet-stream', 크기: buf.length };
}

// 작업을 받은 탭 기억(서비스 워커가 잠들어도 남게 storage.session, 없으면 메모리)
const memClaims = {};
async function getClaims() {
  if (chrome.storage.session) return (await chrome.storage.session.get('claims')).claims || {};
  return memClaims;
}
async function setClaim(jobId, tabId) {
  const c = await getClaims();
  c[jobId] = tabId;
  if (chrome.storage.session) await chrome.storage.session.set({ claims: c }); else memClaims[jobId] = tabId;
}
async function tabAlive(tabId) {
  try { await chrome.tabs.get(tabId); return true; } catch (_) { return false; }
}

// 검수 M2: 탭마다 '받은 파일' 목록 — 서버가 그 탭에 준 작업(대기작업)·묶음 응답에 있던 파일 주소만 '파일'·'영상표'로 받을 수 있음.
// (네이버 페이지가 패널을 조작하거나 메시지를 흉내 내도 다른 여행·글의 사진을 받지 못하게)
const memTabFiles = {};
let tabFilesChain = Promise.resolve();
function withTabFiles(fn) {
  const run = tabFilesChain.then(fn);
  tabFilesChain = run.catch(() => {});
  return run;
}
async function getTabFiles() {
  return chrome.storage.session ? ((await chrome.storage.session.get('tabFiles')).tabFiles || {}) : memTabFiles;
}
async function setTabFiles(all) {
  if (chrome.storage.session) await chrome.storage.session.set({ tabFiles: all });
}
function addressesOf(bundles) {
  const out = [];
  (bundles || []).forEach((b) => (b['파일'] || []).forEach((f) => { if (f && typeof f['주소'] === 'string') out.push(f['주소']); }));
  return out;
}
function grantFiles(tabId, addrs, replace) {
  if (tabId == null) return Promise.resolve();
  return withTabFiles(async () => {
    const all = await getTabFiles();
    const cur = replace ? [] : (all[tabId] || []);
    all[tabId] = Array.from(new Set(cur.concat(addrs))).slice(-2000);
    await setTabFiles(all);
  });
}
async function tabMayFetch(tabId, addr) {
  if (tabId == null) return false;
  const all = await getTabFiles();
  return (all[tabId] || []).includes(addr);
}
async function auxEnabled() {
  return !!(await chrome.storage.local.get('auxTool')).auxTool;
}
if (chrome.tabs && chrome.tabs.onRemoved) {
  chrome.tabs.onRemoved.addListener((tabId) => {
    withTabFiles(async () => { const all = await getTabFiles(); delete all[tabId]; await setTabFiles(all); });
  });
}

// 큰 파일(동영상) 표: 콘텐츠 스크립트가 받을 파일 주소를 맡기고, 같은 탭의 다리 iframe 이 한 번만 찾아감
const TICKET_MS = 120000;
const memTickets = {};
async function getTickets() {
  const all = chrome.storage.session ? ((await chrome.storage.session.get('tickets')).tickets || {}) : memTickets;
  const now = Date.now();
  Object.keys(all).forEach((k) => { if (!all[k] || all[k].만료 < now) delete all[k]; });
  return all;
}
async function setTickets(all) {
  // storage.session 이 없으면 getTickets 가 memTickets 자체를 돌려주므로 따로 저장할 것이 없음
  if (chrome.storage.session) await chrome.storage.session.set({ tickets: all });
}
/** 서버 안의 상대 주소가 정확히 이 API 경로인지(파일·묶음 요청을 그 용도로만 쓰게) */
function isApiAddress(addr, apiPath) {
  if (typeof addr !== 'string' || !addr.startsWith('/') || addr.startsWith('//')) return false;
  try { return decodeURIComponent(new URL(addr, SERVERS[0]).pathname) === apiPath; } catch (_) { return false; }
}
const isFileAddress = (addr) => isApiAddress(addr, '/api/발행/파일');
// 표 읽기·쓰기는 하나씩(동시에 두 번 쓰이거나 지운 표가 되살아나지 않게)
let ticketChain = Promise.resolve();
function withTickets(fn) {
  const run = ticketChain.then(fn);
  ticketChain = run.catch(() => {});
  return run;
}
function randomTicket() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
}

async function handle(msg, sender) {
  const kind = msg && msg['종류'];
  const ok = (r, extra) => ({ ok: true, 서버: r.base, ...extra });
  if (kind === '연결') {
    const code = String(msg['코드'] || '').replace(/\D/g, '');
    if (code.length !== 6) throw new LocalError('연결 코드는 숫자 6자리입니다.', '잘못된_요청');
    const name = (navigator.userAgent.includes('Edg/') ? 'Edge' : 'Chrome') + ' 블로그 도우미';
    const r = await requestLocal(P.pairToken, { method: 'POST', body: { 코드: code, 이름: name }, auth: false });
    await chrome.storage.local.set({ token: r.value['토큰'], server: r.value['서버'], pairedAt: new Date().toISOString() });
    return ok(r, { 데이터: { 서버: r.value['서버'], 확장ID: r.value['확장ID'] } });
  }
  if (kind === '연결끊기') {
    try { await requestLocal(P.pairRevoke, { method: 'POST', body: {} }); } catch (_) { /* 서버가 꺼져 있어도 토큰은 지움 */ }
    await chrome.storage.local.remove(['token', 'server', 'pairedAt']);
    return { ok: true };
  }
  if (kind === '연결확인') {
    if (!(await getToken())) throw new LocalError('아직 연결하지 않았습니다.', '연결필요');
    const r = await requestLocal(P.pairCheck);
    return ok(r, { 데이터: r.value });
  }
  if (kind === '대기작업') {
    const run = claimChain.then(() => claimFor(sender, msg['작업ID'] || null));
    claimChain = run.catch(() => {});
    return run;
  }
  if (kind === '영상표') {
    const list = Array.isArray(msg['파일']) ? msg['파일'] : [];
    if (!list.length || list.length > 10) throw new LocalError('동영상 목록이 비었거나 10개를 넘습니다.', '잘못된_요청');
    if (!sender.tab) throw new LocalError('글쓰기 화면에서만 쓸 수 있습니다.', '잘못된_요청');
    const files = list.map((f) => {
      const addr = String((f && f['주소']) || '');
      if (!isFileAddress(addr)) throw new LocalError('내 PC 서버의 파일 주소가 아닙니다: ' + addr.slice(0, 80), '잘못된_요청');
      return { 주소: addr, 이름: String(f['이름'] || 'video.mp4').slice(0, 200), 형식: String(f['형식'] || ''), 크기: Number(f['크기']) || 0 };
    });
    for (const f of files) {
      if (!(await tabMayFetch(sender.tab.id, f['주소']))) throw new LocalError('이 화면이 받은 글의 파일이 아닙니다.', '작업밖파일');
    }
    if (!(await getToken())) throw new LocalError('아직 연결하지 않았습니다.', '연결필요');
    const ticket = randomTicket();
    await withTickets(async () => {
      const all = await getTickets();
      all[ticket] = { 탭: sender.tab.id, 파일: files, 만료: Date.now() + TICKET_MS };
      await setTickets(all);
    });
    return { ok: true, 표: ticket };
  }
  if (kind === '영상표받기') {
    const id = String(msg['표'] || '');
    const t = await withTickets(async () => {
      const all = await getTickets();
      const hit = all[id];
      if (hit) { delete all[id]; await setTickets(all); }  // 한 번만
      return hit;
    });
    if (!t || !sender.tab || t.탭 !== sender.tab.id) throw new LocalError('표가 없거나 만료되었습니다(같은 화면에서 다시 시도).', '표없음');
    const order = workingServer ? [workingServer, ...SERVERS.filter((s) => s !== workingServer)] : SERVERS;
    return { ok: true, 서버목록: order, 파일: t.파일 };
  }
  return handleRest(msg, kind, sender);
}

let claimChain = Promise.resolve();

/** 대기 작업 받기 — 여러 탭이 동시에 물어도 하나씩(받은 탭 기록이 엇갈리지 않게).
 *  작업ID 를 주면 그 작업만 받음(글이 있는 화면의 [작업 확인]·[이 단계부터 다시]). */
async function claimFor(sender, jobId) {
  let path = P.claim;
  if (jobId) {
    if (!/^n\d{8}-\d{6}-[0-9a-f]{4}$/.test(String(jobId))) throw new LocalError('작업 ID 형식이 이상합니다.');
    path += '?' + new URLSearchParams({ 작업ID: String(jobId) }).toString();
  }
  const r = await requestLocal(path);
  const d = r.value;
  const job = d['작업'];
  const tabId = sender.tab ? sender.tab.id : null;
  if (job && tabId != null) {
    const claims = await getClaims();
    const holder = claims[job['작업ID']];
    if (d['사유'] === '재개' && holder != null && holder !== tabId && await tabAlive(holder)) {
      return { ok: true, 서버: r.base, 데이터: { 작업: null, 사유: '다른화면진행중', 다음가능: null, 서버: d['서버'] } };
    }
    await setClaim(job['작업ID'], tabId);
    await grantFiles(tabId, addressesOf(job['묶음']), true);  // 이 탭은 이 글의 파일만
  }
  return { ok: true, 서버: r.base, 데이터: d };
}

async function handleRest(msg, kind, sender) {
  const tabId = sender && sender.tab ? sender.tab.id : null;
  const ok = (r, extra) => ({ ok: true, 서버: r.base, ...extra });
  if (kind === '결과') {
    const r = await requestLocal(P.report, { method: 'POST', body: msg['본문'] || {} });
    return ok(r, { 데이터: r.value });
  }
  if (kind === '진단') {  // 사람이 패널의 [진단 보내기]를 눌렀을 때만 옴(화면 구조만, 내 PC 서버로)
    const r = await requestLocal(P.diag, { method: 'POST', body: msg['본문'] || {}, timeoutMs: 30000 });
    return ok(r, { 데이터: r.value });
  }
  if (kind === '재시도') {
    const id = String(msg['작업ID'] || '');
    if (!/^n\d{8}-\d{6}-[0-9a-f]{4}$/.test(id)) throw new LocalError('작업 ID 형식이 이상합니다.');
    const body = {};
    if (msg['단계']) body['단계'] = msg['단계'];
    if (msg['사람']) body['사람'] = true;
    const r = await requestLocal(P.jobs + '/' + id + '/재시도', { method: 'POST', body });
    return ok(r, { 데이터: r.value });
  }
  if (kind === '작업') {
    const id = String(msg['작업ID'] || '');
    if (!/^n\d{8}-\d{6}-[0-9a-f]{4}$/.test(id)) throw new LocalError('작업 ID 형식이 이상합니다.');
    const r = await requestLocal(P.jobs + '/' + id);
    return ok(r, { 데이터: r.value });
  }
  if (kind === '목록' || kind === '묶음') {  // 보조 도구(사진 묶음만 넣기) — 팝업에서 사람이 켰을 때만
    if (!(await auxEnabled())) throw new LocalError("'사진 묶음만 넣기'(보조 도구)가 꺼져 있습니다 — 확장 아이콘에서 켜세요.", '보조꺼짐');
  }
  if (kind === '목록') {
    const r = await requestLocal(P.list);
    return ok(r, { 데이터: r.value });
  }
  if (kind === '묶음') {
    if (!isApiAddress(msg['주소'], '/api/발행/묶음')) throw new LocalError('묶음 주소가 아닙니다.', '잘못된_요청');
    const r = await requestLocal(msg['주소']);
    await grantFiles(tabId, addressesOf(r.value && r.value['묶음']), false);
    return ok(r, { 데이터: r.value });
  }
  if (kind === '파일') {
    if (!isFileAddress(msg['주소'])) throw new LocalError('파일 주소가 아닙니다.', '잘못된_요청');
    if (!(await tabMayFetch(tabId, msg['주소']))) throw new LocalError('이 화면이 받은 글의 파일이 아닙니다.', '작업밖파일');
    const r = await requestLocal(msg['주소'], { timeoutMs: FILE_TIMEOUT_MS, reader: readImage });
    return ok(r, { 파일: r.value });
  }
  throw new LocalError('알 수 없는 요청: ' + String(kind));
}

function senderOrigin(sender) {
  if (sender.origin) return sender.origin;
  try { return new URL(sender.url).origin; } catch (_) { return ''; }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!sender || sender.id !== chrome.runtime.id) return false;
  const origin = senderOrigin(sender);
  const kind = msg && msg['종류'];
  const fromPage = !!sender.tab && origin === PAGE_ORIGIN;                    // 네이버 블로그 화면의 content.js
  const fromExt = origin === new URL(chrome.runtime.getURL('/')).origin;     // 확장 페이지(팝업)
  // 동영상 다리: use_dynamic_url 이라 세션마다 바뀌는 주소(chrome-extension://<동적ID>/video-bridge.html)에서 옴.
  // 보낸 확장 ID(sender.id, 브라우저가 붙임)가 이 확장이고, 탭 안의 iframe 이며, 경로가 다리 파일일 때만 다리로 봄
  let senderUrl = null;
  try { senderUrl = new URL(String(sender.url || '')); } catch (_) { senderUrl = null; }
  const fromBridge = !!sender.tab && !!senderUrl && senderUrl.protocol === 'chrome-extension:' && senderUrl.pathname === '/video-bridge.html';
  if (!fromPage && !fromExt && !fromBridge) return false;
  if (fromBridge) { if (kind !== '영상표받기') return false; }               // 다리 iframe 은 표 받기만
  else if (fromExt && !['연결', '연결끊기', '연결확인'].includes(kind)) return false;   // 팝업은 연결만
  if (fromPage && kind === '영상표받기') return false;                       // 표는 다리 iframe 만 찾아감
  handle(msg, sender).then(sendResponse, (err) => sendResponse({ ok: false, 오류: String((err && err.message) || err), 코드: err && err.code }));
  return true;
});
