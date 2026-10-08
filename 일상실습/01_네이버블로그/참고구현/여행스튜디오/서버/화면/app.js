// 여행 스튜디오 화면 — 한 페이지 앱(주소의 # 뒷부분으로 화면을 바꿈). 빌드 과정 없음. (규약 v2 6절)
// 서버(/api)와만 이야기합니다. Claude 와는 서버가 만든 '작업함' 파일로, 블로그 도우미 확장과는 공용 발행 API로.
'use strict';

// ───────────────────────────── 작은 도구
const $ = (선택자, 안 = document) => 안.querySelector(선택자);
const $$ = (선택자, 안 = document) => [...안.querySelectorAll(선택자)];
const h = (글) => String(글 ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const 굵게 = (글) => h(글).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
const 질의 = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString();
const 파일주소 = (여행ID, 경로) => { // 같은 출처의 /파일/<여행>/… 만. .. · . · 빈 조각 · 역슬래시 · 콜론(스킴·드라이브)은 빈 주소
  const 조각 = String(경로 ?? '').split('/');
  if (!경로 || 조각.some((c) => !c || c === '.' || c === '..' || /[\\:]/.test(c))) return '';
  return `/파일/${encodeURIComponent(여행ID)}/${조각.map(encodeURIComponent).join('/')}`;
};
const 정수 = (v, 대신 = null) => (Number.isInteger(v) ? v : 대신); // 파일에서 온 '번호·횟수'는 정수만(글자면 대신값)
const 화면주소 = (화면, ...인자) => '#/' + [화면, ...인자.filter((x) => x !== undefined && x !== null && x !== '').map((x) => encodeURIComponent(x))].join('/');
const 요일 = ['일', '월', '화', '수', '목', '금', '토'];

function 기억읽기(키) { try { return localStorage.getItem('여행스튜디오:' + 키); } catch { return null; } }
function 기억쓰기(키, 값) { try { if (값 === null) localStorage.removeItem('여행스튜디오:' + 키); else localStorage.setItem('여행스튜디오:' + 키, 값); } catch { /* 저장 못 해도 동작에는 지장 없음 */ } }

// 화면 열쇠: 서버가 이 화면(index.html)에만 심어 줌. 다른 확장·사이트는 이것 없이 /api·/파일 을 못 읽음(보안 검수 M1)
const 화면키 = document.querySelector('meta[name="studio-key"]')?.content || '';
function 열쇠다시() { // 서버를 다시 켜면 열쇠가 바뀜 → 화면을 한 번 새로 고침(15초 안에 두 번은 안 함)
  let 전 = 0;
  try { 전 = +sessionStorage.getItem('여행스튜디오:열쇠새로') || 0; } catch { /* 무시 */ }
  if (Date.now() - 전 < 15000) return false;
  try { sessionStorage.setItem('여행스튜디오:열쇠새로', String(Date.now())); } catch { /* 무시 */ }
  location.reload();
  return true;
}
async function API(경로, 보낼것) {
  const 머리 = { 'X-Studio-Key': 화면키 };
  const 옵션 = 보낼것 === undefined ? { cache: 'no-store', headers: 머리 }
    : { method: 'POST', headers: { ...머리, 'Content-Type': 'application/json' }, body: JSON.stringify(보낼것) };
  const r = await fetch(경로, 옵션);
  let 데이터 = null;
  try { 데이터 = await r.json(); } catch { /* JSON 이 아닌 응답 */ }
  if (!r.ok) {
    if (r.status === 403 && 데이터?.코드 === '화면키') 열쇠다시();
    const e = new Error((데이터 && 데이터.오류) || `서버 응답 ${r.status}`);
    e.코드 = 데이터 && 데이터.코드; e.상태 = r.status; e.데이터 = 데이터;
    throw e;
  }
  return 데이터;
}
async function JSON파일(여행ID, ...경로후보) { // 여행 폴더 안 JSON 파일 읽기(없으면 null)
  for (const 경로 of 경로후보) {
    const r = await fetch(파일주소(여행ID, 경로), { cache: 'no-cache', headers: { 'X-Studio-Key': 화면키 } });
    if (r.ok) return r.json();
  }
  return null;
}

// 날짜·시각 (기록된 '현지 시각' 그대로 보여 주려고 글자에서 바로 자름)
function 날짜조각(글) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(글 || ''); return m ? { 년: +m[1], 월: +m[2], 일: +m[3] } : null; }
function 요일글(d) { return 요일[new Date(Date.UTC(d.년, d.월 - 1, d.일)).getUTCDay()]; }
function 날짜더하기(글, 날수) { const d = 날짜조각(글); if (!d) return null; const t = new Date(Date.UTC(d.년, d.월 - 1, d.일 + 날수)); return t.toISOString().slice(0, 10); }
function 시각글(x, 초까지 = false) { const m = /T(\d{2}):(\d{2}):(\d{2})/.exec(x.촬영시각 || x.기록시각 || ''); return m ? (초까지 ? `${m[1]}:${m[2]}:${m[3]}` : `${m[1]}:${m[2]}`) : '시각 모름'; }
function 분(x) { const m = /T(\d{2}):(\d{2})/.exec(x.촬영시각 || ''); const d = 날짜조각(x.촬영시각); return m && d ? Date.UTC(d.년, d.월 - 1, d.일) / 60000 + (+m[1]) * 60 + (+m[2]) : null; }
function 길이글(초) { if (!초 && 초 !== 0) return ''; const s = Math.round(초); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function 짧은시각(글) { const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(글 || ''); return m ? `${+m[2]}/${+m[3]} ${m[4]}:${m[5]}` : ''; }
function 기간글(기간) {
  const a = 날짜조각(기간?.시작), b = 날짜조각(기간?.끝);
  if (!a) return '';
  const 앞 = `${a.년}.${a.월}.${a.일}`;
  if (!b || (a.년 === b.년 && a.월 === b.월 && a.일 === b.일)) return 앞;
  return `${앞} – ${a.년 === b.년 ? '' : b.년 + '.'}${b.월}.${b.일}`;
}
function 크기글(바이트) { if (!바이트) return '0'; return 바이트 > 1048576 ? `${(바이트 / 1048576).toFixed(1)}MB` : `${Math.round(바이트 / 1024)}KB`; }
function 오늘() { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`; }

const 결정순서 = { 미정: '사용', 사용: '대표', 대표: '제외', 제외: '사용' };
const 약한출처 = { EXIF: '시간대 정보 없음(여행 시간대로 가정)', 파일명: '파일 이름에서 읽은 시각', 파일수정시각: '파일 수정 시각(부정확할 수 있음)' };
function 시각약함(x, 정보) {
  const 출처 = x.시각출처;
  if (!(출처 in 약한출처)) return false;
  if (출처 === 'EXIF' && 정보?.기기보정초 && x.기기 in 정보.기기보정초) return false; // 사용자가 시계를 확인한 기기
  return true;
}
const 요청이름 = {
  목록만들기: '사진 목록 만들기', 시계확인: '기기 시계 확인', 고르기: '사진 고르기', 구성안: '구성안 만들기',
  지도: '동선 지도·장소', 꿀팁인터뷰: '꿀팁 인터뷰', 글쓰기: '글쓰기', 수정요청: '고쳐 달라기',
  임시저장: '발행 패키지 만들기', 재시도: '다시 시도', 영상: '돌아보기 영상', 자유요청: '따로 부탁',
};
const 단계이름 = { 목록만들기: '사진 목록', 시계확인: '사진 목록', 고르기: '고르기', 구성안: '구성안', 지도: '지도', 꿀팁인터뷰: '꿀팁', 글쓰기: '글쓰기', 수정요청: '글 고치기', 임시저장: '발행', 재시도: '다시 시도', 영상: '영상', 자유요청: '부탁' };
const 발행상태글 = { 대기: '블로그 도우미 기다리는 중', 채우는중: '채우는 중', 임시저장완료: '임시저장 끝', 예약발행완료: '예약 발행 끝', 실패: '멈춤(실패)', 취소: '취소됨' };
const 실패도움 = {
  로그인필요: '그 브라우저에서 네이버에 직접 로그인한 뒤 [다시 시도]를 눌러 주세요(로그인은 사람이 해요).',
  보안확인: '네이버 보안 확인(자동입력 방지 등)이 떴어요. 사람이 처리한 뒤 [다시 시도]를 눌러 주세요.',
  팝업: '모르는 창이 떴어요. 창 내용을 확인해 닫은 뒤 [다시 시도]를 눌러 주세요.',
  선택자없음: "네이버 화면이 바뀌어 버튼을 못 찾았어요. Claude에게 '확장 선택자를 지금 화면에 맞게 고쳐줘'라고 부탁하세요.",
  확인필요: '결과가 확실하지 않아요. 네이버 화면을 눈으로 확인해 주세요.',
  에디터비어있지않음: '글쓰기 화면에 이미 글이 있어요. 새 글쓰기 화면을 열고 [다시 시도]를 눌러 주세요.',
  앞단계없음: '앞 단계 내용이 화면에 없어요. [처음부터]로 다시 해 주세요.',
  카테고리없음: '블로그에 그 카테고리가 없어요. 글의 카테고리 이름을 블로그와 똑같이 고쳐 달라고 하세요.',
  장소없음: '네이버 장소 검색에서 그 장소를 못 찾았어요. 장소 이름을 확인해 주세요.',
  시간초과: '시간이 오래 걸려 멈췄어요. 화면을 확인하고 [다시 시도]를 눌러 주세요.',
  중단됨: '블로그 도우미의 보고가 오래 없어 멈춘 것으로 봤어요. 브라우저 화면을 확인해 주세요.',
  사람이멈춤: '사람이 멈췄어요. 준비되면 [다시 시도]를 눌러 주세요.',
  예약불가: '예약 발행 조건(승인·설정·시각)이 맞지 않아요.',
  사진없음: '사진 파일을 서버에서 받지 못했어요(업로드 사본 검사에 걸린 사진은 내주지 않아요). [업로드 사본 다시 만들기] 또는 [발행 패키지 다시 만들어 달라기] 뒤 [다시 시도]를 눌러 주세요.',
  영상없음: "동영상 파일을 서버에서 받지 못했어요. [발행 패키지 다시 만들어 달라기] 뒤 [다시 시도] — 급하면 네이버 '동영상' 버튼으로 직접 올려도 돼요.",
  영상전달: "블로그 도우미가 동영상을 네이버 화면에 넘기지 못했어요. 네이버 화면을 새로 고친 뒤 [다시 시도], 안 되면 '동영상' 버튼으로 직접 올려 주세요.",
  설정오류: '블로그 도우미 설정이 맞지 않아요. 확장 팝업에서 연결 상태를 확인해 주세요.',
};
const 브라우저이름 = { chrome: 'Chrome', edge: 'Edge', default: '기본 브라우저' };

function 수리문구(로그칸, 작업) {
  const 파일 = (로그칸 || `로그/${오늘()}.log`).split('#')[0];
  return `${파일}의 마지막 오류를 분석해서 원인을 찾고 고친 다음 그 단계부터 다시 실행해줘` + (작업 ? ` (작업 ${작업})` : '');
}

// ───────────────────────────── 앱 상태
const 앱 = {
  여행ID: 기억읽기('현재여행'),
  여행들: [], 상태: null, 질문: [], 서버살아있음: true,
  본질문: new Set(), 처음질문: true, 본알림: null,
  화면: null, 정의: null, 데이터: null, 그리기번호: 0, 파일시각: {}, 질문서명: '', 여행서명: '', 살핀횟수: 0,
  초안: {}, 보기: {}, 미리보기모바일: false,
};
const 본문 = () => $('#본문');

// ───────────────────────────── 화면 밝기(라이트/다크)
function 지금테마() {
  const 고름 = document.documentElement.dataset.theme;
  if (고름 === 'light' || 고름 === 'dark') return 고름;
  return window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function 테마정하기(값) { // 'light' | 'dark' | 'system'
  if (값 === 'light' || 값 === 'dark') { document.documentElement.dataset.theme = 값; 기억쓰기('테마', 값); }
  else { delete document.documentElement.dataset.theme; 기억쓰기('테마', null); }
  테마단추그리기();
}
function 테마단추그리기() {
  const 어둠 = 지금테마() === 'dark';
  const b = $('#테마단추');
  b.innerHTML = 어둠
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><span>밝게</span>'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><span>어둡게</span>';
  b.setAttribute('aria-label', 어둠 ? '밝은 화면으로 바꾸기' : '어두운 화면으로 바꾸기');
  $$('input[name="테마"]').forEach((r) => { r.checked = r.value === (document.documentElement.dataset.theme || 'system'); });
}
if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', 테마단추그리기);

// ───────────────────────────── 알림(쪽지)·창
function 쪽지(글, { 단추, 할일, 종류 = '보통', 시간 = 7000 } = {}) {
  const el = document.createElement('div');
  el.className = `쪽지 쪽지-${종류}`;
  el.setAttribute('role', 종류 === '오류' ? 'alert' : 'status');
  el.innerHTML = `<span class="쪽지글">${h(글)}</span>${단추 ? `<button type="button" class="쪽지단추">${h(단추)}</button>` : ''}<button type="button" class="쪽지닫기" aria-label="알림 닫기">×</button>`;
  el.querySelector('.쪽지닫기').onclick = () => el.remove();
  if (단추) el.querySelector('.쪽지단추').onclick = () => { el.remove(); typeof 할일 === 'function' ? 할일() : (location.hash = 할일); };
  $('#알림판').append(el);
  while ($('#알림판').children.length > 4) $('#알림판').firstElementChild.remove();
  setTimeout(() => el.remove(), 시간);
}
const 오류쪽지 = (e) => 쪽지(e.message || String(e), { 종류: '오류', 시간: 10000 });

function 창열기(html, { 넓게 = false } = {}) {
  const d = $('#창');
  d.classList.toggle('넓은창', 넓게);
  d.innerHTML = html;
  if (!d.open) d.showModal();
  (d.querySelector('[autofocus]') || d.querySelector('button, input, textarea'))?.focus();
  return d;
}
function 창닫기() { const d = $('#창'); if (d.open) d.close(); }
function 확인창(글, 예 = '네', 아니오 = '아니요') {
  return new Promise((끝) => {
    const d = 창열기(`<p style="margin:0 0 18px;font-size:16px;line-height:1.6">${글}</p>
      <div class="오른쪽"><button type="button" class="단추" data-창답="0">${h(아니오)}</button><button type="button" class="단추 단추-주" data-창답="1" autofocus>${h(예)}</button></div>`);
    let 끝남 = false;
    const 답 = (v) => { if (끝남) return; 끝남 = true; 창닫기(); 끝(v); };
    d.querySelector('[data-창답="1"]').onclick = () => 답(true);
    d.querySelector('[data-창답="0"]').onclick = () => 답(false);
    d.addEventListener('close', () => 답(false), { once: true });
  });
}
async function 복사하기(글) {
  try { await navigator.clipboard.writeText(글); 쪽지('복사했어요. Claude 창에 붙여 넣으세요.'); }
  catch { 창열기(`<h2>복사하기</h2><p class="본문글">아래 글을 골라 복사하세요(Ctrl+C).</p><textarea class="입력" rows="4" readonly autofocus>${h(글)}</textarea><div class="오른쪽" style="margin-top:12px"><button type="button" class="단추 단추-주" data-할일="창닫기">닫기</button></div>`); }
}

// ───────────────────────────── 서버 살피기(2초마다)
async function 살피기() {
  try {
    const [상태, 질문] = await Promise.all([
      API('/api/상태?' + 질의({ 여행: 앱.여행ID })),
      API('/api/질문?' + 질의({ 여행: 앱.여행ID })),
    ]);
    앱.서버살아있음 = true;
    앱.상태 = 상태;
    앱.질문 = 질문.질문 || [];
  } catch {
    앱.서버살아있음 = false;
  }
  연결그리기(); 띠그리기(); 메뉴그리기();
  if (!앱.서버살아있음) return;
  새질문살피기(); 새알림살피기(); 요청단추새로고침();
  const 정의 = 앱.정의 || 화면들[''];
  let 바뀜 = false;
  for (const 키 of 정의.관심 || []) {
    if (키 === '질문') { if (질문서명() !== 앱.질문서명) 바뀜 = true; continue; }
    if (키 === '알림') { // 알림이 생기거나 지난 알림으로 옮겨지면 시작 화면을 다시 그림
      const 서명 = JSON.stringify([(앱.상태.알림 || []).map((x) => x.id), (앱.상태.지난알림 || []).length]);
      if (앱.알림서명 !== undefined && 서명 !== 앱.알림서명) 바뀜 = true;
      앱.알림서명 = 서명; continue;
    }
    if (키 === '여행목록' || 키 === '발행작업') continue;
    const 새 = 앱.상태.파일시각?.[키] ?? null;
    if ((앱.파일시각[키] ?? null) !== 새) 바뀜 = true;
  }
  앱.살핀횟수 += 1;
  if (!바뀜 && (정의.관심 || []).includes('여행목록') && 앱.살핀횟수 % 3 === 0) {
    try { const 여행 = await API('/api/여행'); if (JSON.stringify(여행.여행) !== 앱.여행서명) 바뀜 = true; } catch { /* 다음 번에 */ }
  }
  if (!바뀜 && (정의.관심 || []).includes('발행작업') && 앱.데이터?.편) { // 발행 화면: 확장이 단계를 보고하면 바로 보이게
    try {
      const 새 = await API('/api/발행상태?' + 질의({ 여행: 앱.여행ID, 편: 앱.데이터?.편 }));
      if (JSON.stringify([새.최근작업, 새.확장, 새.패키지, 새.다음가능]) !== JSON.stringify([앱.데이터?.발행?.최근작업, 앱.데이터?.발행?.확장, 앱.데이터?.발행?.패키지, 앱.데이터?.발행?.다음가능])) {
        앱.데이터.발행 = 새; 다시그리기();
      }
    } catch { /* 다음 번에 */ }
  }
  if (바뀜) 화면그리기({ 유지: true });
}
function 질문서명() { return 앱.질문.map((q) => q.id + ':' + q.상태).join('|'); }
async function 살피기반복() { await 살피기(); setTimeout(살피기반복, document.hidden ? 8000 : 2000); }

function 연결그리기() {
  let 종류 = '확인중', 글 = '연결 확인 중…';
  if (!앱.서버살아있음) { 종류 = '끊김'; 글 = '스튜디오 서버가 꺼져 있어요'; }
  else if (앱.상태) {
    const c = 앱.상태.연결 || {};
    if (c.판정 === '연결됨') {
      종류 = '연결됨';
      글 = 'Claude 연결됨 · ' + (앱.상태.대기요청?.length ? '요청 받는 중' : 앱.상태.기다리는질문 ? '답을 기다리는 중' : '기다리는 중');
    } else if (c.판정 === '작업중') {
      종류 = '작업중';
      const w = c.작업 || {};
      const 단계 = w.단계 || '', 메시지 = w.메시지 || '';
      const 내용 = !메시지 ? 단계 : (!단계 || 메시지.includes(단계) || 메시지.length > 10) ? 메시지 : `${단계} ${메시지}`;
      const 발행작업 = w.작업ID && String(w.작업ID).startsWith('n');
      글 = 발행작업 && w.단계 === '대기' ? '네이버 화면에서 확장 대기 중'
        : (발행작업 ? '블로그 도우미 · ' : 'Claude 작업 중 · ') + (내용 || '처리 중') + (typeof w.퍼센트 === 'number' ? ` ${w.퍼센트}%` : '');
    } else { 종류 = '끊김'; 글 = 'Claude 연결 안 됨'; }
  }
  const 단추로 = 앱.서버살아있음 && 앱.상태 && 종류 === '끊김'; // 연결 안 됨 → 표시와 [연결하기]를 한 단추로
  $('#연결표시').className = `연결 연결-${종류}${단추로 ? ' 숨김글' : ''}`;
  if ($('#연결글').textContent !== 글) $('#연결글').textContent = 글;
  $('#연결표시').title = 글;
  $('#연결단추').hidden = !단추로;
}

function 멈춤열쇠(x) { return `${x.작업ID || x.요청id}|${x.갱신}`; }
function 띠그리기() {
  let html = '';
  if (!앱.서버살아있음) {
    html = `<div class="띠 띠-끊김" role="alert"><span>스튜디오 서버가 꺼져 있어요. 바탕화면의 '여행 스튜디오' 아이콘을 다시 눌러 주세요.</span></div>`;
  } else if (앱.상태) {
    const 닫음 = new Set(JSON.parse(기억읽기('닫은멈춤') || '[]'));
    const 멈춤 = (앱.상태.멈춤 || []).find((x) => !닫음.has(멈춤열쇠(x)));
    if (멈춤) { // 오류가 나면 작업은 자동으로 멈춤 → 여기서 알림(규약 2.6)
      const 글 = 멈춤.메시지 && 멈춤.단계 && 멈춤.메시지.includes(멈춤.단계) ? 멈춤.메시지 : [멈춤.단계, 멈춤.메시지].filter(Boolean).join(': ');
      html += `<div class="띠 띠-끊김" role="alert"><span>작업이 멈췄어요 — ${h(글)}</span>
        <span class="단추줄"><a class="단추 단추-작게" href="${화면주소('이력', 앱.여행ID)}">작업 이력에서 보기</a>
        <button type="button" class="단추 단추-작게" data-할일="수리복사" data-값="${h(멈춤.작업ID || '')}">수리 프롬프트 복사</button>
        <button type="button" class="단추 단추-작게" data-할일="멈춤닫기" data-값="${h(멈춤열쇠(멈춤))}" aria-label="이 알림 닫기">닫기</button></span></div>`;
    }
    if (앱.상태.시험확인) { // --시험확인(시험용 서버): 데스크탑 확인 창이 자동으로 답함 — 실제로 쓰지 말 것
      html += `<div class="띠 띠-끊김" role="alert"><span>시험 모드예요 — 컴퓨터 확인 창이 자동으로 ‘${h(앱.상태.시험확인)}’로 답해요. 실제로 쓸 때는 바탕화면 아이콘으로 다시 켜 주세요.</span></div>`;
    }
    if (앱.상태.공용?.갱신필요) { // 서버를 켤 때 교재의 공용 파일과 비교(보안 검수 L13) — 갱신은 사람이
      html += `<div class="띠 띠-안내"><span>공용 파일(미리보기·발행 모듈)에 새 판이 있어요 — 바뀐 것: ${h((앱.상태.공용.바뀐것 || []).join(', '))}</span>
        <button type="button" class="단추 단추-주" data-할일="공용갱신">공용 파일 갱신</button></div>`;
    }
    if (앱.상태.연결?.판정 === '끊김' && 앱.상태.대기요청?.length) {
      html += `<div class="띠 띠-안내"><span>보낸 요청 ${앱.상태.대기요청.length}개가 Claude를 기다리고 있어요. Claude가 연결되어 있지 않아요.</span>
        <button type="button" class="단추 단추-주" data-할일="클로드연결">Claude 연결하기</button></div>`;
    }
  }
  if ($('#띠').dataset.html !== html) { $('#띠').innerHTML = html; $('#띠').dataset.html = html; }
}

function 메뉴그리기() {
  const { 화면 } = 경로풀기();
  const id = 앱.여행ID;
  const 수 = 앱.질문.filter((q) => q.상태 === '기다림').length;
  const 항목 = [['', '시작'], ['타임라인', '타임라인·고르기'], ['질문', '질문'], ['구성안', '구성안'], ['지도', '지도·장소'], ['글', '글'], ['발행', '발행'], ['영상', '영상'], ['이력', '작업 이력']];
  const html = 항목.filter(([k]) => k === '' || k === '질문' || id).map(([k, 이름]) => {
    const href = k ? 화면주소(k, id) : '#/';
    const 지금 = (화면 || '') === k ? ' aria-current="page"' : '';
    const 배지 = k === '질문' && 수 ? ` <span class="수" aria-label="기다리는 질문 ${수}개">${수}</span>` : '';
    const 멈춤 = k === '이력' && (앱.상태?.멈춤 || []).length ? ' <span class="수" aria-label="멈춘 작업 있음">!</span>' : '';
    return `<a href="${href}"${지금}>${이름}${배지}${멈춤}</a>`;
  }).join('');
  const 메뉴 = $('#단계메뉴');
  if (메뉴.dataset.html !== html) { 메뉴.innerHTML = html; 메뉴.dataset.html = html; }
  document.title = (수 ? `(${수}) ` : '') + '여행 스튜디오';
}

function 새질문살피기() {
  const 기다림 = 앱.질문.filter((q) => q.상태 === '기다림');
  const 새것 = 기다림.filter((q) => !앱.본질문.has(q.id));
  기다림.forEach((q) => 앱.본질문.add(q.id));
  if (!앱.처음질문 && 새것.length) {
    쪽지(`Claude가 새 질문을 남겼어요: ${새것[0].제목}${새것.length > 1 ? ` 외 ${새것.length - 1}개` : ''}`,
      { 단추: '답하러 가기', 할일: 화면주소('질문', 새것[0].여행ID || 앱.여행ID), 시간: 15000 });
  }
  앱.처음질문 = false;
}
function 알림글(x) { return typeof x === 'string' ? x : (x?.글 || ''); }
function 새알림살피기() {
  const 지금 = 앱.상태?.알림 || [];
  const 전 = 앱.본알림;
  앱.본알림 = new Set(지금.map((x) => x.id || 알림글(x)));
  if (!전) return; // 처음 열었을 때는 지난 알림을 띄우지 않음
  지금.filter((x) => !전.has(x.id || 알림글(x))).slice(-2).forEach((x) => 쪽지('알림: ' + 알림글(x), { 시간: 10000 }));
}

function 요청단추새로고침() {
  const 대기 = 앱.상태?.대기요청 || [];
  $$('[data-할일="요청"]').forEach((b) => {
    const 내용 = b.dataset.내용 ? JSON.parse(b.dataset.내용) : {};
    const 보냄 = 대기.some((r) => r.종류 === b.dataset.종류 && (r.여행ID || null) === (앱.여행ID || null) &&
      (!내용.편ID || (r.내용 || {}).편ID === 내용.편ID) && (!내용.작업ID || (r.내용 || {}).작업ID === 내용.작업ID));
    if (보냄 === (b.dataset.보냄 === '1')) return;
    b.dataset.보냄 = 보냄 ? '1' : '';
    b.disabled = 보냄;
    if (보냄) { b.dataset.원래글 = b.textContent; b.textContent = '요청 보냄 · Claude 기다리는 중'; }
    else if (b.dataset.원래글) b.textContent = b.dataset.원래글;
  });
}

// ───────────────────────────── Claude 연결하기
async function 클로드연결() {
  let r;
  try { r = await API('/api/claude연결', {}); } catch (e) { r = { 열림: false, 이유: e.message, 폴더: '', 문구: '여행 스튜디오 연결해줘' }; }
  창열기(`<h2>Claude 연결하기</h2>
    ${r.열림
      ? `<p>Claude 앱을 열었어요. 앱에 <b>폴더 확인 창</b>이 뜨면 확인을 누르고, 입력칸에 채워진 <b>“${h(r.문구)}”</b>를 확인한 뒤 <b>Enter</b>를 누르세요.</p>`
      : `<p>Claude 앱을 자동으로 열지 못했어요.${r.이유 ? ` <span class="흐림">(${h(r.이유)})</span>` : ''}</p>`}
    <h3>${r.열림 ? '창이 안 뜨면' : '직접 연결하기'}</h3>
    <ol>
      <li>Claude 데스크탑 앱 → <b>Code</b> 탭</li>
      <li>이 폴더를 열기: <code>${h(r.폴더)}</code> <button type="button" class="단추 단추-작게" data-할일="복사" data-값="${h(r.폴더)}">폴더 경로 복사</button></li>
      <li>입력칸에 <b>${h(r.문구)}</b> 입력 → Enter <button type="button" class="단추 단추-작게" data-할일="복사" data-값="${h(r.문구)}">문구 복사</button></li>
    </ol>
    <p class="흐림작게">연결되면 위쪽 표시가 ‘Claude 연결됨’으로 바뀌어요. 그 Claude 창은 켜 두기만 하면 돼요. 처음 한 번은 Claude가 명령 실행을 물어볼 수 있어요.</p>
    <div class="오른쪽"><button type="button" class="단추 단추-주" data-할일="창닫기" autofocus>닫기</button></div>`);
}

// ───────────────────────────── 요청 보내기(Claude 에게)
async function 요청보내기(종류, 내용 = {}, 여행ID = 앱.여행ID) {
  const r = await API('/api/요청', { 종류, 여행ID, 내용 });
  const 끊김 = 앱.상태?.연결?.판정 === '끊김';
  if (r.중복) 쪽지('같은 요청을 이미 보냈어요. Claude가 처리할 때까지 기다려 주세요.');
  else if (끊김) 쪽지(`요청을 보냈어요: ${요청이름[종류]} — 그런데 Claude가 연결되어 있지 않아요.`, { 단추: 'Claude 연결하기', 할일: 클로드연결, 시간: 12000 });
  else 쪽지(`요청을 보냈어요: ${요청이름[종류]}. Claude가 곧 시작해요.`);
  await 살피기();
  return r;
}

// ───────────────────────────── 화면 바꾸기(라우터)
function 경로풀기() {
  let 조각;
  try { 조각 = location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent); } catch { 조각 = ['']; }
  return { 화면: 조각[0] || '', 인자: 조각.slice(1) };
}
const 켜고끄기 = (el) => el.type === 'checkbox' || el.type === 'radio';
function 초안저장() { $$('[data-초안]').forEach((el) => { 앱.초안[el.dataset.초안] = 켜고끄기(el) ? el.checked : el.value; }); }
function 초안복원() {
  $$('[data-초안]').forEach((el) => {
    const v = 앱.초안[el.dataset.초안];
    if (v === undefined) return;
    if (켜고끄기(el)) el.checked = v; else el.value = v;
  });
}
function 선택자(el) {
  const d = el.dataset;
  if (d.초안) return `[data-초안="${CSS.escape(d.초안)}"]`;
  const 조각 = ['할일', 'id', '종류', '번호', '값', '편'].filter((k) => d[k] !== undefined).map((k) => `[data-${k}="${CSS.escape(d[k])}"]`);
  return 조각.length ? 조각.join('') : null;
}
function 포커스기억() {
  const el = document.activeElement;
  if (!el || !본문().contains(el) || el === 본문()) return null;
  return { 선택자: 선택자(el), 시작: el.selectionStart, 끝: el.selectionEnd };
}
function 포커스복원(기억) {
  if (!기억?.선택자) return;
  const el = $(기억.선택자, 본문());
  if (!el) return;
  el.focus({ preventScroll: true });
  if (typeof 기억.시작 === 'number' && el.setSelectionRange) { try { el.setSelectionRange(기억.시작, 기억.끝); } catch { /* 숫자 칸 등 */ } }
}

async function 화면그리기({ 유지 = false } = {}) {
  const { 화면, 인자 } = 경로풀기();
  const 정의 = 화면들[화면] || 화면들[''];
  let 여행ID = 인자[0] || null;
  if (정의.여행필요) {
    if (!여행ID) 여행ID = 앱.여행ID;
    if (!여행ID) { location.hash = '#/'; return; }
  }
  if (여행ID && 여행ID !== 앱.여행ID) { 앱.여행ID = 여행ID; 기억쓰기('현재여행', 여행ID); }
  메뉴그리기();
  const 번호 = ++앱.그리기번호;
  let 데이터;
  try {
    데이터 = await 정의.불러오기(여행ID, 인자.slice(1));
  } catch (e) {
    if (번호 !== 앱.그리기번호) return;
    앱.정의 = null;
    본문().className = '';
    본문().innerHTML = `<section class="판 오류판" role="alert"><h2>불러오지 못했어요</h2><p class="본문글">${h(e.message)}</p>
      <div class="단추줄"><button type="button" class="단추" data-할일="다시">다시 시도</button><a class="단추" href="#/">시작으로</a></div></section>`;
    return;
  }
  if (번호 !== 앱.그리기번호 || 경로풀기().화면 !== 화면) return; // 그 사이 다른 화면으로 감
  앱.화면 = 화면; 앱.정의 = 정의; 앱.데이터 = 데이터; // 그린 화면과 그 데이터를 한 쌍으로 기억
  앱.파일시각 = { ...(앱.상태?.파일시각 || {}) };
  앱.질문서명 = 질문서명();
  if (데이터?.여행서명) 앱.여행서명 = 데이터.여행서명;
  다시그리기({ 유지 });
}
function 다시그리기({ 유지 = true } = {}) { // 받아 둔 데이터로 다시 그리기(날짜 탭 바꾸기 등)
  const 정의 = 앱.정의;
  if (!정의) return;
  초안저장();
  const 포커스 = 포커스기억();
  const 위치 = window.scrollY;
  본문().className = 정의.본문틀 || '';
  본문().innerHTML = 정의.그리기(앱.데이터, 앱.여행ID);
  초안복원();
  정의.붙이기?.(앱.데이터, 앱.여행ID);
  요청단추새로고침(); 테마단추그리기();
  if (유지) { window.scrollTo(0, 위치); 포커스복원(포커스); }
  else { window.scrollTo(0, 0); 본문().focus({ preventScroll: true }); }
}
window.addEventListener('hashchange', () => 화면그리기());

// ───────────────────────────── ① 시작
const 시작화면 = {
  관심: ['질문', '여행목록', '알림'],
  async 불러오기() {
    const [여행, 꿀팁] = await Promise.all([API('/api/여행'), API('/api/꿀팁노트').catch(() => ({ 항목: [] }))]);
    앱.여행들 = 여행.여행 || [];
    if (앱.여행들.length && !앱.여행들.some((t) => t.여행ID === 앱.여행ID)) { // 고른 여행이 없으면 가장 최근 여행
      앱.여행ID = 앱.여행들[0].여행ID; 기억쓰기('현재여행', 앱.여행ID); 메뉴그리기();
    }
    return { 여행: 앱.여행들, 꿀팁, 여행서명: JSON.stringify(여행.여행) };
  },
  그리기({ 여행, 꿀팁 }) {
    const 알림 = (앱.상태?.알림 || []).slice(-5).reverse();
    const 지난 = (앱.상태?.지난알림 || []).slice(-10).reverse();
    return `
    <section class="머리줄">
      <div><h1 class="큰제목">내 여행</h1>
        <p class="설명">사진 폴더를 고르면 Claude가 시간순으로 정리하고, 애매한 것은 질문으로 물어봅니다.</p></div>
      <button type="button" class="단추 단추-주 단추-크게" data-할일="새여행">+ 새 여행 만들기</button>
    </section>
    ${질문띠()}
    ${알림.length || 지난.length ? `<section class="판" aria-labelledby="알림제목">
      <div class="판머리"><h2 id="알림제목">최근 알림</h2>${알림.length > 1 ? '<button type="button" class="단추 단추-작게" data-할일="알림지우기" data-값="">모두 지우기</button>' : ''}</div>
      ${알림.length ? `<ul class="알림줄들">${알림.map((x) => `<li><span>${h(알림글(x))}${x.시각 ? ` <span class="흐림작게">${h(짧은시각(x.시각))}</span>` : ''}</span>
        <button type="button" class="단추 단추-작게" data-할일="알림지우기" data-값="${h(x.id || '')}">지우기<span class="숨김글"> — ${h(알림글(x).slice(0, 30))}</span></button></li>`).join('')}</ul>`
        : '<p class="흐림작게" style="margin:0">새 알림이 없어요.</p>'}
      ${지난.length ? `<details><summary>지난 알림 ${지난.length}개</summary><ul class="알림목록">${지난.map((x) => `<li>${h(알림글(x))} <span class="흐림작게">(${h([x.해결, 짧은시각(x.해결시각 || x.시각)].filter(Boolean).join(' · '))})</span></li>`).join('')}</ul></details>` : ''}
    </section>` : ''}
    <section class="여행카드들" aria-label="여행 목록">
      ${여행.map(여행카드).join('')}
      <article class="새여행안내">
        <h2>새 여행 시작하기</h2>
        <ol>
          <li>기기별로 사진·영상을 한 폴더에 모아 주세요(아이폰, 카메라 …)</li>
          <li>[새 여행 만들기]에서 그 폴더를 고르세요</li>
          <li>원본은 그대로 두고, 사본으로만 작업해요</li>
        </ol>
        ${여행.length ? '' : '<p class="흐림" style="margin:0">아직 만든 여행이 없어요. 위의 [+ 새 여행 만들기]로 시작하세요.</p>'}
      </article>
    </section>
    <section class="판" aria-label="꿀팁 노트">
      <h2>꿀팁 노트에서 기억하는 것</h2>
      ${꿀팁?.항목?.length
        ? `<ul class="알림목록">${꿀팁.항목.slice(-5).reverse().map((x) => `<li>${h(x)}</li>`).join('')}</ul>
           <p class="흐림작게" style="margin:0">지난 여행에서 알려 주신 쿠폰·이벤트를 다음 여행 글에 먼저 제안해요. (꿀팁노트.md)</p>`
        : `<p class="본문글">아직 기억하는 꿀팁이 없어요. 구성안 화면의 [꿀팁 알려 주기]로 쿠폰·이벤트·예약 요령을 알려 주시면, <b>말씀하신 것만</b> 꿀팁노트.md에 적어 두고 다음 여행 글에 먼저 제안해요.</p>`}
    </section>`;
  },
};
function 질문띠() {
  const 기다림 = 앱.질문.filter((q) => q.상태 === '기다림');
  if (!기다림.length) return '';
  const 제목들 = 기다림.slice(0, 3).map((q) => q.제목).join(', ') + (기다림.length > 3 ? ' …' : '');
  return `<a class="질문띠" href="${화면주소('질문', 기다림[0].여행ID || 앱.여행ID)}"><span class="앞">Claude가 질문 ${기다림.length}개를 남겼어요 — ${h(제목들)}</span><span class="뒤">답하러 가기 →</span></a>`;
}
function 여행카드(t) {
  if (t.오류) return `<article class="여행카드"><div class="카드몸"><h2>${h(t.이름)}</h2><p>${h(t.오류)}</p></div></article>`;
  const 칸 = [0, 1, 2].map((i) => (t.썸네일?.[i]
    ? `<div class="칸"><img src="${파일주소(t.여행ID, t.썸네일[i])}" alt="" loading="lazy"></div>`
    : `<div class="칸 빈칸${i}" aria-hidden="true">${i === 0 ? '[대표 사진]' : ''}</div>`)).join('');
  const 이름들 = ['사진 목록', '고르기', '구성안', '글·발행'];
  const 칩 = 이름들.map((이름, i) => (i < t.단계 ? `<span class="칩 칩-끝">${이름} ✓</span>`
    : i === t.단계 ? `<span class="칩 칩-지금">지금: ${이름}</span>` : `<span class="칩">${이름}</span>`)).join('');
  const 갈곳 = [화면주소('타임라인', t.여행ID), 화면주소('타임라인', t.여행ID), 화면주소('구성안', t.여행ID), 화면주소('글', t.여행ID)][t.단계] || 화면주소('타임라인', t.여행ID);
  const 승인 = (t.편들 || []).filter((x) => x.승인 === '승인됨').length;
  const 정보 = [기간글(t.기간), t.목록있음 ? `사진 ${t.사진수}장 · 영상 ${t.영상수}개 · 기기 ${t.기기수}대` : '사진 목록을 아직 만들지 않았어요',
    (t.편들 || []).length ? `글 ${t.편들.filter((x) => x.배치있음).length}/${t.편들.length}편 · 승인 ${승인}편` : ''].filter(Boolean).join(' · ');
  return `<article class="여행카드">
    <div class="카드사진">${칸}</div>
    <div class="카드몸">
      <h2>${h(t.이름)}</h2>
      <p>${h(정보)}</p>
      <div class="칩들" aria-label="진행 단계">${칩}${t.실패작업수 ? `<a class="칩 칩-경고" href="${화면주소('이력', t.여행ID)}">멈춘 작업 ${t.실패작업수}</a>` : ''}</div>
      <a class="단추" href="${갈곳}">이어서 하기<span class="숨김글"> — ${h(t.이름)}</span></a>
    </div></article>`;
}
// 2026-10-08 실측: 여행 기간을 고칠 곳을 못 찾아 헤맸음(여행정보.json 을 직접 열어야 하는 줄 앎) → 사진 화면 위에 '기간 고치기'를 둠
function 기간판(정보, 항목 = []) {
  const 시작 = 정보.기간?.시작 || '', 끝 = 정보.기간?.끝 || '';
  const 뒤집힘 = 시작 && 끝 && 시작 > 끝;
  const 기간밖 = 항목.length > 0 && 항목.every((x) => (x.일차 ?? null) === null);
  const 경고 = 뒤집힘 ? `여행 시작일(${시작})이 끝나는 날(${끝})보다 뒤예요. 날짜를 고쳐 주세요.`
    : 기간밖 ? '사진이 모두 여행 기간 밖으로 잡혔어요. 여행 기간(특히 시작일)이 맞는지 확인해 주세요.' : '';
  return `<div class="${경고 ? '띠 띠-끊김' : '띠 띠-안내'}"><span>여행 기간: <b>${h(기간글(정보.기간) || '아직 없음(사진 날짜로 자동)')}</b>${경고 ? ` — ${h(경고)} 고친 뒤 ‘사진 목록 다시 만들어 달라기’를 눌러 주세요.` : ''}</span>
    <button type="button" class="단추" data-할일="기간창" data-시작="${h(시작)}" data-끝="${h(끝)}">기간 고치기</button></div>`;
}
function 기간창(b) {
  const id = 앱.여행ID;
  const d = 창열기(`<form id="기간폼" class="창폼">
    <h2>여행 기간 고치기</h2>
    <label class="입력묶음">시작일<input class="입력" type="date" name="시작" value="${h(b.dataset.시작 || '')}"></label>
    <label class="입력묶음">끝나는 날<input class="입력" type="date" name="끝" value="${h(b.dataset.끝 || '')}"></label>
    <p class="흐림작게" style="margin:0">비워 두면 사진 날짜로 자동으로 채워져요. 고친 뒤에는 ‘사진 목록 다시 만들어 달라기’를 눌러야 일차가 새로 계산돼요(고른 결정은 그대로).</p>
    <p id="기간상태" class="흐림" role="status" style="margin:0"></p>
    <div class="오른쪽"><button type="button" class="단추" data-할일="창닫기">취소</button><button type="submit" class="단추 단추-주">저장</button></div>
  </form>`);
  const 폼 = d.querySelector('form');
  폼.onsubmit = async (e) => {
    e.preventDefault();
    const 시작 = 폼.시작.value, 끝 = 폼.끝.value;
    if (시작 && 끝 && 시작 > 끝) { $('#기간상태').textContent = `시작일(${시작})이 끝나는 날(${끝})보다 뒤예요. 날짜를 다시 확인해 주세요.`; return; }
    try {
      await API('/api/여행/기간', { 여행ID: id, 시작, 끝 });
      창닫기();
      쪽지('여행 기간을 고쳤어요. 이제 ‘사진 목록 다시 만들어 달라기’를 눌러 주세요.');
      await 화면그리기();
    } catch (err) { $('#기간상태').textContent = err.message; }
  };
}
function 새여행창() {
  const d = 창열기(`<form id="새여행폼" class="창폼">
    <h2>새 여행 만들기</h2>
    <label class="입력묶음">여행 이름<input class="입력" name="이름" required maxlength="60" placeholder="예: 제주 2박3일" autofocus></label>
    <label class="입력묶음">여행 시작일(선택)<input class="입력" type="date" name="시작일"></label>
    <div class="안내상자"><b>다음에 내 PC의 ‘폴더 고르기’ 창이 떠요.</b> 기기별 폴더(아이폰, 카메라 …)를 모아 둔 폴더를 고르세요. 원본은 읽기만 하고 고치거나 옮기지 않아요.</div>
    <p id="새여행상태" class="흐림" role="status" style="margin:0"></p>
    <div class="오른쪽"><button type="button" class="단추" data-할일="창닫기">취소</button><button type="submit" class="단추 단추-주">폴더 고르기</button></div>
  </form>`);
  const 폼 = d.querySelector('form');
  폼.onsubmit = async (e) => {
    e.preventDefault();
    const 이름 = 폼.이름.value.trim();
    if (!이름) return;
    const 단추들 = $$('button', 폼);
    단추들.forEach((b) => { b.disabled = true; });
    $('#새여행상태').textContent = '폴더 고르는 창이 떴어요. 안 보이면 작업 표시줄(Mac은 Dock)의 Python 아이콘을 눌러 주세요.';
    try {
      const r = await API('/api/여행', { 이름, 시작일: 폼.시작일.value || '' });
      if (r.취소) { $('#새여행상태').textContent = r.안내; 단추들.forEach((b) => { b.disabled = false; }); return; }
      창닫기();
      쪽지(`‘${이름}’ 여행을 만들었어요. 이제 사진 목록을 만들어 달라고 해 보세요.`);
      앱.여행ID = r.여행ID; 기억쓰기('현재여행', r.여행ID);
      location.hash = 화면주소('타임라인', r.여행ID);
    } catch (err) {
      $('#새여행상태').textContent = err.message;
      단추들.forEach((b) => { b.disabled = false; });
    }
  };
}

// ───────────────────────────── ② 타임라인·고르기
const 타임라인화면 = {
  여행필요: true, 관심: ['목록', '장소', '정보'],
  async 불러오기(id) {
    const [목록, 장소] = await Promise.all([API('/api/목록?' + 질의({ 여행: id })), API('/api/장소?' + 질의({ 여행: id }))]);
    return { 목록, 장소: 장소.장소 || {} };
  },
  그리기(d, id) {
    const 정보 = d.목록.여행정보 || {};
    const 이름 = 정보.이름 || id;
    const 원본 = (정보.원본폴더 || []).join(', ');
    if (!d.목록.목록있음) {
      return `<section class="머리줄"><div><h1 class="중간제목">${h(이름)} · 사진 목록</h1>
        <p class="설명">원본 폴더: <code>${h(원본 || '(없음)')}</code> — 원본은 읽기만 해요.</p></div></section>
        ${기간판(정보)}
        <section class="판 빈판">
          <h2>아직 사진 목록이 없어요</h2>
          <p class="본문글">Claude가 원본 폴더를 읽어 촬영 시각·장소·기기를 정리하고, 화면에서 볼 작은 사본(미리보기·썸네일)을 만들어요. 원본은 고치거나 옮기지 않아요.</p>
          <button type="button" class="단추 단추-주 단추-크게" data-할일="요청" data-종류="목록만들기">사진 목록 만들어 달라기</button>
          <p class="흐림작게" style="margin:0">사진이 많으면 몇 분 걸려요. 진행 상황은 위쪽 연결 표시에 나와요.</p>
        </section>`;
    }
    const 항목 = d.목록.항목.filter((x) => x && x.id);
    const 보기 = (앱.보기[id] ||= { 일차: undefined, 거르기: '전체' });
    const 일차들 = [...new Set(항목.map((x) => x.일차 ?? null))].filter((n) => n === null || Number.isInteger(n)).sort((a, b) => (a ?? 999) - (b ?? 999));
    if (!일차들.includes(보기.일차)) 보기.일차 = 일차들[0];
    const 셈 = { 사용: 0, 대표: 0, 제외: 0, 미정: 0 };
    항목.forEach((x) => { 셈[x.사용자결정 in 셈 ? x.사용자결정 : '미정'] += 1; });
    const 시각주의 = 항목.filter((x) => 시각약함(x, 정보)).length;
    const 판정있음 = 항목.some((x) => x.판정 && (x.판정.제외후보 || x.판정.대표후보 || (x.판정.사유 || []).length));
    const 거르기 = { 전체: () => true, 제외후보: (x) => x.판정?.제외후보, 대표후보: (x) => x.판정?.대표후보, 시각확인: (x) => 시각약함(x, 정보), 미정: (x) => (x.사용자결정 || '미정') === '미정' };
    const 거르기이름 = { 전체: '전체', 제외후보: '제외 후보', 대표후보: '대표 후보', 시각확인: '시각 확인 필요', 미정: '아직 안 정함' };
    const 이날 = 항목.filter((x) => (x.일차 ?? null) === 보기.일차).sort((a, b) => String(a.촬영시각 || '').localeCompare(String(b.촬영시각 || '')));
    const 묶음들 = 사진묶기(이날, d.장소).map((g) => ({ ...g, 항목: g.항목.filter(거르기[보기.거르기] || 거르기.전체) })).filter((g) => g.항목.length);
    return `
    <section class="머리줄">
      <div><h1 class="중간제목">${h(이름)} · ${h(일차라벨(보기.일차, 정보, 항목))}</h1>
        <p class="설명">사진을 누를 때마다 <b>사용 → 대표 → 제외</b>로 바뀝니다. 대표 사진은 블로그에 한 장씩 크게 들어가요.</p></div>
      <div class="단추줄">
        <button type="button" class="단추" data-할일="요청" data-종류="고르기">${판정있음 ? 'Claude에게 다시 골라 달라기' : 'Claude에게 골라 달라기'}</button>
        <button type="button" class="단추 단추-주" data-할일="요청" data-종류="구성안">고르기 끝 → 구성안 받기</button>
      </div>
    </section>
    ${기간판(정보, 항목)}
    <section aria-label="요약(여행 전체)" class="요약" id="요약">${요약칸들(셈, 시각주의)}</section>
    <div class="도구줄">
      <div class="탭들" role="group" aria-label="날짜">
        ${일차들.map((n) => `<button type="button" class="탭" aria-pressed="${n === 보기.일차}" data-할일="일차" data-값="${h(정수(n, ''))}">${h(일차라벨(n, 정보, 항목, true))} <span>${항목.filter((x) => (x.일차 ?? null) === n).length}</span></button>`).join('')}
      </div>
      <div class="탭들" role="group" aria-label="골라 보기">
        ${Object.keys(거르기).map((k) => `<button type="button" class="탭" aria-pressed="${보기.거르기 === k}" data-할일="거르기" data-값="${k}">${거르기이름[k]}</button>`).join('')}
      </div>
    </div>
    ${셈.미정 && 판정있음 ? `<div class="띠 띠-안내"><span>아직 안 정한 사진 ${셈.미정}장 — Claude의 추천(제외 후보는 제외, 대표 후보는 대표, 나머지는 사용)대로 한 번에 정할 수 있어요.</span>
      <button type="button" class="단추" data-할일="추천대로">추천대로 정하기</button></div>` : ''}
    ${묶음들.length ? 묶음들.map((g) => `
      <section class="묶음" aria-label="${h(g.제목)}">
        <div class="묶음머리"><h2>${h(g.제목)}</h2><span>${h(g.메모)}</span></div>
        <div class="사진격자">${g.항목.map((x) => 사진칸(x, id, 정보)).join('')}</div>
      </section>`).join('') : `<section class="판 빈판"><p class="본문글">이 조건에 맞는 사진이 없어요.</p></section>`}
    <section class="판">
      <h2>원본 폴더에 사진을 더 넣었나요?</h2>
      <p class="본문글">원본 폴더: <code>${h(원본)}</code> — 다시 읽어도 지금까지 고른 결정은 그대로 둬요.</p>
      <div class="단추줄"><button type="button" class="단추" data-할일="요청" data-종류="목록만들기">사진 목록 다시 만들어 달라기</button></div>
    </section>`;
  },
};
function 요약칸들(셈, 시각주의) {
  return `
    <div class="요약칸"><span class="이름">사용</span><span class="값">${셈.사용}장</span></div>
    <div class="요약칸"><span class="이름">대표(낱장)</span><span class="값 값-대표">${셈.대표}장</span></div>
    <div class="요약칸"><span class="이름">제외</span><span class="값">${셈.제외}장</span></div>
    <div class="요약칸"><span class="이름">아직 안 정함</span><span class="값">${셈.미정}장</span></div>
    <div class="요약칸"><span class="이름">시각 확인 필요</span><span class="값 값-경고">${시각주의}장</span>
      ${시각주의 ? '<button type="button" class="단추 단추-작게" data-할일="요청" data-종류="시계확인">기기 시계 확인 부탁</button>' : ''}</div>`;
}
function 일차라벨(n, 정보, 항목, 짧게 = false) {
  if (n === null || n === undefined) return '날짜 모름';
  const 첫 = 항목.find((x) => x.일차 === n && x.촬영시각);
  const 날 = 정보.기간?.시작 ? 날짜더하기(정보.기간.시작, n - 1) : 첫?.촬영시각?.slice(0, 10);
  const d = 날짜조각(날);
  if (!d) return `${n}일차`;
  return 짧게 ? `${n}일차 · ${d.월}/${d.일}(${요일글(d)})` : `${n}일차 (${d.월}월 ${d.일}일 ${요일글(d)})`;
}
function 사진묶기(항목, 장소표) { // 같은 장소가 이어지거나, 장소를 모를 때는 30분 안에 찍은 것끼리 한 묶음
  const 묶음들 = [];
  let 지금 = null;
  for (const x of 항목) {
    const 장소 = x.장소ID || null, t = 분(x);
    const 새로 = !지금 || 장소 !== 지금.장소 || (t !== null && 지금.끝 !== null && t - 지금.끝 > (장소 ? 90 : 30));
    if (새로) { 지금 = { 장소, 시작: t, 끝: t, 항목: [] }; 묶음들.push(지금); }
    지금.항목.push(x);
    if (t !== null) 지금.끝 = t;
  }
  return 묶음들.map((g) => {
    const p = g.장소 ? 장소표[g.장소] : null;
    const 장소이름 = p ? (p.이름 || g.장소) + (p.확인됨 ? '' : ' (추정)') : (g.장소 ? g.장소 : '장소 정보 없음');
    const 사진수 = g.항목.filter((x) => x.종류 !== '영상').length, 영상수 = g.항목.length - 사진수;
    const 메모 = [`사진 ${사진수}장${영상수 ? ` · 영상 ${영상수}개` : ''}`, p && !p.확인됨 ? '장소 이름 확인 필요' : '', p?.숨김 ? '숨길 장소(지도·글에서 빠짐)' : '',
      (() => { const 연사 = new Set(g.항목.map((x) => x.점수?.연사묶음).filter(Boolean)); return 연사.size ? `연사 묶음 ${연사.size}개` : ''; })()].filter(Boolean).join(' · ');
    return { 제목: `${시각글(g.항목[0])} · ${장소이름}`, 메모, 항목: g.항목 };
  });
}
function 사진칸(x, id, 정보) {
  const 결정 = ['사용', '대표', '제외'].includes(x.사용자결정) ? x.사용자결정 : '미정';
  const 다음 = 결정순서[결정];
  const 약함 = 시각약함(x, 정보);
  const 시각 = 시각글(x, Boolean(x.점수?.연사묶음));
  const 사유 = [];
  if (x.판정?.대표후보) 사유.push('대표 후보');
  사유.push(...(x.판정?.사유 || []));
  if (x.판정?.제외후보 && !(x.판정?.사유 || []).length) 사유.push('제외 후보');
  const 이름 = x.장면설명 || String(x.원본 || x.id).split(/[\\/]/).pop();
  const 라벨 = `${이름}, ${x.종류 === '영상' ? '영상 ' : ''}${x.기기 || ''} ${시각}${약함 ? ', 시각 확인 필요' : ''}. 지금 ${결정}. 누르면 ${다음}(으)로 바뀜`;
  return `<button type="button" class="사진칸" data-할일="결정" data-id="${h(x.id)}" data-결정="${결정}" aria-label="${h(라벨)}" title="${h(이름)}">
    <span class="그림">${x.썸네일 ? `<img src="${파일주소(id, x.썸네일)}" alt="" loading="lazy">` : `<span>[${h(이름)}]</span>`}
      ${x.종류 === '영상' ? `<span class="표식">▶ 영상 ${길이글(x.영상길이초)}</span>` : ''}
      ${결정 === '대표' ? '<span class="표식 표식-대표">★ 대표</span>' : ''}</span>
    <span class="아래"><span>${h(x.기기 || '')} ${h(시각)}${약함 ? ` <span class="주의" title="${h(약한출처[x.시각출처])}">⚠</span>` : ''}</span><span class="상태">${결정}</span></span>
    ${사유.length ? `<span class="사유">${h(사유.join(' · '))}</span>` : ''}
  </button>`;
}
async function 결정바꾸기(단추) {
  const id = 단추.dataset.id, 여행ID = 앱.여행ID;
  const 항목 = 앱.데이터?.목록?.항목?.find((x) => x.id === id);
  if (!항목) return;
  const 전 = 항목.사용자결정 || '미정';
  const 다음 = 결정순서[전] || '사용';
  const 칸바꾸기 = () => {
    const 새 = document.createElement('div');
    새.innerHTML = 사진칸(항목, 여행ID, 앱.데이터.목록.여행정보);
    const 새칸 = 새.firstElementChild;
    const 옛칸 = $(`.사진칸[data-id="${CSS.escape(id)}"]`, 본문());
    if (옛칸) { const 포커스 = document.activeElement === 옛칸; 옛칸.replaceWith(새칸); if (포커스) 새칸.focus(); }
    const 셈 = { 사용: 0, 대표: 0, 제외: 0, 미정: 0 };
    앱.데이터.목록.항목.forEach((x) => { 셈[x.사용자결정 in 셈 ? x.사용자결정 : '미정'] += 1; });
    const 정보 = 앱.데이터.목록.여행정보;
    if ($('#요약')) $('#요약').innerHTML = 요약칸들(셈, 앱.데이터.목록.항목.filter((x) => 시각약함(x, 정보)).length);
    요청단추새로고침();
  };
  항목.사용자결정 = 다음; 칸바꾸기(); // 먼저 화면을 바꾸고(빠르게) 서버에 저장
  try {
    const r = await API('/api/결정', { 여행: 여행ID, id, 결정: 다음 });
    if (r.수정시각) 앱.파일시각.목록 = r.수정시각;
  } catch (e) {
    항목.사용자결정 = 전; 칸바꾸기();
    오류쪽지(e);
  }
}
async function 추천대로() {
  const 결정목록 = 앱.데이터.목록.항목.filter((x) => (x.사용자결정 || '미정') === '미정')
    .map((x) => ({ id: x.id, 결정: x.판정?.제외후보 ? '제외' : x.판정?.대표후보 ? '대표' : '사용' }));
  const 수 = (k) => 결정목록.filter((x) => x.결정 === k).length;
  if (!결정목록.length) return;
  if (!await 확인창(`아직 안 정한 ${결정목록.length}장을 Claude 추천대로 정할까요?<br>사용 ${수('사용')}장 · 대표 ${수('대표')}장 · 제외 ${수('제외')}장<br><span class="흐림">사진은 지우지 않아요. 나중에 한 장씩 다시 바꿀 수 있어요.</span>`, '추천대로 정하기', '그만두기')) return;
  try {
    await API('/api/결정', { 여행: 앱.여행ID, 결정목록 });
    쪽지(`${결정목록.length}장을 정했어요.`);
    화면그리기({ 유지: true });
  } catch (e) { 오류쪽지(e); }
}

// ───────────────────────────── ③ 질문 카드
const 질문화면 = {
  관심: ['질문'], 본문틀: '좁게',
  async 불러오기(id) { return API('/api/질문?' + 질의({ 여행: id || 앱.여행ID })); },
  그리기(d) {
    const 모두 = d.질문 || [];
    const 기다림 = 모두.filter((q) => q.상태 === '기다림');
    const 답함 = 모두.filter((q) => q.상태 === '답함');
    const 처리됨 = 모두.filter((q) => q.상태 === '처리됨');
    return `
    <div><h1 class="중간제목">Claude의 질문</h1>
      <p class="설명">추측하지 않고 물어봐요. 고르거나 짧게 적고 [보내기]를 누르면 Claude가 이어서 작업합니다.</p></div>
    ${기다림.length ? 기다림.map((q, i) => 질문카드(q, i + 1)).join('') : `<section class="판 빈판"><h2>지금은 질문이 없어요</h2>
      <p class="본문글">Claude가 애매한 것(기기 시계, 장소 이름, 컨셉, 사진 속 사람 …)을 만나면 여기에 카드가 생기고, 위쪽 메뉴의 ‘질문’ 옆에 숫자가 떠요.</p></section>`}
    ${답함.length ? `<section class="판"><h2>보낸 답 — Claude가 확인하면 이어서 작업해요</h2>${답함.map(답요약).join('')}</section>` : ''}
    ${처리됨.length ? `<details class="판"><summary>지난 질문 ${처리됨.length}개</summary>${처리됨.slice().reverse().map(답요약).join('')}</details>` : ''}
    <section class="판" aria-labelledby="자유제목">
      <h2 id="자유제목">Claude에게 따로 부탁하기</h2>
      <label class="입력묶음">부탁할 내용<textarea class="입력" rows="3" data-초안="자유요청" placeholder="예: 2일차 우도 사진 중 바다가 잘 보이는 것을 대표 후보로 더 골라 주세요"></textarea></label>
      <div class="오른쪽"><button type="button" class="단추" data-할일="자유요청">부탁 보내기</button></div>
    </section>`;
  },
};
function 질문카드(q, 번호) {
  const 선택 = 앱.초안[`선택-${q.id}`] || [];
  const 사진 = q.사진정보 || [];
  const 여러장 = 사진.length > 2;
  const 사진html = 사진.length ? `<div class="질문사진${여러장 ? ' 여러장' : ''}">${사진.map((p) => {
    const 경로 = (여러장 ? p.썸네일 : p.미리보기 || p.썸네일);
    const 날 = 날짜조각(p.촬영시각);
    const 설명 = [p.기기, 날 ? `${날.월}월 ${날.일}일` : ''].filter(Boolean).join(' · ');
    return `<figure><div class="그림">${경로 ? `<img src="${파일주소(q.여행ID || 앱.여행ID, 경로)}" alt="${h(p.장면설명 || `${p.기기 || ''} 사진 ${p.id}`)}" loading="lazy">` : `[${h(p.id)}]`}</div>
      <figcaption>${h(설명)} <b>${h(p.촬영시각 ? 시각글(p) : '')}</b></figcaption></figure>`;
  }).join('')}</div>` : '';
  const 선택지 = q.선택지 || [];
  const 무리 = q.여러개선택 ? 'group' : 'radiogroup';
  const 역할 = q.여러개선택 ? 'checkbox' : 'radio';
  return `<article class="판 질문카드" aria-labelledby="질문제목-${h(q.id)}">
    <div class="카드머리"><h2 id="질문제목-${h(q.id)}">${번호}. ${h(q.제목)}</h2>
      <span class="흐림작게">${h(단계이름[q.관련종류] || '')}${q.관련종류 ? ' 단계' : ''}${사진.length ? ` · 사진 ${사진.length}장` : ''}</span></div>
    ${q.설명 ? `<p class="본문글">${굵게(q.설명)}</p>` : ''}
    ${사진html}
    ${선택지.length ? `<div role="${무리}" aria-label="답 고르기${q.여러개선택 ? '(여러 개 가능)' : ''}" class="선택지들">
      ${선택지.map((s) => `<button type="button" role="${역할}" class="선택지" aria-checked="${선택.includes(s)}" data-할일="선택" data-id="${h(q.id)}" data-값="${h(s)}">${h(s)}</button>`).join('')}</div>` : ''}
    ${q.입력칸 || !선택지.length ? `<label class="입력묶음">${선택지.length ? '직접 적기(선택)' : '답 적기'}
      <input class="입력" type="text" data-초안="답-${h(q.id)}" placeholder="${h(q.입력예시 || (선택지.length ? '고른 답에 덧붙일 말이 있으면 적어 주세요' : ''))}"></label>` : ''}
    <div class="오른쪽"><button type="button" class="단추 단추-주 단추-크게" data-할일="답보내기" data-id="${h(q.id)}">보내기</button></div>
  </article>`;
}
function 답요약(q) {
  const 답 = q.답변 || {};
  const 글 = [...(답.선택 || []), 답.입력].filter(Boolean).join(' / ');
  return `<div style="display:flex;flex-direction:column;gap:6px"><b>${h(q.제목)}</b><p class="내답">내 답: ${h(글 || '(없음)')}</p></div>`;
}
function 선택바꾸기(단추) {
  const qid = 단추.dataset.id, 값 = 단추.dataset.값;
  const q = 앱.데이터?.질문?.find((x) => x.id === qid);
  let 선택 = 앱.초안[`선택-${qid}`] || [];
  if (q?.여러개선택) 선택 = 선택.includes(값) ? 선택.filter((x) => x !== 값) : [...선택, 값];
  else 선택 = [값];
  앱.초안[`선택-${qid}`] = 선택;
  $$(`.선택지[data-id="${CSS.escape(qid)}"]`).forEach((b) => b.setAttribute('aria-checked', String(선택.includes(b.dataset.값))));
}
async function 답보내기(단추) {
  const qid = 단추.dataset.id;
  const 선택 = 앱.초안[`선택-${qid}`] || [];
  const 입력 = ($(`[data-초안="${CSS.escape('답-' + qid)}"]`)?.value || '').trim();
  if (!선택.length && !입력) { 쪽지('답을 고르거나 적어 주세요.', { 종류: '오류' }); return; }
  단추.disabled = true;
  try {
    await API('/api/답변', { 질문id: qid, 선택, 입력 });
    delete 앱.초안[`선택-${qid}`]; delete 앱.초안[`답-${qid}`];
    쪽지('답을 보냈어요. Claude가 이어서 작업해요.');
    await 살피기();
    화면그리기({ 유지: true });
  } catch (e) { 단추.disabled = false; 오류쪽지(e); }
}

// ───────────────────────────── ④ 구성안 (규약 2.3: 안[].편[{편ID, 제목안, 범위}], 안.추천)
const 구성안화면 = {
  여행필요: true, 관심: ['구성안', '정보'],
  async 불러오기(id) {
    const [안, 여행] = await Promise.all([JSON파일(id, '원고/구성안.json'), API('/api/여행')]);
    return { 안, 여행: (여행.여행 || []).find((t) => t.여행ID === id) || {} };
  },
  그리기(d, id) {
    const t = d.여행;
    if (!d.안 || !(d.안.안 || []).length) {
      return `<div><h1 class="중간제목">이번 여행, 어떻게 올릴까요?</h1><p class="설명">${h(t.이름 || id)}</p></div>
      <section class="판 빈판"><h2>아직 구성안이 없어요</h2>
        <p class="본문글">사진 고르기를 마치고 [구성안 받기]를 누르면 Claude가 세 가지 안(예: 일자별 연재 / 한눈에 보기 + 일자별 / 테마별)을 만들어요. 컨셉을 모르면 먼저 질문 카드로 물어봐요.</p>
        <div class="단추줄"><button type="button" class="단추 단추-주 단추-크게" data-할일="요청" data-종류="구성안">구성안 받기</button>
          <a class="단추 단추-크게" href="${화면주소('타임라인', id)}">사진 고르기로</a></div></section>
      ${꿀팁판()}`;
    }
    const 보기 = (앱.보기['안-' + id] ||= {});
    const 선택 = 정수(보기.선택) ?? 정수(t.선택한구성안);
    const 안 = d.안;
    const 사진 = 안.사진수 ?? ((t.결정?.사용 || 0) + (t.결정?.대표 || 0));
    const 고른것 = 정수(t.선택한구성안) !== null && (t.편들 || []).length;
    return `
    <div><h1 class="중간제목">이번 여행, 어떻게 올릴까요?</h1>
      <p class="설명">${안.컨셉 ? `알려 주신 컨셉 <b>“${h(안.컨셉)}”</b>와 ` : ''}고른 사진 ${h(사진)}장${안.영상수 ? `·영상 ${h(안.영상수)}개` : ''}로 ${안.안.length}가지 안을 만들었어요.</p></div>
    ${고른것 ? `<div class="띠 띠-안내"><span>지금 고른 안: ${h(정수(t.선택한구성안, '?'))}번 · 글 ${t.편들.length}편(${h(t.편들.map((x) => x.편ID).join(', '))})</span><a class="단추" href="${화면주소('글', id)}">글 화면으로 →</a></div>` : ''}
    <section class="안들" aria-label="구성안">
      ${안.안.map((p, i) => {
        const 번호 = 정수(p.번호, i + 1); // 구성안.json 은 Claude 가 쓰는 파일 → 정수만
        const 골랐음 = 선택 === 번호;
        const 편 = (p.편 || []).map((x) => (typeof x === 'string' ? x : `${x.제목안 || x.편ID}${x.편ID && x.제목안 ? ` (${x.편ID})` : ''}`));
        const 추천 = p.추천 === true || 안.추천 === 번호;
        return `<article class="안" data-선택="${골랐음}" aria-label="안 ${h(번호)}">
          <div class="윗줄"><b>안 ${h(번호)}${p.방식 ? ` · ${h(p.방식)}` : ''}</b><span>${추천 ? '<span class="추천표">Claude 추천</span> ' : ''}글 ${h(p.편수 ?? (편.length || (p.글 || []).length))}편</span></div>
          <h2>${h(p.이름 || '')}</h2>
          ${p.설명 ? `<p class="본문글">${굵게(p.설명)}</p>` : ''}
          ${(편.length ? 편 : (p.글 || [])).length ? `<ul>${(편.length ? 편 : p.글).map((x) => `<li>${h(x)}</li>`).join('')}</ul>` : ''}
          ${p.좋은점 ? `<p class="작은글"><b>좋은 점</b> ${h(p.좋은점)}</p>` : ''}
          ${p.아쉬운점 ? `<p class="작은글"><b>아쉬운 점</b> ${h(p.아쉬운점)}</p>` : ''}
          <button type="button" class="단추${골랐음 ? ' 단추-주' : ''}" aria-pressed="${골랐음}" data-할일="안고르기" data-번호="${h(번호)}">${골랐음 ? '✓ 선택됨' : '이 안 고르기'}</button>
        </article>`;
      }).join('')}
    </section>
    <div class="아래띠">
      <label class="입력묶음">고칠 점이 있으면 적어 주세요(선택)
        <input class="입력" type="text" data-초안="구성안고칠점-${h(id)}" placeholder="예: 2일차 우도는 따로 한 편으로 빼 주세요"></label>
      <div class="단추줄">
        <button type="button" class="단추 단추-크게" data-할일="구성안다시">고칠 점 반영해 다시 받기</button>
        <button type="button" class="단추 단추-주 단추-크게" data-할일="안정하기" ${선택 !== null ? '' : 'disabled aria-describedby="안고르기안내"'}>이 안으로 정하기 →</button>
      </div>
      ${선택 !== null ? '' : '<p id="안고르기안내" class="흐림작게" style="margin:0;flex-basis:100%">먼저 위에서 안 하나를 골라 주세요.</p>'}
    </div>
    ${꿀팁판()}`;
  },
};
function 꿀팁판() {
  return `<section class="판"><h2>글을 쓰기 전에 — 꿀팁 알려 주기</h2>
    <p class="본문글">쿠폰·이벤트·할인·예약 요령 같은 꿀팁이 있었나요? Claude가 질문 카드로 물어보고, <b>말씀하신 것만</b> 꿀팁 노트에 적어 글에 넣어요.</p>
    <div class="단추줄"><button type="button" class="단추" data-할일="요청" data-종류="꿀팁인터뷰">꿀팁 알려 주기</button></div></section>`;
}

// ───────────────────────────── ⑤ 지도·장소
const 지도화면 = {
  여행필요: true, 관심: ['장소', '지도', '목록'],
  async 불러오기(id) {
    const [장소, 목록] = await Promise.all([API('/api/장소?' + 질의({ 여행: id })), API('/api/목록?' + 질의({ 여행: id }))]);
    return { 장소, 목록 };
  },
  그리기(d, id) {
    const 장소표 = d.장소.장소 || {};
    const 지도 = d.장소.지도이미지 || [];
    const 장소들 = Object.entries(장소표);
    const 장소사진 = {};
    (d.목록.항목 || []).forEach((x) => { if (x.장소ID && x.썸네일 && x.사용자결정 !== '제외') (장소사진[x.장소ID] ||= []).push(x); });
    return `
    <section class="머리줄">
      <div><h1 class="중간제목">지도와 장소</h1>
        <p class="설명">사진 위치(GPS)로 장소를 묶었어요. 이름이 맞는지 확인하고, 숙소·집처럼 알리고 싶지 않은 곳은 숨겨 주세요. 숨긴 장소는 지도와 글에서 빠져요.</p></div>
      <div class="단추줄"><button type="button" class="단추 단추-주" data-할일="요청" data-종류="지도">${지도.length ? '동선 지도 다시 만들어 달라기' : '동선 지도 만들어 달라기'}</button></div>
    </section>
    ${지도.length ? `<section class="지도들" aria-label="동선 지도">${지도.map((m) => `<figure>
        <img src="${파일주소(id, m.경로)}" alt="${h(m.일차 ? `${m.일차}일차 동선 지도` : m.이름)}" loading="lazy">
        <figcaption><span>${h(m.일차 ? `${m.일차}일차 동선` : m.이름)}</span><span class="흐림작게">© OpenStreetMap contributors</span></figcaption></figure>`).join('')}</section>`
      : `<section class="판 빈판"><h2>아직 동선 지도가 없어요</h2><p class="본문글">[동선 지도 만들어 달라기]를 누르면 Claude가 사진 위치로 장소를 묶고, 일자별 동선 지도(OpenStreetMap)를 만들어요. 장소 이름은 지도에서 찾은 ‘추정’이라 질문 카드로 확인해요.</p></section>`}
    ${장소들.length ? `<section class="판" aria-labelledby="장소제목">
      <h2 id="장소제목">장소 확인 (${장소들.length}곳)</h2>
      <p class="본문글">이름을 고치거나 [이름이 맞아요]를 누르고, 숨길 곳은 체크한 뒤 아래 [바꾼 내용 보내기]를 누르세요. Claude가 장소 목록과 지도를 고쳐요.</p>
      <ul class="장소목록">${장소들.map(([pid, p]) => 장소줄(id, pid, p, 장소사진[pid] || [])).join('')}</ul>
      <div class="오른쪽"><button type="button" class="단추 단추-주 단추-크게" data-할일="장소보내기">바꾼 내용 보내기(지도 다시 그리기)</button></div>
    </section>` : ''}`;
  },
};
function 장소줄(id, pid, p, 사진) {
  const 맞음 = 앱.초안[`장소맞음-${id}-${pid}`] ?? false;
  return `<li class="장소줄" data-숨김="${Boolean(p.숨김)}">
    <div class="장소사진" aria-hidden="true">${사진.slice(0, 4).map((x) => `<img src="${파일주소(id, x.썸네일)}" alt="" loading="lazy">`).join('') || '<span></span>'}</div>
    <div class="장소내용">
      <label class="입력묶음">장소 이름 (${h(pid)})<input class="입력" type="text" value="${h(p.이름 || '')}" data-초안="장소이름-${h(id)}-${h(pid)}"></label>
      <div class="흐림작게">사진 ${h(p.사진수 ?? 사진.length)}장 · <span class="확인표 ${p.확인됨 ? '확인표-됨">확인됨 ✓' : '확인표-추정">추정 — 확인 필요'}</span>${p.숨김 ? ' · 지금 숨김' : ''}</div>
      ${p.숨김 && p.숨김출처 === '자동' && !p.공개확인 ? `<p class="멈춤상자" style="margin:0">기본으로 숨겼어요 — 숙소·집일 수 있어요${(p.비공개이유 || []).length ? `(${h(p.비공개이유.join(', '))})` : ''}. 공개해도 되는 곳(일출 명소 등)이면 Claude의 질문 카드에서 ‘공개해도 돼요’를 고르거나, 아래 체크를 풀고 보내세요. 이름은 공개를 고른 뒤에 찾아요.</p>` : ''}
      <div class="단추줄">
        ${p.확인됨 ? '' : `<button type="button" class="단추 단추-작게${맞음 ? ' 단추-주' : ''}" aria-pressed="${맞음}" data-할일="장소맞음" data-id="${h(pid)}">${맞음 ? '✓ 이름 맞음' : '이름이 맞아요'}</button>`}
        <label class="체크"><input type="checkbox" data-초안="장소숨김-${h(id)}-${h(pid)}" ${p.숨김 ? 'checked' : ''}> 지도·글에서 숨기기(숙소·집)</label>
      </div>
    </div></li>`;
}
async function 장소보내기() {
  const id = 앱.여행ID;
  초안저장();
  const 수정 = [];
  for (const [pid, p] of Object.entries(앱.데이터.장소.장소 || {})) {
    const 이름 = (앱.초안[`장소이름-${id}-${pid}`] ?? p.이름 ?? '').trim();
    const 숨김 = 앱.초안[`장소숨김-${id}-${pid}`] ?? Boolean(p.숨김);
    const 맞음 = 앱.초안[`장소맞음-${id}-${pid}`] ?? false;
    const 이름바뀜 = 이름 !== (p.이름 || '');
    // 숨김을 푼 것 = 사람이 '공개해도 됨'을 고른 것(기본 숨김된 곳은 Claude 가 이 표시가 있을 때만 --공개)
    if (이름바뀜 || 맞음 || 숨김 !== Boolean(p.숨김)) 수정.push({ 장소ID: pid, 이름, 확인됨: Boolean(p.확인됨 || 맞음 || 이름바뀜), 숨김, ...(!숨김 && p.숨김 ? { 공개: true } : {}) });
  }
  if (!수정.length) { 쪽지('바꾼 내용이 없어요.'); return; }
  try {
    await 요청보내기('지도', { 장소수정: 수정 });
    Object.keys(앱.초안).filter((k) => /^장소(이름|숨김|맞음)-/.test(k) && k.includes(`-${id}-`)).forEach((k) => delete 앱.초안[k]);
  } catch (e) { 오류쪽지(e); }
}

// ───────────────────────────── ⑥ 글·미리보기 (편마다: PC/모바일, 블록별 [고쳐줘], [이 글 승인])
function AI표시판(상태) { // 2026-10-08 실측: 네이버 'AI 활용 설정'은 글 단위가 아니라 사진·영상 블록마다 있음 → 이 표시는 확장이 사람에게 '직접 켜라'고 알리는 용. 글의 AI 도움은 글 끝 문구로
  const 켬 = 상태?.AI활용표시 === true;
  return `<section class="판" aria-labelledby="AI제목">
    <h2 id="AI제목">AI 사용 표시</h2>
    <label class="체크"><input type="checkbox" data-할일="AI표시" ${켬 ? 'checked' : ''}> AI로 만들거나 바꾼 사진·영상이 있음(임시저장 뒤 사진·영상마다 ‘AI 활용 설정’을 직접 켜기)</label>
    <p class="흐림작게" style="margin:0;line-height:1.6">AI로 만들거나 바꾼 <b>이미지·영상·오디오</b>가 있을 때 켜요. 직접 찍은 사진만 있으면 꺼 둬요(기본). 켜 두면 블로그 도우미가 ‘AI로 만든 사진·영상마다 직접 켜 주세요’라고 알려요(자동으로 켜 주지는 않아요). 글을 AI 도움으로 쓴 것은 <b>글 끝 문구</b>로 알려요.</p>
    ${상태?.AI이미지 && !켬 ? '<p class="멈춤상자" role="note" style="margin:0">이 글에 AI로 만든·바꾼 이미지가 있어요. ‘AI로 만들거나 바꾼 사진·영상이 있음’ 표시를 권해요.</p>' : ''}
    ${상태?.AI표기문구 ? '<p class="흐림작게" style="margin:0">✓ 글 끝 AI 사용 문구 있음</p>'
      : '<p class="멈춤상자" style="margin:0">글 끝에 AI 사용 문구가 없어요. [Claude에게 고쳐 달라기]로 넣어 달라고 하세요.</p>'}
  </section>`;
}
async function 편불러오기(id, 편요청) {
  const 여행 = await API('/api/여행');
  const t = (여행.여행 || []).find((x) => x.여행ID === id) || {};
  const 편들 = t.편들 || [];
  const 편 = 편들.some((x) => x.편ID === 편요청) ? 편요청 : (기억읽기(`편:${id}`) && 편들.some((x) => x.편ID === 기억읽기(`편:${id}`)) ? 기억읽기(`편:${id}`) : 편들[0]?.편ID);
  if (편) 기억쓰기(`편:${id}`, 편);
  return { t, 편들, 편, 상태: 편들.find((x) => x.편ID === 편) };
}
function 편탭(id, 화면, 편들, 편) {
  return `<nav class="탭들" aria-label="글(편) 고르기">${편들.map((x) => `<a class="탭" href="${화면주소(화면, id, x.편ID)}"${x.편ID === 편 ? ' aria-current="page"' : ''}>${h(x.편ID)}
    <span class="흐림작게">${x.승인 === '승인됨' ? '· 승인됨' : x.배치있음 ? '· 글 있음' : '· 글 없음'}</span></a>`).join('')}</nav>`;
}
const 글화면 = {
  여행필요: true, 관심: ['배치', '목록', '패키지', '구성안'], 본문틀: '넓게',
  async 불러오기(id, [편요청]) {
    const d = await 편불러오기(id, 편요청);
    d.배치 = d.상태?.배치있음 ? await JSON파일(id, `원고/배치_${d.편}.json`, `배치_${d.편}.json`) : null;
    return d;
  },
  그리기(d, id) {
    const { t, 편들, 편, 상태, 배치 } = d;
    if (!편들.length) {
      return `<div><h1 class="중간제목">${h(t.이름 || id)} · 글과 미리보기</h1></div>
      <section class="판 빈판"><h2>아직 글 목록이 없어요</h2>
        <p class="본문글">구성안에서 안을 고르고 [이 안으로 정하기]를 누르면 몇 편으로 나눌지가 정해지고, 편마다 Claude에게 글을 부탁할 수 있어요. Claude는 <b>여러분이 답한 내용만으로</b> 글을 써요.</p>
        <a class="단추 단추-주 단추-크게" href="${화면주소('구성안', id)}">구성안으로</a></section>`;
    }
    const 안쓴편 = 편들.filter((x) => !x.배치있음).map((x) => x.편ID);
    const 머리 = `<section class="머리줄">
      <div><h1 class="중간제목">${h(t.이름 || id)} · 글과 미리보기</h1><p class="설명">${h(상태?.제목 || 상태?.제목안 || '')}</p></div>
      ${편탭(id, '글', 편들, 편)}</section>`;
    if (!배치) {
      return `${머리}
      <section class="판 빈판"><h2>‘${h(편)}’ 글이 아직 없어요</h2>
        <p class="본문글">${h(상태?.제목안 ? `계획한 제목: ${상태.제목안}. ` : '')}Claude가 고른 사진·지도·여러분의 답과 꿀팁 노트만으로 글과 사진 배치를 만들어요. 모르는 것은 질문 카드로 물어봐요.</p>
        <div class="단추줄"><button type="button" class="단추 단추-주 단추-크게" data-할일="요청" data-종류="글쓰기" data-내용='${h(JSON.stringify({ 편ID: 편 }))}'>이 편 글쓰기</button>
          ${안쓴편.length > 1 ? `<button type="button" class="단추 단추-크게" data-할일="모두쓰기">아직 안 쓴 ${안쓴편.length}편 모두 부탁하기</button>` : ''}</div></section>`;
    }
    const 블록 = 배치.블록 || [];
    const 모바일 = 앱.미리보기모바일;
    const 승인됨 = 상태?.승인 === '승인됨';
    return `${머리}
    <div class="두칸">
      <section aria-label="미리보기" class="넓은칸">
        <div class="미리보기줄">
          <div class="탭들" role="group" aria-label="화면 크기">
            <button type="button" class="탭" aria-pressed="${!모바일}" data-할일="보기" data-값="pc">PC</button>
            <button type="button" class="탭" aria-pressed="${모바일}" data-할일="보기" data-값="모바일">모바일</button>
          </div>
          <span class="참고표시">모양 참고용 — 실제 네이버 화면과 조금 다를 수 있어요</span>
        </div>
        <div class="미리보기틀"><iframe id="미리보기" title="${h(편)} 글 미리보기" src="/api/미리보기?${질의({ 여행: id, 편, 보기: 모바일 ? '모바일' : 'pc' })}"></iframe></div>
        <details class="판 블록목록"${앱.보기['블록열림'] ? ' open' : ''} data-할일="블록목록">
          <summary>블록별로 고쳐 달라기 (${블록.length}개)</summary>
          <ol>${블록.map((b, i) => 블록줄(b, i + 1, id, 편)).join('')}</ol>
        </details>
        <label class="입력묶음">이 글에서 고칠 점
          <textarea class="입력" rows="2" data-초안="고칠점-${h(id)}-${h(편)}" placeholder="예: 첫 문단을 아이 시점으로 바꿔 주세요 / 콜라주 대신 슬라이드로"></textarea></label>
        <div class="오른쪽"><button type="button" class="단추" data-할일="고쳐줘" data-편="${h(편)}">Claude에게 고쳐 달라기</button></div>
      </section>
      <aside class="좁은칸" aria-label="승인">
        <section class="판">
          <h2>이 글 승인</h2>
          <p class="본문글">지금 상태: <span class="승인표 ${승인됨 ? '승인표-됨">✓ 승인됨' : '승인표-아님">아직 승인 안 함'}</span>${승인됨 && 상태.승인시각 ? ` <span class="흐림작게">(${h(짧은시각(상태.승인시각))})</span>` : ''}</p>
          ${상태?.승인후바뀜 ? '<p class="멈춤상자" role="alert" style="margin:0">승인한 뒤 글이 바뀌었어요. 다시 읽어 보고 승인해 주세요.</p>' : ''}
          ${상태?.승인무효 ? '<p class="멈춤상자" role="alert" style="margin:0">이 글의 ‘승인됨’ 표시는 화면에서 누른 승인이 아니라서(예전 승인이거나 다른 프로그램이 적음) 무효예요. 읽어 보고 다시 [이 글 승인]을 눌러 주세요.</p>' : ''}
          <p class="흐림작게" style="margin:0;line-height:1.6">미리보기를 끝까지 읽고 사진·장소·꿀팁이 맞으면 승인해 주세요. 자동 예약 발행(설정에서 켤 때만)은 <b>승인한 글만</b> 해요.</p>
          ${승인됨 && !상태?.승인후바뀜
            ? '<button type="button" class="단추" data-할일="승인" data-값="취소">승인 취소</button>'
            : '<button type="button" class="단추 단추-주 단추-크게" data-할일="승인" data-값="승인">이 글 승인</button>'}
          <a class="단추" href="${화면주소('발행', id, 편)}">발행 화면으로 →</a>
        </section>
        ${AI표시판(상태)}
      </aside>
    </div>`;
  },
  붙이기() {
    const 틀 = $('#미리보기');
    if (!틀) return;
    const 높이맞추기 = () => { try { 틀.style.height = Math.max(640, 틀.contentDocument.documentElement.scrollHeight + 4) + 'px'; } catch { /* 다른 출처면 그대로 */ } };
    틀.addEventListener('load', () => {
      try {
        const 문서 = 틀.contentDocument;
        미리보기보기맞추기();
        문서.getElementById('pc')?.addEventListener('click', () => { 앱.미리보기모바일 = false; 바깥보기단추(); setTimeout(높이맞추기, 50); });
        문서.getElementById('mo')?.addEventListener('click', () => { 앱.미리보기모바일 = true; 바깥보기단추(); setTimeout(높이맞추기, 50); });
        new 틀.contentWindow.ResizeObserver(높이맞추기).observe(문서.body);
      } catch { /* 무시 */ }
      높이맞추기();
    });
  },
};
function 블록줄(b, 번호, id, 편) {
  const 요약 = b.글 || b.설명 || (b.장소 || []).join(', ') || (b.목록 || []).join(', ') || (b.사진 ? `사진 ${b.사진.length}장${b.방식 ? ` · ${b.방식}` : ''}` : '') || b.이미지 || '';
  const 열림 = 앱.보기[`블록-${id}-${편}-${번호}`];
  return `<li><div class="블록줄"><span><span class="블록종류">${h(b.종류 || '?')}</span>${h(String(요약).slice(0, 60))}${String(요약).length > 60 ? '…' : ''}</span>
    <button type="button" class="단추 단추-작게" data-할일="블록고쳐" data-번호="${번호}" aria-expanded="${Boolean(열림)}">고쳐줘<span class="숨김글"> — ${번호}번 블록</span></button></div>
    <div class="블록입력"${열림 ? '' : ' hidden'}>
      <label class="입력묶음">${번호}번 블록(${h(b.종류)})을 어떻게 고칠까요?<textarea class="입력" rows="2" data-초안="블록-${h(id)}-${h(편)}-${번호}" placeholder="예: 이 사진 설명을 더 짧게 / 이 콜라주를 슬라이드로"></textarea></label>
      <div class="오른쪽"><button type="button" class="단추 단추-작게 단추-주" data-할일="블록보내기" data-번호="${번호}" data-편="${h(편)}">보내기</button></div>
    </div></li>`;
}
function 바깥보기단추() { $$('[data-할일="보기"]').forEach((b) => b.setAttribute('aria-pressed', String((b.dataset.값 === '모바일') === 앱.미리보기모바일))); }
function 미리보기보기맞추기() {
  const 틀 = $('#미리보기');
  try {
    const 문서 = 틀.contentDocument;
    const 단추 = 문서.getElementById(앱.미리보기모바일 ? 'mo' : 'pc');
    if (단추 && 단추.getAttribute('aria-pressed') !== 'true') 단추.click();
    else if (!단추) 문서.body.classList.toggle('모바일', 앱.미리보기모바일);
  } catch { /* 아직 안 열림 */ }
}

// ───────────────────────────── ⑦ 발행 (블로그 도우미 확장 — 공용 발행 API v2)
const 발행화면 = {
  여행필요: true, 관심: ['배치', '패키지', '발행작업'], 본문틀: '넓게',
  async 불러오기(id, [편요청]) {
    const d = await 편불러오기(id, 편요청);
    d.발행 = d.편 ? await API('/api/발행상태?' + 질의({ 여행: id, 편: d.편 })).catch((e) => ({ 오류: e.message })) : null;
    d.설정 = await API('/api/설정');
    return d;
  },
  그리기(d, id) {
    const { t, 편들, 편, 상태 } = d;
    const 설정 = d.설정?.설정 || {};
    const 발행 = d.발행 || {};
    const 머리 = `<section class="머리줄">
      <div><h1 class="중간제목">${h(t.이름 || id)} · 네이버 발행</h1>
        <p class="설명">블로그 도우미 확장이 내 브라우저(Chrome 또는 Edge)의 네이버 글쓰기 화면을 채우고 <b>'저장'(임시저장)까지</b> 해요. 로그인과 '발행'은 사람이 해요.</p></div>
      ${편들.length ? 편탭(id, '발행', 편들, 편) : ''}</section>`;
    const 설정판 = 발행설정판(설정, d.설정?.경고);
    if (!편들.length || !상태?.배치있음) {
      return `${머리}<div class="두칸"><section class="넓은칸"><section class="판 빈판"><h2>먼저 글이 있어야 해요</h2>
        <p class="본문글">글 화면에서 글을 만들고 미리보기로 확인한 뒤 오세요.</p><a class="단추 단추-주" href="${화면주소('글', id, 편)}">글 화면으로</a></section></section>
        <aside class="좁은칸">${연결판(발행)}${설정판}</aside></div>`;
    }
    return `${머리}
    <div class="두칸">
      <section class="넓은칸" aria-label="임시저장">
        <section class="판">
          <h2>‘${h(상태.제목 || 편)}’ 네이버 임시저장</h2>
          <ol class="안내목록" style="font-size:14px">
            <li>${h(브라우저이름[설정.브라우저] || 'Chrome')}에서 네이버에 <b>직접 로그인</b>해 두세요(로그인 상태 유지)</li>
            <li>그 브라우저에 블로그 도우미 확장을 설치하고 오른쪽 [확장 연결]의 연결 코드를 넣어 두세요(처음 한 번)</li>
            <li>[네이버 임시저장]을 누르면 글쓰기 화면이 열리고, 도우미가 제목·본문·사진·장소·태그를 채워 <b>'저장'까지만</b> 눌러요</li>
            <li>네이버에서 <b>모바일 화면을 확인</b>하고 <b>'발행'은 직접</b> 눌러요</li>
          </ol>
          ${패키지판(발행, 상태, 편)}
          ${작업판(발행, 상태, 설정, 편)}
        </section>
      </section>
      <aside class="좁은칸">${연결판(발행)}${설정판}</aside>
    </div>`;
  },
};
function 패키지판(발행, 상태, 편) {
  if (발행.오류) return `<p class="실패상자" role="alert">${h(발행.오류)}</p>`;
  const 패 = 발행.패키지 || {};
  const 만들기 = (글, 주 = false) => `<button type="button" class="단추${주 ? ' 단추-주' : ''}" data-할일="요청" data-종류="임시저장" data-내용='${h(JSON.stringify({ 편ID: 편, 패키지만: true }))}'>${글}</button>`;
  const 실패 = 발행.패키지실패;
  const 사본다시 = `<button type="button" class="단추 단추-주" data-할일="요청" data-종류="임시저장" data-내용='${h(JSON.stringify({ 편ID: 편, 패키지만: true, 사본다시: true }))}'>업로드 사본 다시 만들기</button>`;
  const 실패판 = 실패 ? `<div class="실패상자" role="alert"><span><b>발행 패키지를 만들다 멈췄어요</b>${실패.단계 ? `(${h(실패.단계)})` : ''}: ${h(실패.오류 || '')}</span>
      <span>${실패.사본문제
        ? '업로드 사본에 위치·기기 정보나 숨은 데이터(모션 포토의 동영상 꼬리·아이폰 HDR 보조 그림)가 남아 <b>올리지 않았어요</b>. [업로드 사본 다시 만들기]를 누르면 Claude가 사본을 새로 만들고 패키지를 다시 만들어요. 그래도 같으면 그 사진을 빼거나 다른 사진으로 바꿔 주세요.'
        : '원인을 고친 뒤 다시 만들어 달라고 하세요.'}</span>
      <span class="단추줄">${실패.사본문제 ? 사본다시 : 만들기('발행 패키지 다시 만들어 달라기', true)}
        ${실패.로그 ? `<button type="button" class="단추" data-할일="로그보기" data-값="${h(실패.로그)}">로그 보기</button>` : ''}</span></div>` : '';
  if (!패.있음) {
    if (실패) return `<h3>1단계 · 발행 패키지</h3>${실패판}`;
    return `<h3>1단계 · 발행 패키지</h3>
      <div class="멈춤상자">아직 <b>발행 패키지</b>(올릴 사진·영상 사본 — GPS·기기 정보를 지운 것)가 없어요. Claude가 <b>패키지만</b> 만들고 내부 표시가 남지 않았는지 점검해요. 다 되면 아래 <b>[네이버 임시저장]</b>을 직접 눌러요.</div>
      <div class="단추줄">${만들기('발행 패키지 만들어 달라기', true)}</div>`;
  }
  if (패.오류) return `<p class="실패상자" role="alert">${h(패.오류)}</p><div class="단추줄">${만들기('발행 패키지 다시 만들어 달라기')}</div>`;
  const 영상 = 패.영상 || [];
  const 영상자동 = 영상.filter((v) => v.자동).reduce((n, v) => n + (v.개수 || 1), 0);
  const 사진묶음 = (패.묶음 || []).filter((x) => x.종류 !== '영상').length;
  const 직접 = (패.건너뜀 || []).length;
  return `${실패판}<h3>1단계 · 발행 패키지 <span class="상태표 상태표-성공">준비됨</span></h3>
    <p class="본문글">사진 묶음 ${사진묶음}개 · 사진 ${패.사진수}장${영상자동 ? ` · 동영상 ${영상자동}개(도우미가 올려요)` : ''} · ${크기글(패.합계크기)}${직접 ? ` · 직접 올릴 것 ${직접}개(${영상.some((v) => !v.자동) ? '동영상 — 네이버 ‘동영상’ 버튼' : '사본 없음'})` : ''}
      <br><span class="흐림작게">AI 사진·영상 표시: ${패.AI활용표시 === true ? '있음(임시저장 뒤 사진·영상마다 직접 켜기)' : '없음'}(글 화면에서 바꿔요)</span></p>
    ${패.패키지승인 === '승인됨' ? '<p class="흐림작게" style="margin:0">✓ 패키지 승인됨 — 올라갈 사진·지도·영상 파일까지 승인에 묶였어요(파일이 바뀌면 무효).</p>'
      : 패.패키지승인 === '필요' ? `<div class="멈춤상자">글은 승인했지만 <b>이 패키지(올라갈 파일)</b>는 아직 승인하지 않았어요(예약 발행에 필요 — 임시저장만 할 거면 안 해도 돼요).
        <div class="단추줄" style="margin-top:8px"><button type="button" class="단추 단추-작게" data-할일="패키지승인">패키지 승인</button></div></div>` : ''}
    ${패.오래됨 ? `<div class="멈춤상자" role="alert">글을 고친 뒤 패키지를 다시 만들지 않았어요.</div><div class="단추줄">${만들기('발행 패키지 다시 만들어 달라기')}</div>` : ''}
    ${패.경고?.length ? `<details><summary>확인할 것 ${패.경고.length}개</summary><ul class="경고목록">${패.경고.map((w) => `<li>${h(w)}</li>`).join('')}</ul></details>` : ''}`;
}
function 발행이력(발행) { // 서버와 같은 판단: 마지막으로 저장한 작업, 그 뒤에 실패하고 아직 정리 안 한 작업
  const 작업들 = 발행?.작업 || [];
  let 저장 = null, 실패 = null;
  작업들.forEach((j) => {
    if (['임시저장완료', '예약발행완료'].includes(j.상태)) { 저장 = j; 실패 = null; } else if (j.상태 === '실패') 실패 = j;
  });
  return { 저장, 실패 };
}
function 작업판(발행, 상태, 설정, 편) {
  const 패 = 발행.패키지 || {};
  const 작업 = 발행.최근작업;
  const 진행중 = 작업 && ['대기', '채우는중'].includes(작업.상태);
  const 예약가능 = 설정.자동예약발행 && 상태?.승인 === '승인됨' && !상태?.승인후바뀜;
  const 준비됨 = 패.있음 && !패.오래됨 && !패.오류;
  const 저장됨 = !!발행이력(발행).저장;
  const 다음 = 발행.다음가능 && new Date(발행.다음가능) > new Date() ? 짧은시각(발행.다음가능) : '';
  const 간격 = h(Number(발행.편사이간격분 || 설정.편사이간격분) || 10);
  let html = '';
  if (진행중) {
    html += `<h3>2단계 · 네이버 임시저장</h3>
      <button type="button" class="단추 단추-주 단추-아주크게" disabled aria-describedby="진행안내">네이버 임시저장 — 진행 중</button>
      <p id="진행안내" class="흐림작게" style="margin:0">블로그 도우미가 이 글을 채우는 동안에는 다시 누를 수 없어요. 아래 진행 상황을 보세요.</p>`;
  } else {
    html += `<h3>2단계 · 네이버 임시저장</h3>
      ${예약가능 ? `<fieldset class="고르기"><legend>무엇을 할까요?</legend>
        <label class="체크"><input type="radio" name="발행모드" value="임시저장" data-초안="발행모드-${h(편)}" checked> 임시저장까지(기본)</label>
        <label class="체크"><input type="radio" name="발행모드" value="예약발행" data-초안="발행모드예약-${h(편)}"> 예약 발행(승인한 글)</label>
        <label class="입력묶음">예약 시각(10분 단위, 지금부터 15분 뒤 이후)<input class="입력" type="datetime-local" step="600" data-초안="예약시각-${h(편)}"></label>
        <p class="흐림작게" style="margin:0">${h(발행.예약경고 || '')}</p></fieldset>`
        : (설정.자동예약발행 ? '<p class="흐림작게" style="margin:0">자동 예약 발행이 켜져 있지만, 이 글은 아직 승인하지 않아 임시저장만 할 수 있어요.</p>' : '')}
      <button type="button" class="단추 ${저장됨 ? '' : '단추-주 '}단추-아주크게" data-할일="임시저장시작" data-편="${h(편)}" ${준비됨 ? '' : 'disabled aria-describedby="시작안내"'}>${저장됨 ? '다시 임시저장(새 글로 저장됨)' : '네이버 임시저장'}</button>
      ${준비됨 ? '' : '<p id="시작안내" class="흐림작게" style="margin:0">1단계 발행 패키지가 준비되면 누를 수 있어요.</p>'}
      ${저장됨 ? '<p class="흐림작게" style="margin:0">이미 임시저장한 글이에요. 다시 누르면 네이버에 <b>새 글로 하나 더</b> 저장돼요(누르면 한 번 더 물어봐요).</p>' : ''}
      ${다음 ? `<p class="흐림작게" style="margin:0">글 사이 간격 ${간격}분: 다음 글은 <b>${h(다음)} 이후</b>에 도우미가 채우기 시작해요.</p>` : ''}
      ${설정.블로그ID ? '' : '<p class="흐림작게" style="margin:0">설정에 블로그 아이디를 적으면 글쓰기 화면을 자동으로 열어 줘요. 없으면 직접 열어 두세요.</p>'}`;
  }
  if (작업) {
    const 단계 = 작업.단계 || [];
    html += `<h3>진행 상황 <span class="상태표 ${{ 임시저장완료: '상태표-성공', 예약발행완료: '상태표-성공', 실패: '상태표-실패', 대기: '상태표-진행', 채우는중: '상태표-진행' }[작업.상태] || '상태표-기타'}">${h(발행상태글[작업.상태] || 작업.상태)}</span></h3>
      <p class="흐림작게" style="margin:0">작업 ${h(작업.작업ID)} · ${h(작업.모드)}${작업.예약시각 ? ` · 예약 ${h(짧은시각(작업.예약시각))}` : ''}${정수(작업.재시도횟수) ? ` · 다시 시도 ${h(정수(작업.재시도횟수))}번` : ''}</p>
      ${작업.상태 === '대기' ? `<div class="멈춤상자">${다음
        ? `글 사이 간격(${간격}분)을 지키는 중이에요. <b>다음 가능 시각 ${h(다음)}</b> — 그때 블로그 도우미가 채우기 시작해요. 글쓰기 화면은 열어 둔 채 기다려 주세요.`
        : `블로그 도우미가 작업을 받기를 기다리는 중이에요. ${h(브라우저이름[설정.브라우저] || 'Chrome')}에 네이버 글쓰기 화면이 열려 있고, 확장이 연결되어 있는지 확인하세요.`}
        <div class="단추줄" style="margin-top:8px"><button type="button" class="단추 단추-작게" data-할일="글쓰기열기">글쓰기 화면 다시 열기</button>
        <button type="button" class="단추 단추-작게" data-할일="발행취소" data-값="${h(작업.작업ID)}">이 작업 취소</button></div></div>` : ''}
      ${단계목록(단계.map((s) => {
        const 표 = { 완료: ['완료', '단계-완료'], 주의: ['완료(확인할 것)', '단계-진행'], 사람: ['사람이 함', '단계-완료'], 건너뜀: ['건너뜀', '단계-대기'], 진행: [s.신호시각 ? `처리 중 · ${짧은시각(s.신호시각)} 신호` : '진행 중', '단계-진행'], 실패: ['멈춤', '단계-실패'] }[s.상태] || [s.상태, '단계-대기'];
        const 블록번호 = /^블록 (\d+)$/.exec(s.이름 || '');
        const 이름 = 블록번호 && (패.블록종류 || [])[블록번호[1] - 1] === '영상' ? `${s.이름} · 동영상` : s.이름;
        return { 끝남: ['완료', '사람', '건너뜀'].includes(s.상태), html: `<li class="단계줄"><span>${h(이름)}</span><b class="${표[1]}">${h(표[0])}</b>${s.메시지 || (s.주의 || []).length ? `<span class="단계메시지">${h([s.메시지, ...(s.주의 || [])].filter(Boolean).join(' · '))}</span>` : ''}</li>` };
      }), '아직 보고가 없어요.')}`;
    const 주의 = 단계.flatMap((s) => (s.주의 || []).map((w) => `${s.이름}: ${w}`));
    if (작업.상태 === '임시저장완료') {
      html += `<div class="완료상자" role="status"><b>임시저장 끝!</b> 네이버 블로그 → 글쓰기 → <b>'저장' 옆 숫자(임시저장 글)</b>에서 이 글을 열고, 오른쪽 아래 기기 아이콘으로 <b>모바일 화면을 확인</b>한 뒤 <b>'발행'은 직접</b> 눌러 주세요.${주의.length ? `<br><b>사람이 확인할 것:</b> ${h(주의.join(' / '))}` : ''}</div>`;
    } else if (작업.상태 === '예약발행완료') {
      html += `<div class="완료상자" role="status"><b>예약 발행을 걸었어요</b>(${h(짧은시각(작업.예약시각))}). 네이버 '예약 글'에서 확인하고, 바꾸려면 네이버에서 직접 고쳐 주세요.</div>`;
    } else if (작업.상태 === '실패') {
      const 실패 = 작업.실패 || {};
      html += `<div class="실패상자" role="alert"><span><b>${h(실패.단계 || '')}</b> 단계에서 멈췄어요: ${h(실패.메시지 || '')}</span>
        <span>${h(실패도움[실패.코드] || '네이버 화면을 확인한 뒤 [다시 시도]를 눌러 주세요.')}</span>
        <span class="단추줄"><button type="button" class="단추 단추-주" data-할일="발행다시" data-값="${h(작업.작업ID)}">다시 시도(${h(실패.단계 || '')}부터)</button>
        <button type="button" class="단추" data-할일="발행다시" data-값="${h(작업.작업ID)}" data-편="처음">처음부터</button>
        <button type="button" class="단추" data-할일="수리복사" data-값="${h(작업.작업ID)}">수리 프롬프트 복사</button>
        <a class="단추" href="${화면주소('이력', 앱.여행ID)}">작업 이력·로그</a></span></div>`;
    } else if (작업.상태 === '취소') {
      html += '<p class="흐림작게">이 작업은 취소했어요. 다시 하려면 [네이버 임시저장]을 누르세요.</p>';
    }
  }
  html += `<details><summary>도우미가 안 될 때</summary><p class="본문글">[글쓰기 화면 열기] 후 확장 패널의 [묶음 N 넣기]로 사진만 넣고 글은 직접 넣거나, Claude에게 부탁하세요.</p>
    <div class="단추줄"><button type="button" class="단추 단추-작게" data-할일="글쓰기열기">글쓰기 화면 열기</button>
    <button type="button" class="단추 단추-작게" data-할일="요청" data-종류="자유요청" data-내용='${h(JSON.stringify({ 글: `'${편}' 글 임시저장을 도와줘(블로그 도우미가 안 됨)` }))}'>Claude에게 부탁하기</button></div></details>`;
  return html;
}
function 연결판(발행) {
  const 연결 = 발행?.확장?.연결 || [];
  return `<section class="판" aria-labelledby="확장제목">
    <h2 id="확장제목">블로그 도우미 확장</h2>
    ${연결.length ? `<ul class="알림목록">${연결.map((c) => `<li>${h(c.이름 || '확장')} · 마지막 접속 ${h(짧은시각(c.마지막접속) || '없음')}
        <button type="button" class="단추 단추-작게" data-할일="연결끊기" data-값="${h(c.확장ID)}">연결 끊기<span class="숨김글"> — ${h(c.이름 || '')}</span></button></li>`).join('')}</ul>`
      : '<p class="본문글">아직 연결된 확장이 없어요.</p>'}
    <button type="button" class="단추 단추-주" data-할일="확장연결">확장 연결(연결 코드 받기)</button>
    <p class="흐림작게" style="margin:0">한 번 연결하면 단체 블로그의 발행서버에서도 그대로 쓸 수 있어요.</p>
  </section>`;
}
function 발행설정판(설정, 경고) {
  const 테마 = document.documentElement.dataset.theme || 'system';
  return `<section class="판" aria-labelledby="설정제목">
    <h2 id="설정제목">설정</h2>
    <fieldset class="고르기"><legend>글쓰기 화면을 열 브라우저(네이버에 로그인하고 확장을 설치한 곳)</legend>
      ${Object.entries(브라우저이름).map(([v, 이름]) => `<label class="체크"><input type="radio" name="브라우저" value="${v}" data-할일="브라우저" ${설정.브라우저 === v ? 'checked' : ''}> ${이름}</label>`).join('')}
    </fieldset>
    <label class="입력묶음">블로그 아이디(blog.naver.com/ 뒤의 영문)
      <span class="단추줄"><input class="입력" style="flex:1 1 160px;width:auto" type="text" inputmode="latin" autocomplete="off" data-초안="블로그ID" value="${h(설정.블로그ID || '')}" placeholder="예: myblog">
      <button type="button" class="단추 단추-작게" data-할일="블로그ID저장">저장</button></span></label>
    <p class="본문글" style="margin:0">글 사이 간격: <b>${h(String(설정.편사이간격분 ?? 10))}분</b>
      <span class="흐림작게" style="display:block;line-height:1.6">한 글을 끝낸 뒤 이만큼 지나야 도우미가 다음 글을 채워요(단체 블로그와 같은 설정 ‘편사이간격분’, 설정.json).</span></p>
    <fieldset class="고르기"><legend>자동 예약 발행(기본 꺼짐)</legend>
      <label class="체크"><input type="checkbox" data-할일="예약설정" ${설정.자동예약발행 ? 'checked' : ''}> 승인한 글을 확장이 예약 발행해도 돼요</label>
      <p class="흐림작게" style="margin:0;line-height:1.6">⚠ ${h(경고 || '')}</p>
    </fieldset>
    <fieldset class="고르기"><legend>화면 밝기</legend>
      ${[['system', '컴퓨터 설정대로'], ['light', '밝게'], ['dark', '어둡게']].map(([v, 이름]) => `<label class="체크"><input type="radio" name="테마" value="${v}" data-할일="테마" ${테마 === v ? 'checked' : ''}> ${이름}</label>`).join('')}
    </fieldset>
  </section>`;
}
async function 확장연결창() {
  let r;
  try { r = await API('/api/확장연결', { 이름: '여행 스튜디오' }); } catch (e) { 오류쪽지(e); return; }
  const 끝 = Date.now() + (r.유효초 || 300) * 1000;
  const d = 창열기(`<h2>블로그 도우미 연결</h2>
    <p class="본문글">아래 6자리 코드를 확장에 넣어 주세요. <b>${Math.round((r.유효초 || 300) / 60)}분 안에, 한 번만</b> 쓸 수 있어요.</p>
    <div class="연결코드" aria-label="연결 코드 ${h(String(r.코드).split('').join(' '))}">${h(r.코드)}</div>
    <p id="코드남은시간" class="흐림작게" role="timer" style="margin:6px 0 0;text-align:center"></p>
    <ol><li>네이버에 로그인해 둔 브라우저(Chrome 또는 Edge) 오른쪽 위 <b>퍼즐 조각(확장)</b> → <b>블로그 도우미</b></li>
      <li>연결 코드 칸에 위 숫자를 넣고 [연결]</li><li>‘연결됨’이 보이면 이 창을 닫으세요</li></ol>
    <div class="오른쪽"><button type="button" class="단추" data-할일="복사" data-값="${h(r.코드)}">코드 복사</button><button type="button" class="단추 단추-주" data-할일="창닫기" autofocus>닫기</button></div>`);
  const 시계 = setInterval(() => {
    const 남음 = Math.max(0, Math.round((끝 - Date.now()) / 1000));
    const el = $('#코드남은시간');
    if (!el || !d.open) { clearInterval(시계); 화면그리기({ 유지: true }); return; }
    el.textContent = 남음 ? `남은 시간 ${Math.floor(남음 / 60)}분 ${남음 % 60}초` : '시간이 지났어요. 다시 [확장 연결]을 눌러 주세요.';
  }, 1000);
}

// ───────────────────────────── ⑧ 영상(선택)
const 영상화면 = {
  여행필요: true, 관심: ['영상'], 본문틀: '좁게',
  async 불러오기(id) { const 여행 = await API('/api/여행'); return { t: (여행.여행 || []).find((x) => x.여행ID === id) || {} }; },
  그리기({ t }, id) {
    const 결과 = t.영상결과 || [];
    return `
    <div><h1 class="중간제목">돌아보기 영상 <span class="흐림" style="font-size:18px">(선택)</span></h1>
      <p class="설명">고른 사진·영상으로 여행 돌아보기 영상을 만들어요. 대표 사진은 길게, 나머지는 짧게, 날짜·장소 제목과 지도 장면을 넣어요. 시간이 꽤 걸려요(수십 분).</p></div>
    <section class="판" aria-labelledby="영상설정">
      <h2 id="영상설정">만들기 설정</h2>
      <div class="칸둘">
        <label class="입력묶음">목표 길이(분:초)<input class="입력" type="text" inputmode="numeric" data-초안="영상길이-${h(id)}" value="8:10"></label>
        <label class="입력묶음">음악 파일 이름(선택)<input class="입력" type="text" data-초안="영상음악-${h(id)}" placeholder="예: bgm.mp3"></label>
      </div>
      <p class="흐림작게" style="margin:0">음악 파일(mp3·m4a·aac·wav·ogg·flac)은 <b>여행/${h(id)}/음악/</b> 폴더에 넣고 <b>파일 이름만</b> 적어 주세요(다른 폴더의 파일은 쓰지 않아요). YouTube 오디오 보관함처럼 써도 되는 음악만 쓰세요.</p>
      <div class="단추줄"><button type="button" class="단추 단추-작게" data-할일="음악폴더">음악 폴더 열기</button></div>
      <div class="오른쪽"><button type="button" class="단추 단추-주 단추-크게" data-할일="영상만들기">영상 만들어 달라기</button></div>
    </section>
    <section class="판" aria-labelledby="영상결과제목">
      <h2 id="영상결과제목">결과</h2>
      ${결과.length ? `<div class="영상결과">${결과.map((경로) => `<figure><video controls preload="metadata" src="${파일주소(id, 경로)}"></video>
        <figcaption class="흐림작게">${h(경로)}</figcaption></figure>`).join('')}</div>
        ${t.영상챕터 ? `<p class="본문글" style="margin:0">유튜브 챕터 문구: <a href="${파일주소(id, t.영상챕터)}" target="_blank" rel="noopener">챕터.txt 열기</a> (설명란에 붙여 넣기)</p>` : ''}
        <p class="흐림작게" style="margin:0">결과는 여행/${h(id)}/작업/영상/ 에 있어요. 유튜브 업로드는 YouTube Studio에서 직접 해 주세요.</p>`
      : '<p class="본문글">아직 만든 영상이 없어요.</p>'}
    </section>`;
  },
};

// ───────────────────────────── ⑨ 작업 이력 (규약 2.6: 성공/실패/재시도 완료/재시도 불가, [다시 시도]·[처음부터]·[로그 보기])
const 이력화면 = {
  여행필요: true, 관심: ['이력'], 본문틀: '좁게',
  async 불러오기(id) { return API('/api/이력?' + 질의({ 여행: id })); },
  그리기(d, id) {
    const 거르기 = (앱.보기['이력거르기'] ||= '전체');
    const 표 = { 전체: () => true, 멈춤: (x) => ['실패', '멈춤', '재시도 불가'].includes(x.표시상태), 진행중: (x) => x.표시상태 === '진행중', 성공: (x) => ['성공', '재시도 완료'].includes(x.표시상태) };
    const 목록 = (d.이력 || []).filter(표[거르기] || 표.전체);
    const 요약 = d.요약 || {};
    return `
    <section class="머리줄"><div><h1 class="중간제목">작업 이력</h1>
      <p class="설명">Claude와 블로그 도우미가 한 일을 단계마다 남겨요. 멈춘 작업은 <b>실패한 단계부터</b> 다시 할 수 있어요(앞 단계 결과를 다시 써서 시간·사용량 절약).</p></div>
      <div class="단추줄"><button type="button" class="단추" data-할일="로그보기" data-값="">오늘 로그 보기</button></div></section>
    <div class="탭들" role="group" aria-label="골라 보기">${Object.keys(표).map((k) => `<button type="button" class="탭" aria-pressed="${거르기 === k}" data-할일="이력거르기" data-값="${k}">${k}${k === '전체' ? ` ${(d.이력 || []).length}` : ''}</button>`).join('')}</div>
    <p class="흐림작게" style="margin:0">${Object.entries(요약).map(([k, v]) => `${h(k)} ${v}`).join(' · ') || '아직 기록된 작업이 없어요.'}</p>
    ${목록.length ? `<ul class="이력목록">${목록.map((x) => 이력카드(x)).join('')}</ul>`
      : '<section class="판 빈판"><p class="본문글">이 조건에 맞는 작업이 없어요.</p></section>'}`;
  },
};
function 이력카드(x) {
  const 취소 = x.출처 === '발행' && x.발행상태 === '취소'; // 사람이 취소한 발행 작업 — 고칠 것이 아님
  const 표시 = 취소 ? '취소됨' : x.표시상태;
  const 표 = { 성공: '상태표-성공', '재시도 완료': '상태표-성공', 진행중: '상태표-진행', 실패: '상태표-실패', 멈춤: '상태표-실패', '재시도 불가': '상태표-실패' }[표시] || '상태표-기타';
  const 멈춤 = !취소 && ['실패', '멈춤', '재시도 불가'].includes(표시);
  const 불가 = String(x.재시도 || '').startsWith('불가');
  const 발행 = x.출처 === '발행';
  const 실패단계 = (x.단계 || []).find((s) => s.상태 === '실패');
  const 로그칸 = 실패단계?.로그 || '';
  const 재시도단추 = 발행
    ? `<button type="button" class="단추 단추-주" data-할일="발행다시" data-값="${h(x.작업ID)}">다시 시도${실패단계 ? `(${h(실패단계.이름)}부터)` : ''}</button>
       <button type="button" class="단추" data-할일="발행다시" data-값="${h(x.작업ID)}" data-편="처음">처음부터</button>`
    : `<button type="button" class="단추 단추-주" data-할일="요청" data-종류="재시도" data-내용='${h(JSON.stringify({ 작업ID: x.작업ID, 처음부터: false }))}' ${불가 ? 'disabled' : ''}>다시 시도${실패단계 ? `(${h(실패단계.이름)}부터)` : ''}</button>
       <button type="button" class="단추" data-할일="처음부터" data-값="${h(x.작업ID)}">처음부터</button>`;
  return `<li class="판 이력카드">
    <div class="카드머리"><h2>${h(x.종류 || '')}${x.편ID ? ` · ${h(x.편ID)}` : ''}</h2><span class="상태표 ${표}">${h(표시)}${x.재시도요청중 ? ' · 다시 시도 요청함' : ''}</span></div>
    <p class="흐림작게" style="margin:0">${h(x.작업ID)} · 시작 ${h(짧은시각(x.시작))}${x.끝 ? ` · 끝 ${h(짧은시각(x.끝))}` : ''}${정수(x.재시도횟수) ? ` · 다시 시도 ${h(정수(x.재시도횟수))}번` : ''}${불가 ? ` · ${h(x.재시도)}` : ''}</p>
    ${(x.단계 || []).length ? 단계목록(x.단계.map((s) => {
      const t = { 완료: ['완료', '단계-완료'], 진행중: ['진행 중', '단계-진행'], 실패: ['실패', '단계-실패'], 건너뜀: ['건너뜀', '단계-대기'] }[s.상태] || [s.상태 || '', '단계-대기'];
      const 덧 = [s.산출물 ? `결과: ${s.산출물}` : '', s.오류 ? `오류: ${s.오류}` : '', s.메시지 && s.상태 !== '실패' ? s.메시지 : ''].filter(Boolean).join(' · ');
      return { 끝남: ['완료', '건너뜀'].includes(s.상태), html: `<li class="단계줄"><span>${h(s.이름)}</span><b class="${t[1]}">${h(t[0])}</b>${덧 ? `<span class="단계메시지">${h(덧)}${s.로그 ? ` <button type="button" class="단추 단추-작게" data-할일="로그보기" data-값="${h(s.로그)}">로그 보기<span class="숨김글"> — ${h(s.이름)}</span></button>` : ''}</span>` : ''}</li>` };
    })) : ''}
    ${멈춤 ? `<div class="수리카드"><b>고치는 방법</b><span>${불가 ? '이어서 할 수 없는 작업이에요(이유를 확인하세요). [처음부터]로 다시 하거나' : '[다시 시도]를 누르거나, 원인을 모르면'} 아래 수리 프롬프트를 Claude에게 보내세요.</span>
      <code>${h(수리문구(로그칸, x.작업ID))}</code>
      <span class="단추줄">${재시도단추}
      <button type="button" class="단추" data-할일="로그보기" data-값="${h(로그칸 || 날짜로그(x.시작))}">로그 보기</button>
      <button type="button" class="단추" data-할일="수리복사" data-값="${h(x.작업ID)}" data-편="${h(로그칸)}">수리 프롬프트 복사</button></span></div>` : ''}
    ${취소 ? `<div class="단추줄"><span class="흐림작게">사람이 취소한 발행 작업이에요. 다시 하려면</span>${재시도단추}</div>` : ''}
    ${!멈춤 && 발행 && 표시 === '진행중' ? `<div class="단추줄"><button type="button" class="단추 단추-작게" data-할일="발행취소" data-값="${h(x.작업ID)}">이 발행 작업 취소</button></div>` : ''}
  </li>`;
}
function 단계목록(줄들, 빈글 = '') { // 단계가 많으면 끝난 것은 접어 두고, 끝나지 않은(진행·실패) 단계와 마지막 단계는 늘 보이게
  if (!줄들.length) return 빈글 ? `<p class="흐림작게" style="margin:0">${h(빈글)}</p>` : '';
  if (줄들.length <= 6) return `<ul class="단계목록">${줄들.map((x) => x.html).join('')}</ul>`;
  const 보일것 = 줄들.filter((x, i) => !x.끝남 || i >= 줄들.length - 2);
  const 끝난수 = 줄들.filter((x) => x.끝남).length;
  return `<p class="흐림작게" style="margin:0">단계 ${줄들.length}개 중 ${끝난수}개 끝남</p>
    <ul class="단계목록">${보일것.map((x) => x.html).join('')}</ul>
    <details><summary>모든 단계 보기(${줄들.length}개)</summary><ul class="단계목록">${줄들.map((x) => x.html).join('')}</ul></details>`;
}
function 날짜로그(시각) { const m = /^(\d{4}-\d{2}-\d{2})/.exec(시각 || ''); return m ? `로그/${m[1]}.log` : ''; }
async function 로그창(로그칸) {
  const m = /로그\/(\d{4}-\d{2}-\d{2})\.log(?:#L(\d+))?/.exec(로그칸 || '');
  const 날짜 = m ? m[1] : 오늘(), 줄 = m && m[2] ? m[2] : '';
  let r;
  try { r = await API('/api/로그?' + 질의({ 날짜, 줄 })); } catch (e) { 오류쪽지(e); return; }
  창열기(`<h2>로그 보기 — ${h(r.파일)}</h2>
    <div class="단추줄" style="margin-bottom:10px">
      <label class="입력묶음" style="flex-direction:row;align-items:center;gap:8px">날짜
        <select class="입력" style="width:auto" data-할일="로그날짜">${(r.날짜들.length ? r.날짜들 : [날짜]).map((x) => `<option ${x === r.날짜 ? 'selected' : ''}>${h(x)}</option>`).join('')}</select></label>
      ${r.마지막오류줄 ? `<button type="button" class="단추 단추-작게" data-할일="로그보기" data-값="${h(`로그/${r.날짜}.log#L${r.마지막오류줄}`)}">마지막 오류로(${r.마지막오류줄}줄)</button>` : ''}
      <button type="button" class="단추 단추-작게" data-할일="수리복사" data-값="" data-편="${h(r.파일)}">수리 프롬프트 복사</button>
    </div>
    ${r.있음 ? `<p class="흐림작게" style="margin:0 0 6px">전체 ${r.전체줄수}줄 중 ${r.줄[0]?.번호 || 0}~${r.줄[r.줄.length - 1]?.번호 || 0}줄 · '오류' 표시 줄은 문제가 난 곳</p>
      <div class="로그상자" tabindex="0" aria-label="로그 내용">${r.줄.map((l) => `<div class="로그줄${l.오류 ? ' 로그줄-오류' : ''}${l.번호 === r.강조줄 ? ' 로그줄-강조' : ''}"${l.번호 === r.강조줄 ? ' id="강조줄"' : ''}><span class="번호">${l.번호}</span><span>${l.오류 ? '<b>[오류]</b> ' : ''}${h(l.글.replace('[오류] ', ''))}</span></div>`).join('')}</div>`
      : '<p class="본문글">이 날짜의 로그가 없어요.</p>'}
    <div class="오른쪽" style="margin-top:12px"><button type="button" class="단추 단추-주" data-할일="창닫기" autofocus>닫기</button></div>`, { 넓게: true });
  $('#강조줄')?.scrollIntoView({ block: 'center' });
}

const 화면들 = { '': 시작화면, 타임라인: 타임라인화면, 질문: 질문화면, 구성안: 구성안화면, 지도: 지도화면, 글: 글화면, 발행: 발행화면, 영상: 영상화면, 이력: 이력화면 };

// ───────────────────────────── 단추 누르기(한곳에서 처리)
const 할일들 = {
  async 요청(b) { const 내용 = b.dataset.내용 ? JSON.parse(b.dataset.내용) : {}; b.disabled = true; try { await 요청보내기(b.dataset.종류, 내용); } catch (e) { b.disabled = false; 오류쪽지(e); } },
  결정: 결정바꾸기,
  추천대로,
  새여행: 새여행창,
  기간창,
  클로드연결,
  창닫기,
  다시: () => 화면그리기(),
  일차(b) { const v = b.dataset.값; 앱.보기[앱.여행ID].일차 = v === '' ? null : +v; 다시그리기(); },
  거르기(b) { 앱.보기[앱.여행ID].거르기 = b.dataset.값; 다시그리기(); },
  선택: 선택바꾸기,
  답보내기,
  async 자유요청() {
    const 글 = (앱.초안['자유요청'] || '').trim();
    if (!글) { 쪽지('부탁할 내용을 적어 주세요.', { 종류: '오류' }); return; }
    try { await 요청보내기('자유요청', { 글 }); 앱.초안['자유요청'] = ''; const t = $('[data-초안="자유요청"]'); if (t) t.value = ''; } catch (e) { 오류쪽지(e); }
  },
  안고르기(b) { const n = Number(b.dataset.번호); if (!Number.isInteger(n)) return; (앱.보기['안-' + 앱.여행ID] ||= {}).선택 = n; 다시그리기(); },
  async 구성안다시() {
    const 고칠점 = (앱.초안[`구성안고칠점-${앱.여행ID}`] || '').trim();
    try { await 요청보내기('구성안', 고칠점 ? { 글: 고칠점 } : {}); } catch (e) { 오류쪽지(e); }
  },
  async 안정하기() {
    const 번호 = 정수((앱.보기['안-' + 앱.여행ID] || {}).선택) ?? 정수(앱.데이터?.여행?.선택한구성안);
    if (번호 === null) { 쪽지('먼저 안 하나를 골라 주세요.', { 종류: '오류' }); return; }
    const 쓴글 = (앱.데이터?.여행?.편들 || []).filter((x) => x.배치있음).length;
    if (쓴글 && !await 확인창(`이미 쓴 글 ${h(쓴글)}편은 그대로 두고, 편 목록만 ${h(번호)}번 안으로 바꿀까요?`, '바꾸기', '그만두기')) return;
    try {
      const r = await API('/api/구성안선택', { 여행ID: 앱.여행ID, 번호 });
      쪽지(`${번호}번 안으로 정했어요. 글 ${r.편목록.length}편 — 편마다 [글쓰기]를 누르세요.`);
      location.hash = 화면주소('글', 앱.여행ID, r.편목록[0]?.편ID);
    } catch (e) { 오류쪽지(e); }
  },
  async 모두쓰기() {
    const 안쓴편 = (앱.데이터?.편들 || []).filter((x) => !x.배치있음).map((x) => x.편ID);
    if (!await 확인창(`아직 안 쓴 ${안쓴편.length}편(${h(안쓴편.join(', '))})을 차례로 부탁할까요? Claude는 한 편씩 써요.`, '부탁하기', '그만두기')) return;
    try { for (const 편ID of 안쓴편) await API('/api/요청', { 종류: '글쓰기', 여행ID: 앱.여행ID, 내용: { 편ID } }); 쪽지(`${안쓴편.length}편을 부탁했어요.`); await 살피기(); } catch (e) { 오류쪽지(e); }
  },
  장소맞음(b) { const k = `장소맞음-${앱.여행ID}-${b.dataset.id}`; 앱.초안[k] = !앱.초안[k]; 다시그리기(); },
  장소보내기,
  보기(b) { 앱.미리보기모바일 = b.dataset.값 === '모바일'; 바깥보기단추(); 미리보기보기맞추기(); },
  블록목록() { setTimeout(() => { 앱.보기['블록열림'] = $('.블록목록')?.open; }, 0); },
  블록고쳐(b) {
    const 칸 = b.closest('li').querySelector('.블록입력');
    칸.hidden = !칸.hidden; b.setAttribute('aria-expanded', String(!칸.hidden));
    앱.보기[`블록-${앱.여행ID}-${앱.데이터?.편}-${b.dataset.번호}`] = !칸.hidden;
    if (!칸.hidden) 칸.querySelector('textarea').focus();
  },
  async 블록보내기(b) {
    const 편ID = b.dataset.편, 블록번호 = +b.dataset.번호;
    const 키 = `블록-${앱.여행ID}-${편ID}-${블록번호}`;
    const 글 = (앱.초안[키] || '').trim();
    if (!글) { 쪽지('어떻게 고칠지 적어 주세요.', { 종류: '오류' }); return; }
    try { await 요청보내기('수정요청', { 편ID, 블록번호, 글 }); 앱.초안[키] = ''; 앱.보기[키] = false; 다시그리기(); } catch (e) { 오류쪽지(e); }
  },
  async 고쳐줘(b) {
    const 편ID = b.dataset.편, 키 = `고칠점-${앱.여행ID}-${편ID}`;
    const 글 = (앱.초안[키] || '').trim();
    if (!글) { 쪽지('고칠 점을 적어 주세요.', { 종류: '오류' }); return; }
    try { await 요청보내기('수정요청', { 편ID, 글 }); 앱.초안[키] = ''; const t = $(`[data-초안="${CSS.escape(키)}"]`); if (t) t.value = ''; } catch (e) { 오류쪽지(e); }
  },
  async 패키지승인() {
    쪽지('컴퓨터 화면에 뜬 승인 확인 창에서 [이 글 승인]을 마우스로 눌러 주세요.', { 시간: 20000 });
    try { const r = await API('/api/패키지승인', { 여행ID: 앱.여행ID, 편ID: 앱.데이터.편 }); 쪽지(`패키지를 승인했어요(파일 ${h(r.승인?.파일수 ?? '')}개).`); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async AI표시(b) {
    const 켬 = b.checked;
    try { await API('/api/AI활용표시', { 여행ID: 앱.여행ID, 편ID: 앱.데이터.편, 켬 }); 쪽지(켬 ? 'AI 사진·영상 있음으로 표시했어요 — 임시저장 뒤 사진·영상마다 ‘AI 활용 설정’을 직접 켜 주세요.' : 'AI 사진·영상 표시를 껐어요.'); 화면그리기({ 유지: true }); }
    catch (e) { b.checked = !켬; 오류쪽지(e); }
  },
  async 알림지우기(b) {
    const id = b.dataset.값;
    try { await API('/api/알림', id ? { 동작: '지우기', id } : { 동작: '모두지우기' }); await 살피기(); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async 승인(b) {
    const 승인 = b.dataset.값 === '승인';
    if (승인) 쪽지('컴퓨터 화면에 뜬 ‘여행 스튜디오 — 이 글 승인’ 창에서 [이 글 승인]을 마우스로 눌러 주세요(브라우저 뒤에 있을 수 있어요).', { 시간: 20000 });
    try { await API('/api/승인', { 여행ID: 앱.여행ID, 편ID: 앱.데이터.편, 승인 }); 쪽지(승인 ? '이 글을 승인했어요.' : '승인을 취소했어요.'); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async 임시저장시작(b) {
    const 편ID = b.dataset.편;
    초안저장();
    const 예약 = 앱.초안[`발행모드예약-${편ID}`] === true;
    const 내용 = { 여행ID: 앱.여행ID, 편ID, 모드: 예약 ? '예약발행' : '임시저장' };
    if (예약) {
      const 값 = 앱.초안[`예약시각-${편ID}`];
      if (!값) { 쪽지('예약 시각을 정해 주세요.', { 종류: '오류' }); return; }
      const t = new Date(값);
      const 오프셋 = -t.getTimezoneOffset(), 부호 = 오프셋 >= 0 ? '+' : '-';
      내용.예약시각 = `${값.length === 16 ? 값 + ':00' : 값}${부호}${String(Math.floor(Math.abs(오프셋) / 60)).padStart(2, '0')}:${String(Math.abs(오프셋) % 60).padStart(2, '0')}`;
      if (!await 확인창(`예약 발행을 걸까요?<br>${h(값.replace('T', ' '))}에 네이버에 공개돼요.<br><span class="흐림">${h(앱.데이터?.발행?.예약경고 || '')}</span>`, '예약 걸기', '그만두기')) return;
      쪽지('컴퓨터 화면에 뜬 ‘네이버 예약 발행’ 확인 창에서 [예약 발행 작업 만들기]를 마우스로 눌러 주세요.', { 시간: 20000 });
    }
    const { 저장, 실패 } = 발행이력(앱.데이터?.발행);
    if (실패) {
      if (!await 확인창(`실패한 작업이 있어요(${h(실패.실패?.단계 || 실패.현재단계 || '')} 단계).<br>채우던 화면에서 이어 하려면 <b>[다시 시도]</b>를 누르세요.<br>새 글쓰기 화면에서 <b>새 글로 처음부터</b> 할까요?${저장 ? '<br><span class="흐림">이 글은 전에 임시저장한 적도 있어요 — 네이버에 새 글로 하나 더 저장돼요.</span>' : ''}`, '새 글로 처음부터', '그만두기')) return;
      내용.새로 = true;
    } else if (저장) {
      if (!await 확인창(`이 글은 이미 네이버에 임시저장했어요${저장.끝 ? `(${h(짧은시각(저장.끝))})` : ''}.<br>다시 하면 네이버 임시저장 글이 <b>하나 더</b> 생겨요.<br><span class="흐림">고친 내용을 넣으려면 네이버에서 앞 글을 지우거나, 새 글을 확인한 뒤 하나만 발행하세요.</span>`, '다시 임시저장(새 글로 저장됨)', '그만두기')) return;
      내용.새로 = true;
    }
    b.disabled = true;
    try {
      const r = await API('/api/발행작업', 내용).catch(async (e) => {
        if (!['이미_임시저장', '실패한_작업있음'].includes(e.코드)) throw e; // 화면이 늦게 바뀐 사이 다른 곳에서 저장됨
        if (!await 확인창(`${h(e.message)}`, e.코드 === '이미_임시저장' ? '다시 임시저장(새 글로 저장됨)' : '새 글로 처음부터', '그만두기')) return null;
        return API('/api/발행작업', { ...내용, 새로: true });
      });
      if (!r) { b.disabled = false; return; }
      const 열기 = r.브라우저 || {};
      쪽지(열기.열림 ? `작업을 만들고 ${브라우저이름[열기.브라우저] || ''}에서 글쓰기 화면을 열었어요. 블로그 도우미가 채우기 시작해요.`
        : `작업을 만들었어요. ${열기.이유 || (열기.시험모드 ? '(시험 모드라 브라우저는 열지 않았어요.)' : '')} 네이버 글쓰기 화면을 열면 블로그 도우미가 시작해요.`, { 시간: 12000 });
      화면그리기({ 유지: true });
    } catch (e) { b.disabled = false; 오류쪽지(e); }
  },
  async 발행다시(b) {
    const 처음부터 = b.dataset.편 === '처음';
    if (처음부터 && !await 확인창('이 글을 처음(준비 단계)부터 다시 채울까요? 네이버 글쓰기 화면은 새로 열린 빈 화면이어야 해요.', '처음부터', '그만두기')) return;
    try { const r = await API('/api/발행작업/다시', { 작업ID: b.dataset.값, 처음부터 }); 쪽지(`다시 시작해요(${r.작업?.시작단계 || ''}부터).${r.브라우저?.이어하기 ? ' ' + r.브라우저.이유 : ''}`, { 시간: 12000 }); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async 발행취소(b) {
    if (!await 확인창('이 발행 작업을 취소할까요? 이미 채운 내용은 네이버 화면에 그대로 남아요.', '취소하기', '그대로 두기')) return;
    try { await API(`/api/발행/작업/${encodeURIComponent(b.dataset.값)}/취소`, {}); 쪽지('작업을 취소했어요.'); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async 글쓰기열기() {
    try { const r = await API('/api/글쓰기열기', {}); 쪽지(r.열림 ? `${브라우저이름[r.브라우저] || ''}에서 글쓰기 화면을 열었어요.` : (r.이유 || '열지 못했어요.'), { 종류: r.열림 ? '보통' : '오류' }); } catch (e) { 오류쪽지(e); }
  },
  확장연결: 확장연결창,
  async 연결끊기(b) {
    if (!await 확인창('이 확장의 연결을 끊을까요? 다시 쓰려면 연결 코드를 새로 넣어야 해요.', '연결 끊기', '그대로 두기')) return;
    try { await API('/api/확장연결/해제', { 확장ID: b.dataset.값 }); 쪽지('연결을 끊었어요.'); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async 브라우저(b) { try { await API('/api/설정', { 브라우저: b.value }); 쪽지(`글쓰기 화면은 ${브라우저이름[b.value]}(으)로 열게요.`); } catch (e) { 오류쪽지(e); } },
  async 블로그ID저장() {
    const 값 = (앱.초안['블로그ID'] ?? $('[data-초안="블로그ID"]')?.value ?? '').trim();
    try { await API('/api/설정', { 블로그ID: 값 }); 쪽지(값 ? `블로그 아이디를 저장했어요: ${값}` : '블로그 아이디를 지웠어요.'); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); }
  },
  async 예약설정(b) {
    const 켜기 = b.checked;
    if (켜기) {
      b.checked = false;
      const 경고 = 앱.데이터?.설정?.경고 || '';
      if (!await 확인창(`<b>자동 예약 발행을 켤까요?</b><br>${h(경고)}<br><br>그래도 켜려면 [위험을 알고 켜기]를 누르세요.`, '위험을 알고 켜기', '끄고 두기')) return;
    }
    if (켜기) 쪽지('컴퓨터 화면에 뜬 ‘여행 스튜디오’ 확인 창에서 [예]를 눌러 주세요(브라우저 뒤에 있을 수 있어요).', { 시간: 20000 });
    try { await API('/api/설정', 켜기 ? { 자동예약발행: true, 위험확인: true } : { 자동예약발행: false }); 쪽지(`자동 예약 발행을 ${켜기 ? '켰어요' : '껐어요'}.`); 화면그리기({ 유지: true }); } catch (e) { 오류쪽지(e); 화면그리기({ 유지: true }); }
  },
  테마(b) { 테마정하기(b.value); },
  async 공용갱신() {
    if (!await 확인창('교재의 공용 파일(미리보기·발행 모듈)을 이 스튜디오로 가져올까요?<br><span class="흐림">교재 저장소의 ‘참고구현/공용’ 에서만 가져와요. 진행 중인 발행 작업이 없을 때 누르세요.</span>', '가져오기', '그만두기')) return;
    try { const r = await API('/api/공용갱신', {}); 쪽지(`공용 파일을 갱신했어요: ${(r.복사 || []).join(', ') || '바뀐 것 없음'}`); await 살피기(); } catch (e) { 오류쪽지(e); }
  },
  async 처음부터(b) {
    if (!await 확인창('이 작업을 처음부터 다시 할까요? 지금까지 만든 결과 파일은 지우지 않고 작업함/처리완료/보관/으로 옮겨요.', '처음부터 다시', '그만두기')) return;
    try { await 요청보내기('재시도', { 작업ID: b.dataset.값, 처음부터: true }); } catch (e) { 오류쪽지(e); }
  },
  이력거르기(b) { 앱.보기['이력거르기'] = b.dataset.값; 다시그리기(); },
  로그보기(b) { 로그창(b.dataset.값); },
  로그날짜(b) { 로그창(`로그/${b.value}.log`); },
  수리복사(b) { 복사하기(수리문구(b.dataset.편 || '', b.dataset.값 || '')); },
  멈춤닫기(b) { const 닫음 = JSON.parse(기억읽기('닫은멈춤') || '[]'); 닫음.push(b.dataset.값); 기억쓰기('닫은멈춤', JSON.stringify(닫음.slice(-50))); 띠그리기(); },
  async 영상만들기() {
    const id = 앱.여행ID;
    const 길이 = (앱.초안[`영상길이-${id}`] || '8:10').trim();
    const m = /^(\d{1,2}):(\d{2})$/.exec(길이);
    if (!m) { 쪽지('목표 길이는 8:10처럼 분:초로 적어 주세요.', { 종류: '오류' }); return; }
    const 음악파일 = (앱.초안[`영상음악-${id}`] || '').trim();
    if (음악파일 && (/[\\/:]/.test(음악파일) || !/\.(mp3|m4a|aac|wav|ogg|flac)$/i.test(음악파일))) {
      쪽지('음악은 음악 폴더에 넣은 오디오 파일의 이름만 적어 주세요(예: bgm.mp3).', { 종류: '오류' }); return;
    }
    try { await 요청보내기('영상', { 목표초: (+m[1]) * 60 + (+m[2]), ...(음악파일 ? { 음악파일 } : {}) }); } catch (e) { 오류쪽지(e); }
  },
  async 복사(b) { 복사하기(b.dataset.값); },
  async 음악폴더() {
    try {
      const r = await API('/api/폴더열기', { 여행ID: 앱.여행ID, 폴더: '음악' });
      쪽지(r.열림 ? `${r.폴더} 폴더를 열었어요. 음악 파일을 넣고 파일 이름을 적어 주세요.` : (r.이유 || `${r.폴더} 폴더를 만들었어요(시험 모드라 열지는 않았어요).`), { 시간: 10000 });
    } catch (e) { 오류쪽지(e); }
  },
};
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-할일]');
  if (!el || el.disabled) return;
  if (el.tagName === 'INPUT' || el.tagName === 'SELECT') return; // 값 바꾸기는 change 에서
  const 할일 = 할일들[el.dataset.할일];
  if (!할일) return;
  if (el.tagName === 'DETAILS') { 할일(el); return; } // 열고 닫기는 브라우저가 처리
  e.preventDefault();
  할일(el);
});
document.addEventListener('input', (e) => { const k = e.target.dataset?.초안; if (k) 앱.초안[k] = e.target.type === 'checkbox' || e.target.type === 'radio' ? e.target.checked : e.target.value; });
document.addEventListener('change', (e) => {
  const k = e.target.dataset?.초안;
  if (k) 앱.초안[k] = e.target.type === 'checkbox' || e.target.type === 'radio' ? e.target.checked : e.target.value;
  if (e.target.name === '발행모드') { $$('input[name="발행모드"]').forEach((r) => { 앱.초안[r.dataset.초안] = r.checked; }); }
  const 할일 = e.target.dataset?.할일 && 할일들[e.target.dataset.할일];
  if (할일 && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT')) 할일(e.target);
});
$('#연결단추').addEventListener('click', 클로드연결);
$('.건너뛰기')?.addEventListener('click', (e) => { e.preventDefault(); $('#본문').focus(); });
$('#테마단추').addEventListener('click', () => 테마정하기(지금테마() === 'dark' ? 'light' : 'dark'));

// ───────────────────────────── 시작
(async () => {
  테마단추그리기();
  await 살피기();
  await 화면그리기();
  setTimeout(살피기반복, 2000);
})();
