/* 블로그 도우미 — 연결 팝업: 연결 코드 입력 → 토큰 받기(background.js 가 서버와 이야기함) */
'use strict';

const $ = (id) => document.getElementById(id);

function send(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      if (chrome.runtime.lastError) resolve({ ok: false, 오류: chrome.runtime.lastError.message });
      else resolve(resp || { ok: false, 오류: '응답 없음' });
    });
  });
}

function showMsg(text, kind) {
  $('msg').textContent = text;
  $('msg').setAttribute('data-kind', kind || 'info');
}

async function refresh() {
  const r = await send({ 종류: '연결확인' });
  if (r.ok) {
    $('state').textContent = '연결됨 · ' + ((r['데이터'] && r['데이터']['서버']) || '로컬 서버');
    $('state').setAttribute('data-kind', 'on');
    $('disconnect').hidden = false;
  } else {
    const off = r['코드'] === '연결필요' ? '연결 안 됨 — 연결 코드를 넣으세요' : (r['오류'] || '연결 안 됨');
    $('state').textContent = off;
    $('state').setAttribute('data-kind', 'off');
    $('disconnect').hidden = r['코드'] === '연결필요';
  }
}

$('pair').addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = $('code').value.replace(/\D/g, '');
  if (code.length !== 6) { showMsg('숫자 6자리를 넣으세요.', 'error'); return; }
  $('connect').disabled = true;
  showMsg('연결하는 중…');
  const r = await send({ 종류: '연결', 코드: code });
  $('connect').disabled = false;
  if (r.ok) {
    $('code').value = '';
    showMsg('연결했습니다. 네이버 글쓰기 화면을 열면 도우미 패널이 작업을 받습니다.', 'done');
  } else {
    showMsg(r['오류'] || '연결하지 못했습니다.', 'error');
  }
  refresh();
});

$('disconnect').addEventListener('click', async () => {
  await send({ 종류: '연결끊기' });
  showMsg('연결을 끊었습니다.', 'done');
  refresh();
});

// 보조 도구(사진 묶음만 넣기) 켜기·끄기 — 사람이 이 팝업에서만 바꿈(검수 M2)
chrome.storage.local.get('auxTool', (v) => { $('aux').checked = !!(v && v.auxTool); });
$('aux').addEventListener('change', (e) => {
  if (!e.isTrusted) return;
  chrome.storage.local.set({ auxTool: $('aux').checked });
  showMsg($('aux').checked ? "보조 도구를 켰습니다. 글쓰기 화면을 새로고침하면 패널에 '사진 묶음만 넣기'가 보입니다." : '보조 도구를 껐습니다.', 'done');
});

refresh();
