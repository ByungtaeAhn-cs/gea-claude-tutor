/*
 * 블로그 도우미 v2 — 에디터 화면의 패널과 '글 전체 채우기' (content script, 확장 쪽 세계)
 * ---------------------------------------------------------------------------
 * 구성
 *   1. 작은 도구
 *   2. 사진 넣기 핵심 — (a) 사진 업로드 칸 / (b) 끌어다 놓기  (v1 그대로, 하네스에서도 씀)
 *   3. 프레임 판별 (에디터가 mainFrame iframe 안에 있을 수 있음)
 *   4. 글 채우기 엔진 — 서버에서 받은 작업을 단계별로: 준비 → 제목 → 블록들 → 태그 → 카테고리
 *      → 공개설정 → AI활용 → 저장(임시저장) → (조건이 다 맞을 때만) 예약발행
 *   5. 패널 — 연결 상태, 작업·단계 목록, [멈춤]·[이 단계부터 다시]·[이 단계는 내가 했음], 보조 '사진 묶음만 넣기'
 *   6. 시작
 *
 * 지키는 것
 *   - 로그인·비밀번호·캡차는 건드리지 않음. 그런 화면이면 바로 멈추고 보고.
 *   - 기본(임시저장) 작업에서는 발행 '확인' 버튼을 누르지 않음. 작업 중에는 그 버튼 클릭을 막는 안전장치를 켬.
 *   - 실패한 단계에서 멈춤(추측 클릭 금지). 다시 할 때는 그 단계부터.
 *   - 외부 서버로 아무것도 보내지 않음(서버와의 통신은 background.js 가 내 PC 의 127.0.0.1:8765 와만).
 * 선택자·방법은 selectors.js 에 있습니다.
 */
(function () {
  'use strict';
  if (globalThis.__blogHelperContentLoaded) return; // 같은 프레임에 두 번 들어오는 것 방지
  globalThis.__blogHelperContentLoaded = true;

  var VERSION = '0.5.0';
  var S = globalThis.BLOG_HELPER_SELECTORS;
  if (!S) {
    console.warn('[블로그 도우미] selectors.js 가 먼저 로드되지 않았습니다.');
    return;
  }
  var IS_EXTENSION = !!(globalThis.chrome && chrome.runtime && chrome.runtime.id);
  var ARM_ATTR = 'data-blog-helper-arm';
  var PANEL_ID = 'blog-helper-panel';
  var MARK_ATTR = 'data-blog-helper'; // <html data-blog-helper="editor|shell|waiting|no-editor"> 실측용 표시
  // 검수 M2: 패널은 '닫힌' 그림자 루트 안에 — 페이지 스크립트가 패널 DOM·로그·목록을 보거나 버튼을 누르지 못하게.
  // (확장 밖 시험 하네스에서만 열린 모드 — 시험 도구가 패널을 읽을 수 있게)
  var SHADOW_MODE = IS_EXTENSION ? 'closed' : 'open';
  var PANEL_UI = null; // {host, root, panel}

  function randomHex(bytes) {
    var a = new Uint8Array(bytes || 16);
    crypto.getRandomValues(a);
    return Array.prototype.map.call(a, function (x) { return (x < 16 ? '0' : '') + x.toString(16); }).join('');
  }

  // ── 1. 작은 도구 ───────────────────────────────────────────────────────
  function rawSleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  /** 단계 안에서 쓰는 기다림: 깨어난 뒤 그 단계가 멈춤(시간 초과)·보호조치 상태면 바로 멈춤 */
  function sleep(ms) {
    return rawSleep(ms).then(function () { if (RUN.cancelled || RUN.doc) assertLive(); });
  }

  function isOurs(el) {
    return !!(el && el.closest && el.closest('#' + PANEL_ID));
  }

  /** 선택자 목록을 차례로 시도해 처음 찾은 요소. 패널 안 요소는 무시. */
  function first(root, list) {
    for (var i = 0; i < (list || []).length; i++) {
      try {
        var nodes = root.querySelectorAll(list[i]);
        for (var j = 0; j < nodes.length; j++) {
          if (!isOurs(nodes[j])) return { el: nodes[j], sel: list[i] };
        }
      } catch (_) { /* 잘못된 선택자는 건너뜀 */ }
    }
    return null;
  }

  function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function formatBytes(n) {
    n = Number(n) || 0;
    if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + 'MB';
    if (n >= 1024) return Math.round(n / 1024) + 'KB';
    return n + 'B';
  }

  function isFileInput(el) {
    return !!el && el.tagName === 'INPUT' && String(el.type).toLowerCase() === 'file';
  }

  // ── 2. 사진 넣기 핵심 ───────────────────────────────────────────────────────
  /** 에디터에 들어간 사진 수(서로 다른 img 기준. img 가 아직 없는 사진 모듈은 모듈 자체를 셈) */
  function countImages(root) {
    var set = new Set();
    (S.insertedImage || []).forEach(function (sel) {
      try {
        root.querySelectorAll(sel).forEach(function (n) {
          if (isOurs(n)) return;
          if (n.tagName === 'IMG') { set.add(n); return; }
          var imgs = n.querySelectorAll('img');
          if (imgs.length) imgs.forEach(function (i) { set.add(i); }); else set.add(n);
        });
      } catch (_) { /* 잘못된 선택자는 건너뜀 */ }
    });
    return set.size;
  }

  /** 지금 에디터에 보이는 '사진이 들어갔다'는 신호 */
  function snapshot(doc) {
    var popup = first(doc, S.layoutPopup);
    return {
      images: countImages(doc),
      popup: !!(popup && isVisible(popup.el)),
      progress: !!first(doc, S.uploadProgress),
    };
  }

  /** before 와 비교해 사진이 늘거나 배치 선택 창이 뜨면 성공. 업로드 진행 표시가 보이면 한 번 더 기다림. */
  async function waitForEffect(doc, before, timeoutMs, onSlow) {
    var start = Date.now();
    var deadline = start + timeoutMs;
    var extended = false;
    var slowTold = false;
    while (Date.now() < deadline) {
      assertLive();
      var now = snapshot(doc);
      if (now.images > before.images) {
        return { ok: true, 근거: '에디터의 사진이 ' + before.images + '개 → ' + now.images + '개', popup: now.popup };
      }
      if (now.popup && !before.popup) {
        return { ok: true, 근거: '네이버의 배치 선택 창(개별 사진/콜라주/슬라이드)이 뜸', popup: true };
      }
      if (now.progress && !extended) {
        deadline += timeoutMs;
        extended = true;
      }
      if (onSlow && !slowTold && Date.now() - start > S.timing.effectWaitMs) {
        slowTold = true;
        onSlow();
      }
      await sleep(200);
    }
    return { ok: false, popup: snapshot(doc).popup };
  }

  /** 성공 뒤, 여러 장인데 일부만 보이면 주의 문장을 돌려줌(배치 선택 창이 뜬 경우는 셀 수 없어 건너뜀) */
  async function partialNotes(doc, before, expected, eff) {
    if (eff.popup || expected < 2) return [];
    var deadline = Date.now() + (S.timing.settleMs || 3000);
    var seen = snapshot(doc).images - before.images;
    while (seen < expected && Date.now() < deadline) {
      assertLive();
      await sleep(200);
      seen = snapshot(doc).images - before.images;
    }
    return seen < expected
      ? ['사진이 ' + expected + '장 중 ' + Math.max(seen, 0) + '장만 보임 — 일부만 들어갔을 수 있으니 화면을 확인하세요']
      : [];
  }

  function makeDataTransfer(files) {
    var dt = new DataTransfer();
    files.forEach(function (f) { dt.items.add(f); });
    return dt;
  }

  // 갈고리(page-hook.js)가 가로챈 input 표시: data-blog-helper-captured="순번:난수"
  // 검수 L6: 이번에 켤 때 정한 일회 난수가 붙은 것만 인정(페이지가 미리 심어 둔 가짜 input 은 무시)
  function capturedMark(el) {
    var v = String(el.getAttribute('data-blog-helper-captured') || '');
    var i = v.indexOf(':');
    return { seq: Number(i >= 0 ? v.slice(0, i) : v) || 0, nonce: i >= 0 ? v.slice(i + 1) : '' };
  }

  function maxCapturedSeq(doc) {
    var max = 0;
    doc.querySelectorAll('input[data-blog-helper-captured]').forEach(function (el) {
      max = Math.max(max, capturedMark(el).seq);
    });
    return max;
  }

  /** 이번 켜기(난수)에서 가로챈 input 중 가장 나중 것. 난수가 같으면 이번에 잡은 것이므로 순번 기준선은 쓰지 않음
   *  (페이지가 큰 순번의 가짜 input 을 심어 기준선을 올려도 진짜 input 을 놓치지 않게) */
  function latestCaptured(doc, _afterSeq, nonce) {
    var best = null;
    var bestSeq = -1;
    doc.querySelectorAll('input[data-blog-helper-captured]').forEach(function (el) {
      var m = capturedMark(el);
      if (!nonce || m.nonce !== nonce) return;
      if (m.seq > bestSeq) { best = el; bestSeq = m.seq; }
    });
    return best;
  }

  /** 갈고리 켜기: <html data-blog-helper-arm="만료ms:난수">. 난수를 돌려줌 */
  function armHook(doc, ms, nonce) {
    nonce = nonce || randomHex(16);
    doc.documentElement.setAttribute(ARM_ATTR, String(Date.now() + ms) + ':' + nonce);
    return nonce;
  }

  /** 선택자에 맞는 사진용 file input (지난번에 갈고리가 잠깐 붙인 input 과 except 집합은 뺌) */
  function findPhotoInput(doc, except) {
    var lists = [S.fileInput];
    if (S.allowAnyFileInput) lists.push(['input[type="file"]']);
    for (var k = 0; k < lists.length; k++) {
      for (var i = 0; i < lists[k].length; i++) {
        var nodes;
        try { nodes = doc.querySelectorAll(lists[k][i]); } catch (_) { continue; }
        for (var j = 0; j < nodes.length; j++) {
          var n = nodes[j];
          if (isOurs(n) || n.hasAttribute('data-blog-helper-attached') || (except && except.has(n))) continue;
          return { el: n, sel: lists[k][i] };
        }
      }
    }
    return null;
  }

  function fireButton(btn) {
    assertLive();
    var events = (S.photoButtonEvents && S.photoButtonEvents.length) ? S.photoButtonEvents : ['click'];
    events.forEach(function (type) {
      if (type === 'click') { btn.click(); return; }
      var Ctor = type.indexOf('pointer') === 0 && typeof PointerEvent === 'function' ? PointerEvent : MouseEvent;
      btn.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true, composed: true, button: 0, buttons: 1 }));
    });
  }

  /**
   * 사진 업로드용 file input 을 구합니다. (갈고리는 tryFileInput 이 켜 둔 상태)
   *  1) '사진' 버튼을 누르고, 페이지가 열려는 input 을 가로채거나(page-hook.js) 새로 생긴 input 을 찾음
   *  2) 그래도 없으면 보조로, 원래 문서에 있던 사진용 input
   */
  async function obtainFileInput(doc, log, guardState, nonce) {
    var btn = first(doc, S.photoButton);
    if (btn) {
      var seqBefore = maxCapturedSeq(doc);
      var beforeInputs = new Set(Array.prototype.slice.call(doc.querySelectorAll('input[type="file"]')));
      log('사진 버튼을 누름 (' + btn.sel + ') — 파일 선택 창은 가로채서 열지 않음');
      fireButton(btn.el);
      var deadline = Date.now() + S.timing.inputWaitMs;
      while (Date.now() < deadline) {
        assertLive();
        var cap = latestCaptured(doc, seqBefore, nonce);
        if (cap) {
          log('페이지가 연 file input 을 가로챔' + (cap.getAttribute('data-blog-helper-attached') ? ' (문서에 없던 input — 잠깐 붙임)' : ' (문서에 있는 input)'));
          return { input: cap, how: 'captured' };
        }
        if (guardState.el) {
          log('click 이벤트로 열리던 file input 을 잡음');
          return { input: guardState.el, how: 'guarded' };
        }
        var appeared = findPhotoInput(doc, beforeInputs);
        if (appeared) {
          log('버튼을 누른 뒤 생긴 file input 을 찾음 (' + appeared.sel + ')');
          return { input: appeared.el, how: 'appeared' };
        }
        await sleep(100);
      }
      log('사진 버튼을 눌렀지만 ' + S.timing.inputWaitMs + 'ms 안에 file input 을 잡지 못함');
    } else {
      log('사진 버튼을 찾지 못함 (selectors.photoButton)');
    }
    var existing = findPhotoInput(doc, null);
    if (existing) {
      log('보조: 원래 문서에 있던 file input 을 씀 (' + existing.sel + ') — 다른 업로드 칸일 수 있으니 결과를 꼭 확인');
      return { input: existing.el, how: 'existing' };
    }
    return null;
  }

  function cleanupCaptured(input) {
    if (input && input.getAttribute && input.getAttribute('data-blog-helper-attached') === '1') {
      setTimeout(function () { if (input.isConnected) input.remove(); }, 3000);
    }
  }

  /**
   * 방법 (a): 사진 업로드용 file input 에 파일을 넣고 input/change 이벤트.
   * 결과의 '전달'이 true 면 파일을 input 까지는 넣었다는 뜻(그 뒤 반응이 없으면 '확인 필요').
   */
  async function tryFileInput(files, ctx) {
    var doc = ctx.doc;
    var log = ctx.log;
    var win = doc.defaultView;
    var html = doc.documentElement;
    var before = snapshot(doc);
    var guardState = { el: null };
    // 문서에 붙은 input 이 click 이벤트로 열리는 경우를 막는 보조 장치(확장 쪽 세계에서 동작)
    var guard = function (e) {
      if (isFileInput(e.target) && !isOurs(e.target)) {
        e.preventDefault();
        guardState.el = e.target;
      }
    };
    // 갈고리는 input 을 구하는 동안 + 파일을 넣은 뒤 inputWaitMs 동안만 켜 둠
    // (네이버가 조금 늦게 파일 선택 창을 열려 해도 막고, 그 뒤 사람이 '사진' 버튼을 누르면 평소대로 열리게)
    var armed = true;
    var disarm = function () {
      if (!armed) return;
      armed = false;
      html.removeAttribute(ARM_ATTR);
      win.removeEventListener('click', guard, true);
    };
    var nonce = armHook(doc, S.timing.inputWaitMs + 5000);
    win.addEventListener('click', guard, true);
    var got = null;
    try {
      got = await obtainFileInput(doc, log, guardState, nonce);
      if (!got) return { ok: false, 방법: 'a', 전달: false, 사유: '사진 업로드용 file input 을 찾지 못함' };
      var input = got.input;
      var notes = [];
      if (got.how === 'existing') notes.push('사진 버튼으로 칸을 못 찾아 원래 있던 업로드 칸에 넣음 — 다른 업로드 칸일 수 있음');
      if (files.length > 1 && !input.multiple) {
        log('주의: 이 input 은 여러 장(multiple) 표시가 없음');
        notes.push('네이버 사진 칸에 여러 장 받기 표시가 없음 — 일부만 들어갔을 수 있음');
      }
      var accept = (input.getAttribute('accept') || '').toLowerCase();
      if (accept) {
        files.forEach(function (f) {
          var ext = (f.name.split('.').pop() || '').toLowerCase();
          if (accept.indexOf('.' + ext) < 0 && accept.indexOf(f.type) < 0 && accept.indexOf('image/*') < 0) {
            log('주의: ' + f.name + ' 형식이 input 의 accept(' + accept + ')에 없음');
          }
        });
      }
      try {
        input.files = makeDataTransfer(files).files;
      } catch (err) {
        return { ok: false, 방법: 'a', 전달: false, 사유: 'input 에 파일을 넣지 못함: ' + err.message };
      }
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      log('file input 에 ' + files.length + '장을 넣고 input/change 이벤트를 보냄');
      armHook(doc, S.timing.inputWaitMs, nonce);
      setTimeout(disarm, S.timing.inputWaitMs);
      var eff = await waitForEffect(doc, before, S.timing.deliveredWaitMs, function () {
        log(S.timing.effectWaitMs / 1000 + '초가 지나도 아직 안 보임 — 업로드가 느릴 수 있어 최대 ' + S.timing.deliveredWaitMs / 1000 + '초까지 기다림');
      });
      if (!eff.ok) {
        return { ok: false, 방법: 'a', 전달: true, 주의: notes, 사유: '사진 칸에 넣었지만 ' + S.timing.deliveredWaitMs / 1000 + '초 안에 화면에 사진이 보이지 않음' };
      }
      notes = notes.concat(await partialNotes(doc, before, files.length, eff));
      return { ok: true, 방법: 'a', 사유: eff.근거, popup: eff.popup, 주의: notes };
    } finally {
      disarm();
      if (got) cleanupCaptured(got.input);
    }
  }

  // 사람이 마지막으로 클릭한 본문 위치(끌어다 놓기 지점으로 씀)
  var lastPoint = null;
  function rememberPoint(e) {
    if (!e.isTrusted || isOurs(e.target)) return;
    var t = e.target;
    if (!t || !t.getBoundingClientRect) return;
    var r = t.getBoundingClientRect();
    lastPoint = { el: t, dx: e.clientX - r.left, dy: e.clientY - r.top };
  }

  function dropPoint(doc, target) {
    var win = doc.defaultView;
    if (lastPoint && lastPoint.el.isConnected && target.contains(lastPoint.el)) {
      var r = lastPoint.el.getBoundingClientRect();
      var x = r.left + lastPoint.dx;
      var y = r.top + lastPoint.dy;
      if (x >= 0 && y >= 0 && x <= win.innerWidth && y <= win.innerHeight) return { x: x, y: y, 근거: '마지막으로 클릭한 본문 위치' };
    }
    var t = target.getBoundingClientRect();
    var left = Math.max(t.left, 0);
    var right = Math.min(t.right, win.innerWidth);
    var top = Math.max(t.top, 0);
    var bottom = Math.min(t.bottom, win.innerHeight);
    return { x: (left + right) / 2, y: (top + bottom) / 2, 근거: '편집 영역 가운데(클릭한 위치가 없음)' };
  }

  /** 방법 (b): 본문 편집 영역에 파일을 담은 dragenter/dragover/drop 이벤트 합성 */
  async function tryDrop(files, ctx) {
    var doc = ctx.doc;
    var log = ctx.log;
    var found = first(doc, S.dropTarget);
    if (!found) return { ok: false, 방법: 'b', 사유: '끌어다 놓을 편집 영역을 찾지 못함 (selectors.dropTarget)' };
    var area = found.el;
    var pt = dropPoint(doc, area);
    var target = doc.elementFromPoint(pt.x, pt.y);
    if (!target || !area.contains(target) || isOurs(target)) target = area;
    log('끌어다 놓기 대상: ' + found.sel + ' / 지점: ' + pt.근거);
    var before = snapshot(doc); // (a)의 결과가 (b)의 성공으로 잘못 세지지 않게 바로 전에 잼
    var dt = makeDataTransfer(files);
    var dragoverAccepted = false;
    ['dragenter', 'dragover', 'drop'].forEach(function (type) {
      var ev = new DragEvent(type, {
        bubbles: true, cancelable: true, composed: true,
        dataTransfer: dt, clientX: pt.x, clientY: pt.y,
      });
      var notCanceled = target.dispatchEvent(ev);
      if (type === 'dragover') dragoverAccepted = !notCanceled;
    });
    log('dragover 를 에디터가 ' + (dragoverAccepted ? '받아들임(preventDefault)' : '받아들이지 않음') + ', drop 보냄');
    var eff = await waitForEffect(doc, before, S.timing.effectWaitMs);
    if (eff.ok) {
      return { ok: true, 방법: 'b', 사유: eff.근거, popup: eff.popup, 주의: await partialNotes(doc, before, files.length, eff) };
    }
    return {
      ok: false, 방법: 'b',
      사유: dragoverAccepted ? 'drop 을 보냈지만 사진이 나타나지 않음' : '에디터가 합성한 끌어다 놓기를 받지 않음',
    };
  }

  /**
   * (a) → (b) 순서로 시도.
   * 결과: {ok, 방법:'a'|'b'|null, 확인필요, 시도:[...], popup, 주의:[...], 기록:[...]}
   * opts.method: 'auto' | 'a' | 'b'
   * 자동일 때 (b)는 (a)가 파일을 사진 칸에 넣지도 못한 경우에만 이어서 합니다.
   * (a)가 파일을 넣었는데 반응이 없으면 '확인 필요'로 멈춥니다 — 업로드가 늦게 끝나 같은 사진이
   * 두 번 들어가는 것을 막기 위해서입니다.
   */
  async function insertFiles(files, opts) {
    opts = opts || {};
    var doc = opts.doc || document;
    var method = opts.method || 'auto';
    var logs = [];
    var log = function (m) {
      logs.push(m);
      if (opts.onLog) opts.onLog(m);
      try { console.debug('[블로그 도우미] ' + m); } catch (_) { /* 무시 */ }
    };
    var tries = [];
    if (!files || !files.length) return { ok: false, 방법: null, 시도: [], 주의: [], 기록: ['넣을 파일이 없음'] };
    log(files.length + '장 넣기 시작 (방법: ' + method + ')');

    if (method === 'auto' || method === 'a') {
      var a = await tryFileInput(files, { doc: doc, log: log });
      tries.push(a);
      if (a.ok) return { ok: true, 방법: 'a', 시도: tries, popup: !!a.popup, 주의: a.주의 || [], 기록: logs };
      log('(a) 실패: ' + a.사유);
      if (a.전달) {
        if (method === 'auto') log('(a)에서 파일은 사진 칸까지 넣었으므로 (b)를 자동으로 하지 않음(두 번 들어가는 것 방지)');
        return { ok: false, 방법: null, 확인필요: true, 시도: tries, popup: snapshot(doc).popup, 주의: a.주의 || [], 기록: logs };
      }
    }
    if (method === 'auto' || method === 'b') {
      var b = await tryDrop(files, { doc: doc, log: log });
      tries.push(b);
      if (b.ok) return { ok: true, 방법: 'b', 시도: tries, popup: !!b.popup, 주의: b.주의 || [], 기록: logs };
      log('(b) 실패: ' + b.사유);
    }
    return { ok: false, 방법: null, 시도: tries, popup: snapshot(doc).popup, 주의: [], 기록: logs };
  }

  // ── 3. 프레임 판별 ─────────────────────────────────────────────────────
  function isWriteUrl(href) {
    return (S.writeUrl || []).some(function (re) { return re.test(href); });
  }

  /** 'editor' = 이 문서에 에디터 본체가 있음 / 'shell' = 에디터 iframe(mainFrame)을 품은 바깥 화면 / 'none' */
  function frameRole(doc) {
    doc = doc || document;
    if (first(doc, S.shellIframe)) return 'shell';
    if (first(doc, S.editorRoot)) return 'editor';
    return 'none';
  }

  function mark(state) {
    try { document.documentElement.setAttribute(MARK_ATTR, state); } catch (_) { /* 무시 */ }
  }

  // ── 4. 글 채우기 엔진 ──────────────────────────────────────────────────
  function StepError(code, message) {
    this.code = code;
    this.message = message;
  }

  // 지금 실행 중인 단계의 표식. 시간 초과면 cancelled=true → 다음 동작(waitFor·sleep·clickEl·사진 받기)에서 바로 멈춤.
  // 시간 초과된 단계가 30초 안에 멈추지 않으면 zombie 로 남기고, 그 단계가 끝날 때까지 cancelled 를 풀지 않으며
  // 새 작업도 시작하지 않음(늦게 깨어난 옛 단계가 새 작업 화면을 만지지 않게).
  var RUN = { cancelled: false, doc: null, lastBarrier: 0, zombie: null };
  function assertLive() {
    if (RUN.cancelled) throw new StepError('시간초과', '단계를 멈췄습니다(시간 초과)');
    if (RUN.doc && Date.now() - RUN.lastBarrier > 2000) {
      RUN.lastBarrier = Date.now();
      checkBarrier(RUN.doc); // 단계 도중에 로그인·보호조치·캡차가 떠도 바로 멈춤
    }
  }

  function norm(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }

  /** 선택자 목록에 걸리는 요소 전부, 문서 순서대로 */
  function allOf(root, list) {
    var out = [];
    (list || []).forEach(function (sel) {
      try {
        root.querySelectorAll(sel).forEach(function (n) { if (!isOurs(n) && out.indexOf(n) < 0) out.push(n); });
      } catch (_) { /* 잘못된 선택자 */ }
    });
    return out.sort(function (a, b) {
      return a === b ? 0 : (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
    });
  }

  /** 본문 모듈(제목 제외), 문서 순서 */
  function bodyComponents(doc) {
    return allOf(doc, S.docComponent).filter(function (n) { return !isTitleNode(n) && !(n.parentElement && n.parentElement.closest('.se-component')); });
  }

  /**
   * 방금 넣은 것(pick 이 true 인 마지막 모듈)이 문서 '끝'에 있는지: 그 뒤에는 빈 글 문단만 있어야 함.
   * 커서가 엉뚱한 곳에 있으면 글·사진이 중간에 들어가는데, 이 검사로 잡아 멈춥니다.
   */
  function atDocumentEnd(doc, pick) {
    var comps = bodyComponents(doc);
    var idx = -1;
    comps.forEach(function (c, i) { if (pick(c)) idx = i; });
    if (idx < 0) return false;
    return comps.slice(idx + 1).every(function (c) {
      return !!c.querySelector('.se-text-paragraph') && !textOf(c) && !c.querySelector('img, video, iframe');
    });
  }

  /** 선택자 목록에서 처음 '보이는' 요소(네이버는 숨은 같은 요소가 앞에 오는 일이 있음 [C6]) */
  function visibleFirst(root, list) {
    for (var i = 0; i < (list || []).length; i++) {
      var nodes;
      try { nodes = root.querySelectorAll(list[i]); } catch (_) { continue; }
      for (var j = 0; j < nodes.length; j++) {
        if (!isOurs(nodes[j]) && isVisible(nodes[j])) return { el: nodes[j], sel: list[i] };
      }
    }
    return null;
  }

  function textOf(el) {
    if (!el) return '';
    var c = el.cloneNode(true);
    allOf(c, S.placeholder).forEach(function (p) { p.remove(); });
    return norm(c.textContent);
  }

  async function waitFor(fn, ms, every) {
    var end = Date.now() + ms;
    for (;;) {
      assertLive();
      var v;
      try { v = fn(); } catch (_) { v = null; }
      if (v) return v;
      if (Date.now() >= end) return null;
      await sleep(every || 150);
    }
  }

  function clickEl(el, where) {
    assertLive();
    var doc = el.ownerDocument;
    var view = doc.defaultView;
    try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (_) { /* 무시 */ }
    var r = el.getBoundingClientRect();
    var x = where === 'end' ? r.right - 2 : r.left + r.width / 2;
    var y = where === 'end' ? r.bottom - Math.min(4, r.height / 2) : r.top + r.height / 2;
    (S.clickEvents || ['click']).forEach(function (type) {
      var Ctor = type.indexOf('pointer') === 0 && typeof view.PointerEvent === 'function' ? view.PointerEvent : view.MouseEvent;
      el.dispatchEvent(new Ctor(type, {
        bubbles: true, cancelable: true, composed: true, view: view,
        clientX: x, clientY: y, button: 0, buttons: /down$/.test(type) ? 1 : 0,
      }));
    });
  }

  function pressKey(el, key) {
    assertLive();
    var view = el.ownerDocument.defaultView;
    var codes = { Enter: 13, Escape: 27 };
    ['keydown', 'keypress', 'keyup'].forEach(function (type) {
      if (type === 'keypress' && key !== 'Enter') return;
      el.dispatchEvent(new view.KeyboardEvent(type, {
        key: key, code: key, keyCode: codes[key], which: codes[key], charCode: type === 'keypress' ? codes[key] : 0,
        bubbles: true, cancelable: true, composed: true,
      }));
    });
  }

  /** React 가 관리하는 입력칸에도 값이 들어가게(값을 바꾼 뒤 input·change 이벤트) */
  function setInputValue(input, value) {
    assertLive();
    var view = input.ownerDocument.defaultView;
    var proto = input.tagName === 'SELECT' ? view.HTMLSelectElement.prototype
      : input.tagName === 'TEXTAREA' ? view.HTMLTextAreaElement.prototype : view.HTMLInputElement.prototype;
    var desc = Object.getOwnPropertyDescriptor(proto, 'value');
    desc.set.call(input, value);
    input.dispatchEvent(new view.Event('input', { bubbles: true }));
    input.dispatchEvent(new view.Event('change', { bubbles: true }));
  }

  /**
   * 글자 칸(input·textarea)에 사람이 친 것처럼 넣기: 포커스 → 전체 선택 → execCommand('insertText').
   * 2026-10-08 실측: 장소 검색칸(react-autosuggest)은 setInputValue 로는 글자만 보이고 React 상태가 안 바뀌어 검색이 안 됨.
   * 브라우저가 만든 입력 이벤트는 React 가 확실히 받음. 안 되면 setInputValue 로.
   */
  function typeIntoInput(input, value) {
    assertLive();
    var ok = false;
    try {
      input.focus();
      input.select();
      ok = input.ownerDocument.execCommand('insertText', false, value);
    } catch (_) { ok = false; }
    if (ok && input.value === value) return 'execCommand';
    setInputValue(input, value);
    return 'setter';
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  function toHtml(text) {
    return String(text).split('\n').map(function (line) {
      return line.trim() ? '<p>' + escapeHtml(line) + '</p>' : '<p><br></p>';
    }).join('');
  }

  /** 숨은 입력 프레임(있으면) 또는 지금 포커스가 있는 편집 칸 */
  function inputTarget(doc) {
    var f = first(doc, S.inputBuffer);
    var bdoc = null;
    try { bdoc = f && f.el.contentDocument; } catch (_) { bdoc = null; }
    if (bdoc) {
      var a = bdoc.activeElement;
      var ed = a && a !== bdoc.body ? a : (bdoc.querySelector('[contenteditable="true"]') || bdoc.body);
      return { doc: bdoc, el: ed, how: '숨은 입력 프레임' };
    }
    return { doc: doc, el: doc.activeElement || doc.body, how: '지금 포커스' };
  }

  /** execCommand 는 선택 범위가 있어야 동작: 편집 칸 안에 커서가 없으면 끝에 둠 */
  function ensureSelection(t) {
    try { t.el.focus(); } catch (_) { /* 무시 */ }
    var sel = t.doc.getSelection && t.doc.getSelection();
    if (sel && (!sel.rangeCount || !t.el.contains(sel.anchorNode))) {
      var r = t.doc.createRange();
      r.selectNodeContents(t.el);
      r.collapse(false);
      sel.removeAllRanges();
      sel.addRange(r);
    }
  }

  /** 글을 한 번 넣음(확인은 부른 쪽이 함). method: 'paste' | 'execCommand' */
  function insertTextOnce(doc, text, method, asHtml) {
    assertLive();
    var t = inputTarget(doc);
    var view = t.doc.defaultView;
    if (method === 'paste') {
      var dt = new view.DataTransfer();
      dt.setData('text/plain', text);
      if (asHtml) dt.setData('text/html', toHtml(text));
      t.el.dispatchEvent(new view.ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
      return t.how;
    }
    if (method === 'execCommand') {
      ensureSelection(t);
      var lines = String(text).split('\n');
      lines.forEach(function (line, i) {
        if (i > 0) pressKey(t.el, 'Enter');   // 2026-10-08 실측: insertParagraph 는 에디터가 무시 — 줄 나누기도 Enter 키로
        if (line) t.doc.execCommand('insertText', false, line);
      });
      return t.how;
    }
    throw new StepError('설정오류', '모르는 글 넣기 방법: ' + method);
  }

  function titleEl(doc) { var f = first(doc, S.title); return f && f.el; }
  function titleText(doc) { return textOf(titleEl(doc)); }

  function isTitleNode(n) { return !!(n.closest && n.closest('.se-documentTitle, [data-a11y-title="제목"]')); }
  function isCaptionNode(n) { return !!(n.closest && n.closest('.se-caption')); }

  function bodyParagraphs(doc) {
    return allOf(doc, S.bodyParagraph).filter(function (n) { return !isTitleNode(n) && !isCaptionNode(n); });
  }

  /** 제목을 뺀 본문 전체 글자 */
  function docText(doc) {
    return bodyComponents(doc).map(textOf).join(' ');
  }

  function bodyIsEmpty(doc) {
    var comps = bodyComponents(doc);
    return comps.every(function (c) { return !textOf(c) && !c.querySelector('img, video, iframe'); });
  }

  /** 문서 끝으로 커서 옮기기: 마지막 본문 문단의 끝을 클릭 [C6 _focus_tail] */
  async function focusTail(doc) {
    var paras = bodyParagraphs(doc);
    var last = paras[paras.length - 1];
    if (!last) throw new StepError('선택자없음', '본문 칸을 찾지 못함 (selectors.bodyParagraph)');
    clickEl(last, 'end');
    await sleep(200);
    return last;
  }

  async function ensureEmptyParagraph(doc) {
    var last = await focusTail(doc);
    if (!textOf(last)) return;
    var before = bodyParagraphs(doc).length;
    var methods = S.newParagraphMethods || ['execCommand'];
    for (var i = 0; i < methods.length; i++) {
      var t = inputTarget(doc);
      ensureSelection(t);
      if (methods[i] === 'execCommand') t.doc.execCommand('insertParagraph', false);
      if (methods[i] === 'enter') pressKey(t.el, 'Enter');
      var ok = await waitFor(function () { return bodyParagraphs(doc).length > before; }, S.timing.verifyMs);
      if (ok) { await focusTail(doc); return; }
    }
    throw new StepError('확인필요', '새 문단을 만들지 못함 (selectors.newParagraphMethods)');
  }

  async function setTextFormat(doc, kind) {
    var btn = visibleFirst(doc, S.textFormatButton);
    if (!btn) {
      if (kind === '본문') return '글 유형 버튼이 없어 그대로 둠';
      throw new StepError('선택자없음', "글 유형 버튼을 찾지 못함 — '" + kind + "'으로 바꿀 수 없음 (selectors.textFormatButton)");
    }
    clickEl(btn.el);
    var opt = await waitFor(function () { return visibleFirst(doc, S.textFormatOption[kind]); }, S.timing.layerMs);
    if (!opt) throw new StepError('선택자없음', "글 유형 목록에서 '" + kind + "'을 찾지 못함 (selectors.textFormatOption)");
    clickEl(opt.el);
    await sleep(200);
    return '';
  }

  /** 본문 계열 블록: 빈 문단 → 글 유형 → 글 넣기 → 화면에서 확인 */
  async function putText(ctx, kind, text) {
    var doc = ctx.doc;
    await ensureEmptyParagraph(doc);
    await setTextFormat(doc, kind);
    var probe = norm(String(text).split('\n').filter(function (l) { return l.trim(); })[0] || '').slice(0, 30);
    var before = docText(doc);
    var methods = S.textMethods.body;
    for (var i = 0; i < methods.length; i++) {
      var how = insertTextOnce(doc, text, methods[i], true);
      var ok = await waitFor(function () { return norm(docText(doc)).indexOf(probe) >= 0 && docText(doc) !== before; }, S.timing.verifyMs * 2);
      if (ok) {
        var nonEmpty = String(text).split('\n').map(norm).filter(Boolean);
        var tailProbe = (nonEmpty[nonEmpty.length - 1] || '').slice(0, 30);
        if (!atDocumentEnd(doc, function (c) { return textOf(c).indexOf(tailProbe) >= 0; })) {
          throw new StepError('확인필요', kind + '이(가) 문서 끝이 아닌 곳에 들어감(커서 위치) — 화면을 확인하세요');
        }
        var lines = String(text).split('\n').map(norm).filter(Boolean);
        var now = norm(docText(doc));
        var missing = lines.filter(function (l) { return now.indexOf(l) < 0; });
        ctx.log(kind + ' 넣음 — 방법 ' + methods[i] + '(' + how + ')');
        return missing.length ? ['일부 줄이 안 보임: ' + missing.slice(0, 3).join(' / ')] : [];
      }
      if (docText(doc) !== before) {
        throw new StepError('확인필요', '글이 다르게 들어갔을 수 있음(방법 ' + methods[i] + ') — 화면을 확인하세요');
      }
      ctx.log('방법 ' + methods[i] + ' 은 반응 없음');
    }
    throw new StepError('확인필요', kind + '을(를) 넣지 못함(방법: ' + methods.join(', ') + ') — selectors.textMethods 실측 필요');
  }

  async function stepTitle(ctx) {
    var doc = ctx.doc;
    var want = norm(ctx.job['글']['제목']);
    if (!want) return { 상태: '건너뜀', 메시지: '제목이 비어 있음' };
    var el = titleEl(doc);
    if (!el) throw new StepError('선택자없음', '제목 칸을 찾지 못함 (selectors.title)');
    var have = titleText(doc);
    if (have === want) return { 상태: '완료', 메시지: '이미 같은 제목' };
    if (have) throw new StepError('에디터비어있지않음', "제목 칸에 이미 '" + have.slice(0, 30) + "'이(가) 있음");
    clickEl(el);
    await sleep(250);
    var methods = S.textMethods.title;
    for (var i = 0; i < methods.length; i++) {
      var how = insertTextOnce(doc, ctx.job['글']['제목'], methods[i], false);
      var got = await waitFor(function () { return titleText(doc); }, S.timing.verifyMs * 2);
      if (got === want) return { 상태: '완료', 메시지: '제목 넣음 — 방법 ' + methods[i] + '(' + how + ')' };
      if (got) throw new StepError('확인필요', "제목이 다르게 들어감: '" + got.slice(0, 40) + "'");
      ctx.log('제목: 방법 ' + methods[i] + ' 은 반응 없음');
    }
    throw new StepError('확인필요', '제목을 넣지 못함(방법: ' + methods.join(', ') + ')');
  }

  async function stepDivider(ctx) {
    var doc = ctx.doc;
    await focusTail(doc);
    var beforeSet = allOf(doc, S.dividerComponent);
    var before = beforeSet.length;
    var btn = visibleFirst(doc, S.dividerButton);
    if (!btn) throw new StepError('선택자없음', '구분선 버튼을 찾지 못함 (selectors.dividerButton)');
    clickEl(btn.el);
    var ok = await waitFor(function () { return allOf(doc, S.dividerComponent).length > before; }, S.timing.layerMs);
    if (!ok) throw new StepError('확인필요', '구분선이 생겼는지 확인 못 함 (selectors.dividerComponent)');
    var mine = allOf(doc, S.dividerComponent).filter(function (n) { return beforeSet.indexOf(n) < 0; });
    if (!atDocumentEnd(doc, function (c) { return mine.some(function (m) { return c === m || c.contains(m); }); })) {
      throw new StepError('확인필요', '구분선이 문서 끝이 아닌 곳에 들어감(커서 위치) — 화면을 확인하세요');
    }
    return { 상태: '완료', 메시지: '구분선 넣음' };
  }

  function layoutOptionFor(doc, way) {
    var names = (S.layoutText[way] || [way]).map(norm);
    var opts = allOf(doc, S.layoutOption);
    for (var i = 0; i < opts.length; i++) {
      if (names.indexOf(norm(opts[i].textContent)) >= 0) return opts[i];
    }
    return null;
  }

  async function stepPhoto(ctx, block) {
    var doc = ctx.doc;
    var bundle = (ctx.job['묶음'] || []).filter(function (b) { return b['번호'] === block['묶음']; })[0];
    if (!bundle || !(bundle['파일'] || []).length) {
      throw new StepError('사진없음', '이 사진 블록의 업로드 사본이 없음 — 발행 패키지를 다시 만드세요');
    }
    var files = await ctx.fetchFiles(bundle);
    await focusTail(doc);
    var beforeSet = allOf(doc, S.imageComponent);
    var before = beforeSet.length;
    var res = await insertFiles(files, { doc: doc, method: ctx.method || 'auto', onLog: ctx.log });
    var notes = (res['주의'] || []).slice();
    if (!res.ok) {
      var why = (res['시도'] || []).map(function (t) { return '(' + t['방법'] + ') ' + t['사유']; }).join(' / ');
      if (res['확인필요']) throw new StepError('확인필요', '사진 칸에 넣었지만 화면에 안 보임 — 네이버 화면을 확인하세요. ' + why);
      throw new StepError('선택자없음', '사진을 넣지 못함: ' + why + (bundle['폴더'] ? ' (사진 위치: ' + bundle['폴더'] + ')' : ''));
    }
    var way = bundle['방식'];
    if (files.length > 1) {
      var popup = await waitFor(function () { return visibleFirst(doc, S.layoutPopup); }, S.timing.layerMs);
      if (popup) {
        var opt = layoutOptionFor(doc, way);
        if (!opt) throw new StepError('선택자없음', "배치 선택 창에서 '" + way + "'을 찾지 못함 (selectors.layoutText)");
        clickEl(opt);
        await sleep(200);
        var confirm = visibleFirst(doc, S.layoutConfirm);
        if (confirm) clickEl(confirm.el);
        var shown = await waitFor(function () { return allOf(doc, S.imageComponent).length > before; }, S.timing.deliveredWaitMs);
        if (!shown) throw new StepError('확인필요', "'" + way + "'을 골랐지만 사진이 화면에 안 보임");
        ctx.log("배치 '" + way + "' 고름");
      } else {
        notes.push("배치 선택 창이 뜨지 않음 — 네이버가 정한 배치로 들어갔을 수 있음(원래 방식: " + way + ')');
      }
    }
    await waitFor(function () { return allOf(doc, S.imageComponent).length > before; }, S.timing.settleMs);
    var mine = allOf(doc, S.imageComponent).filter(function (n) { return beforeSet.indexOf(n) < 0; });
    if (mine.length && !atDocumentEnd(doc, function (c) { return mine.some(function (m) { return c === m || c.contains(m); }); })) {
      throw new StepError('확인필요', '사진이 문서 끝이 아닌 곳에 들어감(커서 위치) — 화면을 확인하세요');
    }
    var comp = mine[mine.length - 1];
    if (block['설명'] && comp) {
      clickEl(comp);
      await sleep(200);
      var cap = await waitFor(function () { return visibleFirst(comp, S.imageCaption); }, 2000);
      var capOk = false;
      // 2026-10-08 실측: 설명이 안 들어감(원인 미확정). 에디터가 문단을 다시 그리면 처음 잡은 요소는 떨어져 나가므로
      // 확인할 때마다 설명 칸을 다시 찾고, 방법별 결과·다른 곳에 들어갔는지를 기록(다음 실측 때 진단과 함께 봄)
      var want = norm(block['설명']).slice(0, 20);
      var capText = function () { var c = first(comp, S.imageCaption); return c ? textOf(c.el) : ''; };
      if (cap) {
        clickEl(cap.el);
        await sleep(200);
        for (var i = 0; i < S.textMethods.title.length && !capOk; i++) {
          var bodyBefore = docText(doc);
          var how = insertTextOnce(doc, block['설명'], S.textMethods.title[i], false);
          capOk = !!(await waitFor(function () { return capText().indexOf(want) >= 0; }, S.timing.verifyMs));
          var strayed = !capOk && norm(docText(doc)).indexOf(want) >= 0 && docText(doc) !== bodyBefore;
          ctx.log('사진 설명 — 방법 ' + S.textMethods.title[i] + '(' + how + '): ' + (capOk ? '들어감' : strayed ? '설명 칸이 아닌 곳에 들어감' : '반응 없음'));
          if (strayed) throw new StepError('확인필요', '사진 설명이 설명 칸이 아닌 곳에 들어감 — 화면에서 지운 뒤 [이 단계는 내가 했음 → 다음]');
        }
      } else {
        ctx.log('사진을 눌렀지만 설명 칸이 보이지 않음 (selectors.imageCaption)');
      }
      if (!capOk) notes.push('사진 설명을 넣지 못함 — 사람이 넣기: “' + block['설명'] + '”');
    }
    if (block['대표'] && comp) {
      clickEl(comp);
      await sleep(200);
      var rep = visibleFirst(doc, S.imageRepresentative);
      var pressed = rep && (rep.el.getAttribute('aria-pressed') === 'true' || /(^|\s|-)(on|selected|active)(\s|$)/.test(rep.el.className));
      if (rep && pressed) ctx.log('대표 사진: 이미 지정됨');
      else if (rep) { clickEl(rep.el); ctx.log('대표 사진 지정'); } else notes.push("대표 사진 지정 버튼을 찾지 못함 — 사람이 '대표' 지정");
    }
    await focusTail(doc);
    return { 상태: notes.length ? '주의' : '완료', 메시지: '사진 ' + files.length + '장(' + way + ') — 방법 (' + res['방법'] + ')', 주의: notes };
  }

  function placeName(item) {
    var n = first(item, S.place.resultName);
    return norm((n ? n.el : item).textContent).split(' · ')[0];
  }

  async function stepPlace(ctx, block) {
    var doc = ctx.doc;
    var names = (block['장소'] || []).map(norm).filter(Boolean);
    var notes = [];
    if (!names.length) return { 상태: '건너뜀', 메시지: '장소 이름이 없음' };
    if (names.length > 5) { notes.push('5곳이 넘어 앞 5곳만 넣음'); names = names.slice(0, 5); }
    await focusTail(doc);
    var beforeSet = allOf(doc, S.place.component);
    var before = beforeSet.length;
    var btn = visibleFirst(doc, S.place.button);
    if (!btn) throw new StepError('선택자없음', '장소 버튼을 찾지 못함 (selectors.place.button)');
    clickEl(btn.el);
    var popup = await waitFor(function () { return visibleFirst(doc, S.place.popup); }, S.timing.layerMs);
    if (!popup) throw new StepError('선택자없음', '장소 창이 열리지 않음 (selectors.place.popup)');
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      var input = await waitFor(function () { return visibleFirst(popup.el, S.place.input); }, S.timing.layerMs);
      if (!input) throw new StepError('선택자없음', '장소 검색칸을 찾지 못함');
      var oldItems = allOf(popup.el, S.place.resultItem);
      ctx.log('장소 검색칸 입력 — 방법 ' + typeIntoInput(input.el, name));
      await sleep(300);
      var freshItems = function () {
        var it = allOf(popup.el, S.place.resultItem);
        var fresh = it.filter(function (n) { return oldItems.indexOf(n) < 0; });
        return fresh.length ? fresh : null;
      };
      // 2026-10-08 실측: 글자가 들어가도 검색 버튼 클릭이 가끔 무시됨(창이 막 열렸을 때 등) → 클릭·Enter 를 번갈아 재시도
      var tries = S.place.searchTries || ['click', 'enter'];
      var items = null;
      for (var t = 0; t < tries.length && !items; t++) {
        var search = visibleFirst(popup.el, S.place.search);
        if (tries[t] === 'click' && search) clickEl(search.el); else pressKey(input.el, 'Enter');
        items = await waitFor(freshItems, S.timing.placeSearchMs || 4000);
        if (!items && t + 1 < tries.length) ctx.log("장소 '" + name + "' 검색 결과가 아직 없음 — 다시 검색(" + tries[t + 1] + ')');
      }
      if (!items) throw new StepError('장소없음', "'" + name + "' 검색 결과가 없음 — 장소 창이 열려 있음(사람이 고르거나 닫기)");
      var match = items.filter(function (it) { return placeName(it) === name; })[0];
      if (!match) {
        throw new StepError('장소없음', "'" + name + "'과 이름이 정확히 같은 결과가 없음. 후보: " +
          items.slice(0, 5).map(placeName).join(', ') + ' — 장소 창이 열려 있음');
      }
      ['mouseover', 'mouseenter', 'mousemove'].forEach(function (t) {
        match.dispatchEvent(new (doc.defaultView.MouseEvent)(t, { bubbles: t !== 'mouseenter' }));
      });
      await sleep(200);
      var add = first(match, S.place.add);
      if (!add) throw new StepError('선택자없음', "'추가' 버튼을 찾지 못함 (selectors.place.add)");
      add.el.click();
      await sleep(400);
      ctx.log("장소 '" + name + "' 추가");
    }
    var confirm = visibleFirst(popup.el, S.place.confirm) || visibleFirst(doc, S.place.confirm);
    if (!confirm || confirm.el.disabled) throw new StepError('확인필요', '장소 확인 버튼이 꺼져 있음 — 장소가 선택되지 않았을 수 있음');
    clickEl(confirm.el);
    var ok = await waitFor(function () { return allOf(doc, S.place.component).length > before; }, S.timing.layerMs);
    if (!ok) throw new StepError('확인필요', '장소 지도가 본문에 생겼는지 확인 못 함');
    var minePlace = allOf(doc, S.place.component).filter(function (n) { return beforeSet.indexOf(n) < 0; });
    if (!atDocumentEnd(doc, function (c) { return minePlace.some(function (m) { return c === m || c.contains(m); }); })) {
      throw new StepError('확인필요', '장소가 문서 끝이 아닌 곳에 들어감(커서 위치) — 화면을 확인하세요');
    }
    await focusTail(doc);
    return { 상태: notes.length ? '주의' : '완료', 메시지: '장소 ' + names.length + '곳: ' + names.join(', '), 주의: notes };
  }

  // ── 동영상 ─────────────────────────────────────────────────────────────
  /**
   * 동영상 업로드 칸(file input) 구하기: '동영상' 버튼 → (바로 파일 선택 창 | 업로드 창 → '동영상 추가').
   * 파일 선택 창은 page-hook.js 가 가로채 열지 않음(사진과 같은 갈고리). 결과: {input, disarm}
   */
  async function obtainVideoInput(doc, log) {
    var html = doc.documentElement;
    var win = doc.defaultView;
    var guardState = { el: null };
    var guard = function (e) {
      if (isFileInput(e.target) && !isOurs(e.target)) { e.preventDefault(); guardState.el = e.target; }
    };
    var disarm = function () { html.removeAttribute(ARM_ATTR); win.removeEventListener('click', guard, true); };
    var nonce = armHook(doc, S.timing.layerMs + S.timing.inputWaitMs * 2 + 5000);
    win.addEventListener('click', guard, true);
    try {
      var seqBefore = maxCapturedSeq(doc);
      var beforeInputs = new Set(Array.prototype.slice.call(doc.querySelectorAll('input[type="file"]')));
      var findNew = function () {
        var cap = latestCaptured(doc, seqBefore, nonce);
        if (cap) return cap;
        if (guardState.el) return guardState.el;
        return allOf(doc, S.video.fileInput).filter(function (n) { return !beforeInputs.has(n); })[0] || null;
      };
      var btn = visibleFirst(doc, S.video.button);
      if (!btn) throw new StepError('선택자없음', "'동영상' 버튼을 찾지 못함 (selectors.video.button)");
      log("'동영상' 버튼을 누름 — 파일 선택 창은 가로채서 열지 않음");
      clickEl(btn.el);
      var got = await waitFor(function () { return findNew() || visibleFirst(doc, S.video.popup); }, S.timing.layerMs);
      if (!got) throw new StepError('선택자없음', "'동영상'을 눌렀지만 업로드 창·파일 칸이 나타나지 않음 (selectors.video.popup)");
      var input = got.tagName ? got : findNew();
      if (!input) {
        // 2026-10-08 실측: 창 틀(se-popup-video-upload)이 먼저 뜨고 업로더(nvu_) 내용은 조금 늦게 그려짐 → 버튼을 기다림
        var add = await waitFor(function () { return visibleFirst(got.el, S.video.addButton); }, S.timing.layerMs);
        if (!add) throw new StepError('선택자없음', "동영상 업로드 창에서 '동영상 추가' 버튼을 찾지 못함 (selectors.video.addButton)");
        log("업로드 창의 '동영상 추가'를 누름");
        clickEl(add.el);
        input = await waitFor(findNew, S.timing.inputWaitMs);
        if (!input) {
          var inside = first(got.el, ['input[type="file"]']);
          input = inside && inside.el;
        }
      }
      if (!input) throw new StepError('선택자없음', '동영상 업로드 칸(file input)을 찾지 못함 (selectors.video.fileInput)');
      return { input: input, disarm: function () { disarm(); cleanupCaptured(input); } };
    } catch (err) {
      disarm();
      throw err;
    }
  }

  /**
   * 동영상 하나의 제목(네이버 업로더에서 필수, 최대 40자).
   * 블록 '제목'이 목록이면 순서대로, 글자 하나면 여러 개일 때 뒤에 번호(" 1", " 2"), 없으면 글 제목.
   */
  function videoTitle(block, postTitle, index, total) {
    var max = S.video.titleMax || 40;
    var t = block['제목'];
    if (Array.isArray(t)) return norm(t[index] || t[t.length - 1] || postTitle || '동영상').slice(0, max) || '동영상';
    var base = norm(t || postTitle || '동영상');
    var suffix = total > 1 ? ' ' + (index + 1) : '';
    return base.slice(0, max - suffix.length) + suffix;
  }

  /**
   * 동영상 블록: 내 PC 서버의 동영상 사본을 큰 파일 통로(ctx.fetchVideo)로 받아 '동영상' 업로드로 넣고,
   * 네이버 처리(업로드·인코딩)가 끝날 때까지 기다림(그동안 서버에 '처리중' 신호). 1회 최대 10개씩.
   */
  async function stepVideo(ctx, block) {
    var doc = ctx.doc;
    var bundle = (ctx.job['묶음'] || []).filter(function (b) { return b['번호'] === block['묶음']; })[0];
    if (!bundle || !(bundle['파일'] || []).length) {
      return { 상태: '주의', 메시지: '동영상 사본 없음', 주의: ["이 동영상 블록은 업로드 사본이 없어 넣지 않음 — 사람이 '동영상' 버튼으로 넣기"] };
    }
    if (!ctx.fetchVideo) throw new StepError('설정오류', '동영상을 받을 통로가 없음');
    var notes = (bundle['경고'] || []).slice();
    var all = bundle['파일'];
    var total = 0;
    for (var g = 0; g < all.length; g += 10) {
      var infos = all.slice(g, g + 10);
      var bytes = infos.reduce(function (s, f) { return s + (Number(f['크기']) || 0); }, 0);
      await ctx.beat('동영상 ' + infos.length + '개(' + formatBytes(bytes) + ')를 내 PC 서버에서 받는 중');
      var files = await ctx.fetchVideo(infos);
      assertLive();
      await focusTail(doc);
      var beforeSet = allOf(doc, S.video.component);
      var got = await obtainVideoInput(doc, ctx.log);
      try {
        got.input.files = makeDataTransfer(files).files;
      } catch (err) {
        got.disarm();
        throw new StepError('선택자없음', '동영상 칸에 파일을 넣지 못함: ' + err.message);
      }
      got.input.dispatchEvent(new Event('input', { bubbles: true }));
      got.input.dispatchEvent(new Event('change', { bubbles: true }));
      setTimeout(got.disarm, S.timing.inputWaitMs);
      ctx.log('동영상 ' + files.length + '개를 업로드 칸에 넣음(' + formatBytes(bytes) + ') — 네이버 처리 기다림');
      // 업로드·처리(인코딩) 기다리기 [미실측: 표시 이름]
      var started = Date.now();
      var lastBeat = Date.now();
      var outcome = null;
      while (!outcome) {
        assertLive();
        var bad = visibleFirst(doc, S.video.error);
        if (bad) {
          var badItem = bad.el.closest('li') || bad.el;
          // 파일 이름·상태 글자만(숨김 글자 '로딩중'·'주의'·'삭제'는 빼고)
          var badText = (S.video.itemText || []).map(function (q) { return badItem.querySelector(q); }).filter(Boolean)
            .map(function (n) { return norm(n.textContent); }).join(' ') || norm(badItem.textContent);
          throw new StepError('확인필요', '네이버가 동영상 처리 중 문제를 표시함: “' + badText.slice(0, 60) + '” — 화면을 확인하세요');
        }
        var busy = visibleFirst(doc, S.video.processing);
        // 업로더 목록에 이번 파일이 다 올라온 뒤에만 '끝남'으로 봄(넣은 직후 목록이 그려지기 전과 구별)
        var listed = (S.video.fileItem || []).length ? allOf(doc, S.video.fileItem).length >= files.length : true;
        var info = busy || !listed ? null : visibleFirst(doc, S.video.infoForm);
        var added = allOf(doc, S.video.component).filter(function (n) { return beforeSet.indexOf(n) < 0; });
        if (info) outcome = { info: info };
        else if (!busy && added.length >= files.length) outcome = { added: added };
        else if (Date.now() - started > S.timing.videoWaitMs) {
          throw new StepError('시간초과', '동영상 업로드·처리가 ' + Math.round(S.timing.videoWaitMs / 60000) + '분 안에 끝나지 않음 — 네이버 화면을 확인하세요');
        }
        if (!outcome && Date.now() - lastBeat >= S.timing.beatMs) {
          lastBeat = Date.now();
          var what = busy ? norm(busy.el.textContent).slice(0, 40) : '기다리는 중';
          if (ctx.status) ctx.status('네이버 동영상 처리 중(' + Math.round((Date.now() - started) / 60000) + '분): ' + what);
          await ctx.beat('동영상 처리 중 ' + Math.round((Date.now() - started) / 60000) + '분: ' + what);
        }
        if (!outcome) await sleep(500);
      }
      if (outcome.info) {
        // 제목·정보 칸(2026-10-08 실측: 업로더 안, 제목 필수) — 파일마다 목록에서 골라 넣고, 이름이 정확히 '완료' 등인 버튼만 누름
        var form = outcome.info.el;
        var rounds = Math.max(1, Math.min(allOf(doc, S.video.fileSelect || []).length, files.length));
        for (var k = 0; k < rounds; k++) {
          var selects = allOf(doc, S.video.fileSelect || []);   // 고를 때마다 목록이 다시 그려질 수 있어 매번 다시 찾음
          if (selects.length > 1 && selects[k]) { clickEl(selects[k]); await sleep(400); }
          var vt = videoTitle(block, ctx.job['글']['제목'], g + k, all.length);
          var ti = visibleFirst(doc, S.video.titleInput);
          if (ti && vt) typeIntoInput(ti.el, vt);
          else if (!ti) notes.push('동영상 제목 칸을 찾지 못함 — 사람이 넣기: “' + vt + '”');
          else notes.push('동영상 ' + (g + k + 1) + '의 제목이 비어 있음(네이버 필수) — 사람이 넣기');
          if (block['설명']) {
            var di = visibleFirst(doc, S.video.descInput);
            var desc = String(block['설명']).slice(0, S.video.descMax || 300);
            if (di) typeIntoInput(di.el, desc); else notes.push('동영상 정보 칸을 찾지 못함 — 사람이 넣기: “' + desc + '”');
          }
        }
        var wrap = form.closest('#video-uploader-wrap') || form;
        var isDone = function (b) { return isVisible(b) && (S.video.doneText || []).indexOf(norm(b.textContent)) >= 0; };
        // 정해진 '완료' 버튼(nvu_btn_submit)을 먼저, 없을 때만 글자가 정확히 같은 버튼(앞쪽 알림 창 버튼이 먼저 잡히지 않게)
        var doneBtn = allOf(wrap, S.video.done).filter(isDone)[0] || allOf(wrap, ['button']).filter(isDone)[0];
        if (!doneBtn) throw new StepError('선택자없음', "동영상 정보 창의 '완료' 버튼을 찾지 못함 — 사람이 마무리한 뒤 [이 단계는 내가 했음]");
        clickEl(doneBtn);
        var added2 = await waitFor(function () {
          var a = allOf(doc, S.video.component).filter(function (n) { return beforeSet.indexOf(n) < 0; });
          return a.length >= files.length ? a : null;
        }, S.timing.layerMs * 2);
        if (!added2) throw new StepError('확인필요', "동영상 정보 창에서 '" + norm(doneBtn.textContent) + "'을 눌렀지만 본문에 동영상이 안 보임");
        outcome.added = added2;
      }
      var mine = outcome.added;
      if (!atDocumentEnd(doc, function (c) { return mine.some(function (m) { return c === m || c.contains(m); }); })) {
        throw new StepError('확인필요', '동영상이 문서 끝이 아닌 곳에 들어감(커서 위치) — 화면을 확인하세요');
      }
      total += files.length;
      await focusTail(doc);
    }
    return { 상태: notes.length ? '주의' : '완료', 메시지: '동영상 ' + total + '개 올림', 주의: notes };
  }

  async function stepBlock(ctx, block) {
    var kind = block['종류'];
    if (kind === '본문') return { 상태: '완료', 메시지: '본문', 주의: await putText(ctx, '본문', block['글'] || '') };
    if (kind === '소제목') return { 상태: '완료', 메시지: '소제목', 주의: await putText(ctx, '소제목', block['글'] || '') };
    if (kind === '인용구') {
      var q = (block['글'] || '') + (block['출처'] ? '\n— ' + block['출처'] : '');
      return { 상태: '완료', 메시지: '인용구', 주의: await putText(ctx, '인용구', q) };
    }
    if (kind === '꿀팁') return { 상태: '완료', 메시지: '꿀팁(인용구로)', 주의: await putText(ctx, '인용구', '꿀팁: ' + (block['글'] || '')) };
    if (kind === '참고자료') {
      var list = (block['목록'] || []).map(function (x) { return '- ' + x; });
      return { 상태: '완료', 메시지: '참고자료', 주의: await putText(ctx, '본문', ['참고자료'].concat(list).join('\n')) };
    }
    if (kind === '구분선') return stepDivider(ctx);
    if (kind === '사진' || kind === '그룹사진' || kind === '지도') return stepPhoto(ctx, block);
    if (kind === '장소') return stepPlace(ctx, block);
    if (kind === '영상') return stepVideo(ctx, block);
    return { 상태: '주의', 메시지: '모르는 블록', 주의: ["모르는 블록 종류 '" + kind + "' — 넣지 않음"] };
  }

  // 발행 설정 레이어
  async function openLayer(doc) {
    if (visibleFirst(doc, S.publishLayer)) return;
    var btn = visibleFirst(doc, S.publishOpen);
    if (!btn) throw new StepError('선택자없음', '발행 설정을 여는 버튼을 찾지 못함 (selectors.publishOpen)');
    clickEl(btn.el);
    var ok = await waitFor(function () { return visibleFirst(doc, S.publishLayer); }, S.timing.layerMs);
    if (!ok) throw new StepError('확인필요', '발행 설정 창이 열리지 않음 — 혹시 바로 발행됐는지 네이버 화면을 꼭 확인하세요');
  }

  async function closeLayer(doc) {
    if (!visibleFirst(doc, S.publishLayer)) return true;
    var c = visibleFirst(doc, S.publishLayerClose);
    if (c) clickEl(c.el); else pressKey(doc.activeElement || doc.body, 'Escape');
    return !!(await waitFor(function () { return !visibleFirst(doc, S.publishLayer); }, 2500));
  }

  function chipTexts(doc) {
    return allOf(doc, S.tagChip).map(function (n) { return norm(n.textContent).replace(/^#/, ''); }).filter(Boolean);
  }

  async function stepTags(ctx) {
    var doc = ctx.doc;
    var tags = (ctx.job['글']['태그'] || []).map(function (t) { return norm(t).replace(/^#/, ''); }).filter(Boolean);
    if (!tags.length) return { 상태: '건너뜀', 메시지: '태그 없음' };
    await openLayer(doc);
    var input = await waitFor(function () { return visibleFirst(doc, S.tagInput); }, S.timing.layerMs);
    if (!input) throw new StepError('선택자없음', '태그 입력칸을 찾지 못함 (selectors.tagInput)');
    var have = chipTexts(doc);
    for (var i = 0; i < tags.length; i++) {
      if (have.indexOf(tags[i]) >= 0) continue;
      typeIntoInput(input.el, tags[i]);
      pressKey(input.el, 'Enter');
      await sleep(250);
    }
    var after = chipTexts(doc);
    if (!after.length && !allOf(doc, S.tagChip).length) {
      return { 상태: '주의', 메시지: '태그 ' + tags.length + '개 입력', 주의: ['태그가 들어갔는지 확인 못 함(selectors.tagChip 실측 필요)'] };
    }
    var missing = tags.filter(function (t) { return after.indexOf(t) < 0; });
    if (missing.length) throw new StepError('확인필요', '태그 일부가 안 들어감: ' + missing.join(', '));
    return { 상태: '완료', 메시지: '태그 ' + tags.length + '개' };
  }

  function cleanCategory(text) {
    return norm(String(text).replace(S.categoryChildMark, ''));
  }

  async function stepCategory(ctx) {
    var doc = ctx.doc;
    var name = norm(ctx.job['글']['카테고리']);
    if (!name) return { 상태: '주의', 메시지: '카테고리 없음', 주의: ['패키지에 카테고리가 없어 블로그 기본 카테고리로 둠'] };
    await openLayer(doc);
    var btn = await waitFor(function () { return visibleFirst(doc, S.categoryOpen); }, S.timing.layerMs);
    if (!btn) throw new StepError('선택자없음', '카테고리 버튼을 찾지 못함 (selectors.categoryOpen)');
    if (cleanCategory(btn.el.textContent) === name) return { 상태: '완료', 메시지: "이미 '" + name + "'" };
    clickEl(btn.el);
    var items = await waitFor(function () { var a = allOf(doc, S.categoryItem); return a.length ? a : null; }, S.timing.layerMs);
    if (!items) throw new StepError('선택자없음', '카테고리 목록이 열리지 않음 (selectors.categoryItem)');
    var names = items.map(function (n) { return cleanCategory(n.textContent); });
    var idx = names.indexOf(name);
    if (idx < 0) {
      clickEl(btn.el); // 목록 닫기
      throw new StepError('카테고리없음', "'" + name + "' 카테고리가 없음(이름이 정확히 같아야 함). 있는 것: " + names.join(', '));
    }
    // 2026-10-08 실측: 줄(li)을 누르면 안 바뀜 — 안의 라디오(input)·라벨이 받음. 라디오는 .click()(브라우저가 change 를 만듦)
    var item = items[idx];
    var ctl = (S.categoryItemControl || []).map(function (s) { return item.querySelector(s); }).filter(Boolean)[0];
    if (ctl && ctl.tagName === 'INPUT') ctl.click(); else clickEl(ctl || item);
    var ok = await waitFor(function () { return cleanCategory(btn.el.textContent) === name; }, 2500);
    if (!ok) throw new StepError('확인필요', "카테고리를 '" + name + "'으로 바꿨는지 확인 못 함");
    return { 상태: '완료', 메시지: "카테고리 '" + name + "'" };
  }

  async function stepVisibility(ctx) {
    var doc = ctx.doc;
    var v = ctx.job['글']['공개'];
    if (!v) return { 상태: '주의', 메시지: '공개 값 없음', 주의: ['패키지에 공개 값이 없어 네이버 기본값 그대로 — 발행 전에 사람이 확인'] };
    await openLayer(doc);
    var input = first(doc, S.visibility[v]);
    if (!input) throw new StepError('선택자없음', "공개 설정 '" + v + "'을 찾지 못함 (selectors.visibility)");
    if (!input.el.checked) input.el.click();
    var ok = await waitFor(function () { return input.el.checked; }, 2000);
    if (!ok) throw new StepError('확인필요', "공개 설정을 '" + v + "'으로 바꿨는지 확인 못 함");
    return { 상태: '완료', 메시지: "공개 설정 '" + v + "'" };
  }

  /**
   * 'AI 활용 설정' — 2026-10-08 실측: 글 전체 설정은 없고 사진·콜라주·동영상 덩어리마다 스위치가 있음
   * (사진을 선택하면 사진 위 div.se-set-ai-mark-button, 켜짐 = button.se-set-ai-mark-button-toggle.se-is-selected,
   *  동영상은 업로더 안에도 영상별 스위치). 어떤 사진이 AI로 만든 것인지는 사람이 가장 잘 알므로
   * 확장은 스위치를 건드리지 않고, AI활용표시가 true 인 글에서 사람이 켜도록 '주의'로 안내만 함(강사 결정 2026-10-08).
   */
  async function stepAi(ctx) {
    var flag = ctx.job['글']['AI활용표시'];
    if (flag === false) return { 상태: '건너뜀', 메시지: '패키지의 AI활용표시가 false' };
    if (flag == null) return { 상태: '주의', 메시지: 'AI활용표시 값 없음', 주의: ["패키지에 AI활용표시 값이 없음 — AI로 만든 사진·영상이 있으면 사람이 사진·영상마다 'AI 활용 설정'을 켜기"] };
    return { 상태: '주의', 메시지: "'AI 활용 설정'은 사람이",
      주의: ["AI로 만들거나 바꾼 사진·영상을 하나씩 클릭해 사진 위 'AI 활용 설정' 스위치를 켜기(확장은 건드리지 않음)"] };
  }

  function readSaveCount(doc) {
    var f = first(doc, S.saveCount);
    if (!f) return null;
    var m = String(f.el.getAttribute('aria-label') || f.el.textContent || '').match(/(\d+)\s*개?\s*$/) ||
      String(f.el.textContent || '').match(/(\d+)/);
    return m ? Number(m[1]) : null;
  }

  function toastSaying(doc, word) {
    return allOf(doc, S.saveToast).some(function (n) { return isVisible(n) && norm(n.textContent).indexOf(word) >= 0; });
  }

  async function stepSave(ctx) {
    var doc = ctx.doc;
    var notes = [];
    if (!(await closeLayer(doc))) notes.push('발행 설정 창을 닫지 못해 열린 채로 저장함');
    var before = readSaveCount(doc);
    var btn = visibleFirst(doc, S.saveButton);
    if (!btn) throw new StepError('선택자없음', "'저장' 버튼을 찾지 못함 (selectors.saveButton)");
    var hadToast = toastSaying(doc, '저장');
    clickEl(btn.el);
    var ok = await waitFor(function () {
      var now = readSaveCount(doc);
      if (before != null) return now != null && now > before;
      return !hadToast && toastSaying(doc, '임시저장');
    }, 10000, 250);
    if (!ok) throw new StepError('확인필요', "임시저장이 됐는지 확인 못 함 — 네이버 화면의 '저장' 옆 숫자를 확인하세요");
    return { 상태: notes.length ? '주의' : '완료', 메시지: '임시저장' + (before != null ? '(저장 글 ' + before + '→' + readSaveCount(doc) + '개)' : ''), 주의: notes };
  }

  function kstParts(isoText) {
    var t = new Date(isoText);
    if (isNaN(t)) return null;
    var k = new Date(t.getTime() + 9 * 3600 * 1000);
    var p = function (n) { return String(n).padStart(2, '0'); };
    return { y: k.getUTCFullYear(), mo: p(k.getUTCMonth() + 1), d: p(k.getUTCDate()), h: p(k.getUTCHours()), mi: p(k.getUTCMinutes()) };
  }

  function reserveAllowed(job) {
    var r = job['예약'] || {};
    // 2026-10-08 실측: 'AI 활용 설정'은 사람이 사진·영상마다 켬 → AI활용표시가 false 가 아닌 글은 예약 발행 안 함(서버 reserve_check 와 이중)
    return job['모드'] === '예약발행' && r['허용'] === true && r['자동예약발행'] === true &&
      job['글'] && job['글']['승인'] === '승인됨' && job['글']['AI활용표시'] === false && !!r['시각'];
  }

  async function stepReserve(ctx) {
    var doc = ctx.doc;
    var job = ctx.job;
    if (!reserveAllowed(job)) throw new StepError('예약불가', '예약 조건(모드·승인·자동예약발행 설정·AI활용표시 false)이 맞지 않아 발행하지 않음');
    var k = kstParts(job['예약']['시각']);
    if (!k) throw new StepError('예약불가', '예약시각을 읽지 못함');
    await openLayer(doc);
    var radio = first(doc, S.reserve.radio);
    if (!radio) {
      var lab = allOf(doc, [S.publishLayer[0] + ' label']).filter(function (n) { return norm(n.textContent) === S.reserve.radioText; })[0];
      radio = lab ? { el: lab.control || lab } : null;
    }
    if (!radio) throw new StepError('선택자없음', "발행 시간 '예약'을 찾지 못함 (selectors.reserve.radio)");
    if (!radio.el.checked) radio.el.click();
    var dateIn = await waitFor(function () { return visibleFirst(doc, S.reserve.date); }, S.timing.layerMs);
    var hourSel = visibleFirst(doc, S.reserve.hour);
    var minSel = visibleFirst(doc, S.reserve.minute);
    if (!dateIn || !hourSel || !minSel) throw new StepError('선택자없음', '예약 날짜·시·분 칸을 찾지 못함 (selectors.reserve) — 발행하지 않음');
    var dateText = S.reserve.dateFormat.replace('YYYY', k.y).replace('MM', k.mo).replace('DD', k.d);
    if (dateIn.el.type === 'date') dateText = k.y + '-' + k.mo + '-' + k.d;
    setInputValue(dateIn.el, dateText);
    setInputValue(hourSel.el, k.h);
    setInputValue(minSel.el, k.mi);
    await sleep(200);
    if (hourSel.el.value !== k.h || minSel.el.value !== k.mi || norm(dateIn.el.value) !== norm(dateText)) {
      throw new StepError('확인필요', '예약 시각이 그대로 들어가지 않음 — 발행하지 않음');
    }
    var confirm = visibleFirst(doc, S.publishConfirm);
    if (!confirm) throw new StepError('선택자없음', '발행 확인 버튼을 찾지 못함');
    var margin = ((job['설정'] || {})['예약최소여유분'] || 15) * 60 * 1000;
    if (new Date(job['예약']['시각']).getTime() - Date.now() < margin) {
      throw new StepError('예약불가', '예약 시각까지 여유가 너무 적음(채우는 데 오래 걸림) — 발행하지 않음. 시각을 바꿔 새 작업으로');
    }
    var reservedBefore = allOf(doc, S.reserve.done).filter(function (n) { return isVisible(n) && /예약/.test(n.textContent); }).map(function (n) { return n.textContent; }).join('|');
    if (ctx.mark) await ctx.mark('예약발행', '확인누름');  // 뒤에서 보고가 끊겨도 같은 글을 두 번 예약하지 않게
    // 여기부터는 확인 버튼이 눌렸을 수 있음 → 어떤 이유로 멈추든 '사람이 네이버 예약 목록을 확인'하라고 알림
    var ok = false;
    try {
      guard.allowUntil = Date.now() + 1500;
      try { clickEl(confirm.el); } finally { guard.allowUntil = 0; }
      ok = await waitFor(function () {
        var now = allOf(doc, S.reserve.done).filter(function (n) { return isVisible(n) && /예약/.test(n.textContent); }).map(function (n) { return n.textContent; }).join('|');
        return now && now !== reservedBefore;
      }, 10000, 250);
    } catch (err) {
      var why = err instanceof StepError ? err.message : String(err && err.message || err);
      throw new StepError('확인필요', '발행 확인 버튼을 누르는 중(직전 또는 직후)에 멈춤: ' + why +
        ' — 버튼이 눌렸는지 확실하지 않습니다. 네이버의 예약 발행 목록을 사람이 꼭 확인하세요');
    }
    if (!ok) throw new StepError('확인필요', "예약 표시('예약 발행 n건')를 확인하지 못함 — 바로 발행됐을 수도 있으니 네이버 화면을 꼭 확인하세요");
    return { 상태: '완료', 메시지: '예약 발행 ' + k.y + '-' + k.mo + '-' + k.d + ' ' + k.h + ':' + k.mi + '(한국 시간)' };
  }

  function checkBarrier(doc) {
    if (first(doc, S.loginFrame)) throw new StepError('로그인필요', '네이버 로그인 화면이 보임 — 사람이 로그인한 뒤 다시');
    if (first(doc, S.captcha)) throw new StepError('보안확인', '자동입력 방지(캡차) 화면이 보임 — 사람이 처리한 뒤 다시');
    // 화면에 보이는 글자만(body.innerText 는 script·숨은 요소를 빼고 읽음).
    // 낱말이 나온 횟수를 셈: 화면 전체 - 우리 패널 - 글 내용(에디터 캔버스만, 툴바·팝업은 셈에 남김) > 0 이면 멈춤.
    // (글에 '보호조치' 같은 낱말이 있어도 멈추지 않고, 에디터 위에 뜬 보호조치 창은 잡음)
    var count = function (s, w) { return s ? String(s).split(w).length - 1 : 0; };
    var text = ((doc.body && doc.body.innerText) || '').slice(0, 200000);
    var mine = PANEL_UI && PANEL_UI.panel.ownerDocument === doc ? PANEL_UI.panel : null;
    var root = first(doc, S.editorRoot);
    var canvas = root && (root.el.closest('.se-canvas, .se-content') || root.el);
    var hit = (S.barrierText || []).filter(function (w) {
      return count(text, w) - count(mine && mine.innerText, w) - count(canvas && canvas.innerText, w) > 0;
    })[0];
    if (hit) throw new StepError('보안확인', "'" + hit + "' 문구가 보임(보호조치·확인 화면) — 사람이 처리한 뒤 다시");
  }

  async function stepPrepare(ctx) {
    var doc = ctx.doc;
    var notes = [];
    checkBarrier(doc);
    // 검수 M5: 서버가 위치·기기 정보·덧붙은 데이터가 남아 내주지 않은 사진·영상이 있으면 아무것도 넣지 않고 멈춤
    var refused = [];
    (ctx.job['묶음'] || []).forEach(function (b) { (b['거절'] || []).forEach(function (x) { refused.push(x['이름'] + '(' + (x['이유'] || []).join('·') + ')'); }); });
    if (refused.length) {
      throw new StepError('개인정보', '업로드 사본에 남으면 안 되는 정보가 있어 서버가 내주지 않은 파일: ' + refused.join(', ') +
        ' — 업로드 사본을 다시 만든 뒤(메타 지우기) [이 단계부터 다시]');
    }
    var help = visibleFirst(doc, S.helpPanel);
    if (help) {
      var close = visibleFirst(doc, S.helpPanelClose);
      if (close) { clickEl(close.el); notes.push('도움말 패널을 닫음'); await sleep(300); }
    }
    var pop = visibleFirst(doc, S.blockingPopup);
    if (pop && !isOurs(pop.el)) {
      var box = pop.el.closest('.se-popup') || pop.el;
      var popTitle = (S.blockingPopupTitle || []).map(function (s) { return box.querySelector(s); }).filter(Boolean)[0];
      var label = norm((popTitle || box).textContent).slice(0, 40);
      // 2026-10-08 실측: 새로고침·로그인 뒤 '작성 중인 글이 있습니다.' 창이 자주 뜸 → 실패로 끝내지 않고 사람이 닫기를 기다림.
      //   [취소]로 에디터가 새로 그려지면 새 패널이 같은 작업을 '재개'로 받아 처음부터(빈 화면) 다시 시작함(handleResume)
      if ((S.restorePopupText || []).some(function (w) { return label.indexOf(w) >= 0; })) {
        if (ctx.status) ctx.status("네이버 '" + label + "' 창이 떠 있습니다. [취소]를 누르면 새 글로 이어서 채웁니다([확인]은 예전 글을 불러오므로 멈춤).");
        // 사람이 [확인](이어 쓰기)을 눌렀는지 직접 봄 — 예전 글이 늦게 불러와져 새 글과 섞이지 않게(사람 클릭만)
        var chose = { restore: false };
        var onPick = function (e) {
          if (!e.isTrusted || !e.target || !e.target.closest) return;
          var btn = e.target.closest('button');
          if (btn && btn.closest('.se-popup') && (S.restorePopupConfirm || []).some(function (q) { return btn.matches(q); })) chose.restore = true;
        };
        doc.addEventListener('click', onPick, true);
        var gone;
        try {
          gone = await waitFor(function () {
            var p = visibleFirst(doc, S.blockingPopup);
            return !p || isOurs(p.el) ? true : null;
          }, S.timing.restorePopupWaitMs || 60000);
        } finally {
          doc.removeEventListener('click', onPick, true);
        }
        if (!gone) throw new StepError('팝업', '에디터 위에 창이 떠 있음: “' + label + '” — 사람이 [취소]로 닫고 [이 단계부터 다시]');
        if (chose.restore) {
          throw new StepError('에디터비어있지않음', "'" + label + "' 창에서 [확인](이어 쓰기)을 골라 예전 글을 불러왔습니다 — 새 글로 하려면 새로고침 뒤 [취소]");
        }
        notes.push("'" + label + "' 창을 사람이 닫음([취소])");
        await sleep(1500);   // 불러오기가 늦게 끝나는 경우 대비 — 아래 빈 화면 검사로 한 번 더 막음
      } else {
        throw new StepError('팝업', '에디터 위에 창이 떠 있음: “' + label + '” — 사람이 닫고 [이 단계부터 다시]');
      }
    }
    if (!titleEl(doc)) throw new StepError('선택자없음', '제목 칸을 찾지 못함 (selectors.title)');
    if (ctx.resume) {
      if (titleText(doc) !== norm(ctx.job['글']['제목'])) {
        throw new StepError('앞단계없음', '앞 단계 내용(제목)이 화면에 없음 — 처음부터 다시 하세요');
      }
    } else if (titleText(doc) || !bodyIsEmpty(doc)) {
      throw new StepError('에디터비어있지않음', '에디터에 이미 내용이 있음(임시저장 글을 불러왔나요?) — 새 글쓰기 화면에서 다시 하세요');
    }
    return { 상태: notes.length ? '주의' : '완료', 메시지: '에디터 확인', 주의: notes };
  }

  // 발행 확인 버튼 안전장치: 작업 중에는 막고, 예약발행 단계의 그 순간에만 풀어 줌
  var guard = { armed: false, allowUntil: 0 };
  function confirmGuard(e) {
    if (!guard.armed || !e.target || !e.target.closest) return;
    if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
    var hit = e.target.closest(S.publishConfirm.join(','));
    if (hit && Date.now() > guard.allowUntil) {
      e.preventDefault();
      e.stopImmediatePropagation();
      console.warn('[블로그 도우미] 작업 중에는 발행 확인 버튼을 누를 수 없게 막았습니다.');
    }
  }
  function armGuard(doc, on) {
    guard.armed = on;
    var win = doc.defaultView;
    if (on && !win.__blogHelperGuard) {
      ['click', 'mousedown', 'pointerdown', 'mouseup', 'pointerup', 'keydown'].forEach(function (t) { win.addEventListener(t, confirmGuard, true); });
      win.__blogHelperGuard = true;
    }
  }

  function stepRunner(name, block) {
    if (name === '준비') return stepPrepare;
    if (name === '제목') return stepTitle;
    if (name === '태그') return stepTags;
    if (name === '카테고리') return stepCategory;
    if (name === '공개설정') return stepVisibility;
    if (name === 'AI활용') return stepAi;
    if (name === '저장') return stepSave;
    if (name === '예약발행') return stepReserve;
    if (block) return function (ctx) { return stepBlock(ctx, block); };
    return null;
  }

  /**
   * 작업 하나를 단계별로 실행. opts: {doc, transport, onStep(name,state,msg), log, method,
   * shouldStop(), humanFirst(첫 단계를 '사람'으로 처리)}. 결과: {ok, 실패단계, 코드, 메시지}
   */
  async function runJob(job, opts) {
    var doc = opts.doc || document;
    var steps = job['단계목록'] || [];
    var start = job['시작단계'] && steps.indexOf(job['시작단계']) > 0 ? steps.indexOf(job['시작단계']) : 0;
    var humanFirst = !!(opts.humanFirst || job['시작단계사람']);
    var blocks = {};
    (job['글']['블록'] || []).forEach(function (b) { blocks['블록 ' + b['번호']] = b; });
    var ctx = {
      doc: doc, job: job, method: opts.method, resume: start > 1 || (start === 1 && humanFirst),
      log: opts.log || function () {},
      fetchFiles: opts.fetchFiles,
      fetchVideo: opts.fetchVideo,
      status: opts.onStatus || null,
      step: null,
    };
    // 오래 걸리는 단계의 '살아 있음' 신호(서버가 중단으로 보지 않게). 실패해도 단계는 계속(보고는 다음 신호·결과로)
    ctx.beat = async function (msg) {
      if (!ctx.step) return;
      try {
        await opts.transport.send({ 종류: '결과', 본문: { 작업ID: job['작업ID'], 단계: ctx.step, 상태: '진행', 메시지: msg || '',
          주의: [], 코드: '처리중' } });
      } catch (_) { /* 무시 */ }
    };
    var report = async function (name, state, res, final) {
      var body = { 작업ID: job['작업ID'], 단계: name, 상태: state, 메시지: (res && res['메시지']) || '',
        주의: (res && res['주의']) || [], 코드: (res && res['코드']) || null };
      if (final) body['최종'] = final;
      var r = await opts.transport.send({ 종류: '결과', 본문: body });
      if (!r || !r.ok) throw new StepError('서버', '서버에 보고하지 못함: ' + ((r && r['오류']) || '응답 없음'));
    };
    // 예약 확인 버튼을 누르기 직전 보고. 서버가 '지금' 조건(설정·승인·여유)으로 다시 확인해 거절하면 누르지 않고 멈춤.
    ctx.mark = async function (name, code) {
      var r = await opts.transport.send({ 종류: '결과', 본문: { 작업ID: job['작업ID'], 단계: name, 상태: '진행',
        메시지: '확인 버튼을 누르기 직전', 주의: [], 코드: code } });
      if (!r || !r.ok) {
        if (r && r['코드'] === '예약불가') throw new StepError('예약불가', (r['오류'] || '서버가 예약을 멈춤') + ' — 발행하지 않음');
        throw new StepError('서버', '서버에 보고하지 못함(확인 버튼은 누르지 않음): ' + ((r && r['오류']) || '응답 없음'));
      }
      ctx.marked = true;
    };
    var finalOf = function (i) {
      if (i !== steps.length - 1) return null;
      return steps[i] === '예약발행' ? '예약발행완료' : '임시저장완료';
    };
    if (RUN.zombie) {
      // 앞의 시간 초과된 단계가 아직 멈추지 않음 → 이 작업은 손대지 않고 바로 돌려줌(시작할 단계에 실패로 남겨, 나중에 그 단계부터 다시)
      var zstep = steps[start] || steps[0] || '준비';
      var zmsg = '앞의 시간 초과된 단계가 아직 멈추지 않아 시작하지 않았습니다 — 잠시 뒤 [이 단계부터 다시] 또는 화면을 새로고침';
      try { await report(zstep, '실패', { 메시지: zmsg, 코드: '확인필요' }); } catch (_) { /* 서버 보고 실패 */ }
      if (opts.onStep) opts.onStep(zstep, '실패', zmsg);
      return { ok: false, 실패단계: zstep, 코드: '확인필요', 메시지: zmsg };
    }
    armGuard(doc, true);
    try {
      // '준비'는 언제나 먼저(재시도라도 화면 확인)
      var order = [0].concat(steps.map(function (_, i) { return i; }).filter(function (i) { return i >= Math.max(start, 1); }));
      for (var k = 0; k < order.length; k++) {
        var i = order[k];
        var name = steps[i];
        if (opts.shouldStop && opts.shouldStop()) {
          var stopRes = { 메시지: '사람이 멈춤', 코드: '사람이멈춤' };
          await report(name, '실패', stopRes);
          if (opts.onStep) opts.onStep(name, '실패', stopRes['메시지']);
          return { ok: false, 실패단계: name, 코드: '사람이멈춤', 메시지: '사람이 멈춤' };
        }
        if (k === 1 && humanFirst) {
          var hres = { 메시지: '사람이 했다고 표시' };
          await report(name, '사람', hres, finalOf(i));
          if (opts.onStep) opts.onStep(name, '사람', hres['메시지']);
          continue;
        }
        var fn = stepRunner(name, blocks[name]);
        if (opts.onStep) opts.onStep(name, '진행', '');
        await report(name, '진행', null);
        var res;
        var stepPromise = null;
        var timer = null;
        RUN.cancelled = false;
        RUN.doc = doc;
        RUN.lastBarrier = 0;
        ctx.step = name;
        try {
          if (!fn) throw new StepError('설정오류', '모르는 단계: ' + name);
          if (name !== '준비') checkBarrier(doc);
          var limit = S.timing.stepMs * (/^블록/.test(name) ? 4 : 1);
          if (blocks[name] && blocks[name]['종류'] === '영상') limit = S.timing.videoStepMs || limit;
          stepPromise = Promise.resolve().then(function () { return fn(ctx); });
          res = await Promise.race([stepPromise, new Promise(function (_, reject) {
            timer = setTimeout(function () {
              RUN.cancelled = true; // 단계 안의 다음 동작이 곧바로 멈추게
              reject(new StepError('시간초과', Math.round(limit / 1000) + '초 안에 끝나지 않음'));
            }, limit);
          })]);
        } catch (err) {
          var code = err instanceof StepError ? err.code : '오류';
          var msg = err instanceof StepError ? err.message : String(err && err.message || err);
          if (stepPromise && RUN.cancelled) {
            // 시간 초과: 단계가 실제로 멈출 때까지(최대 30초) 기다린 뒤 보고 — 보고 뒤에 화면을 더 만지지 않게
            var settled = false;
            var settle = stepPromise.then(function () { settled = true; }, function () { settled = true; });
            await Promise.race([settle, rawSleep(S.timing.cancelWaitMs || 30000)]);
            if (!settled) {
              // 아직도 안 멈춤 → 끝날 때까지 cancelled 를 그대로 두고, 끝나면 풀어 줌
              RUN.zombie = settle;
              settle.then(function () { if (RUN.zombie === settle) { RUN.zombie = null; RUN.cancelled = false; } });
              msg += ' (단계가 아직 멈추지 않음 — 화면을 새로고침한 뒤 다시)';
            }
          }
          clearTimeout(timer);
          RUN.doc = null;
          if (ctx.marked && code !== '확인필요') {
            code = '확인필요';
            msg += ' — 발행 확인 버튼이 눌렸을 수 있습니다. 네이버의 예약 발행 목록을 사람이 꼭 확인하세요';
          }
          if (code === '서버') throw err;
          await report(name, '실패', { 메시지: msg, 코드: code });
          if (opts.onStep) opts.onStep(name, '실패', msg);
          return { ok: false, 실패단계: name, 코드: code, 메시지: msg };
        }
        clearTimeout(timer);
        RUN.doc = null;
        var state = res['상태'] || '완료';
        await report(name, state, res, finalOf(i));
        if (opts.onStep) opts.onStep(name, state, res['메시지'] + ((res['주의'] || []).length ? ' / 주의: ' + res['주의'].join(' / ') : ''));
      }
      return { ok: true };
    } catch (err) {
      var m = err instanceof StepError ? err.message : String(err && err.message || err);
      return { ok: false, 실패단계: null, 코드: '서버', 메시지: m };
    } finally {
      RUN.doc = null;
      if (!RUN.zombie) RUN.cancelled = false; // 멈추지 않은 옛 단계가 있으면 그 단계가 끝날 때 풂
      armGuard(doc, false);
    }
  }

  // ── 5. 패널 ────────────────────────────────────────────────────────────
  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text != null) node.textContent = text;
    return node;
  }

  function base64ToFile(b64, name, type) {
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name, { type: type, lastModified: Date.now() });
  }

  function extensionTransport() {
    return {
      send: function (msg) {
        return new Promise(function (resolve) {
          try {
            chrome.runtime.sendMessage(msg, function (resp) {
              if (chrome.runtime.lastError) {
                resolve({ ok: false, 오류: '확장과 연결이 끊겼습니다. 이 화면을 새로고침하세요. (' + chrome.runtime.lastError.message + ')' });
              } else {
                resolve(resp || { ok: false, 오류: '응답 없음' });
              }
            });
          } catch (err) {
            resolve({ ok: false, 오류: '확장이 다시 로드되었습니다. 이 화면을 새로고침하세요.' });
          }
        });
      },
      fetchLarge: function (infos, progress) { return bridgeFetch(this.send, infos, progress); },
    };
  }

  async function fetchBundleFiles(transport, bundle, progress) {
    var infos = bundle['파일'] || [];
    var files = [];
    for (var i = 0; i < infos.length; i++) {
      assertLive(); // 시간 초과로 멈춘 단계면 남은 사진을 더 받지 않음
      if (progress) progress(i, infos.length);
      var f = infos[i];
      var r = await transport.send({ 종류: '파일', 주소: f['주소'] });
      assertLive();
      if (!r || !r.ok) {
        var conn = !r || r['코드'] === '서버꺼짐' || r['코드'] === '시간초과' || !r['코드'];
        throw new StepError(conn ? '서버' : '사진없음', ((r && r['오류']) || '사진을 받지 못했습니다') + ' — ' + f['이름']);
      }
      files.push(base64ToFile(r['파일'].base64, f['이름'], f['형식'] || r['파일']['형식']));
    }
    return files;
  }

  /** 동영상(큰 파일) 받기 — transport.fetchLarge 가 있어야 함(확장: 숨은 다리 iframe, 하네스: 가짜) */
  async function fetchVideoFiles(transport, infos, progress) {
    if (!transport.fetchLarge) throw new StepError('설정오류', '큰 파일(동영상)을 받을 통로가 없음');
    assertLive();
    var files = await transport.fetchLarge(infos, progress);
    assertLive();
    if (!files || files.length !== infos.length) throw new StepError('확인필요', '동영상 ' + infos.length + '개 중 ' + ((files || []).length) + '개만 받음');
    for (var i = 0; i < infos.length; i++) {
      if (infos[i]['크기'] && files[i].size !== infos[i]['크기']) {
        throw new StepError('확인필요', '동영상 크기가 다름(' + files[i].size + ' / ' + infos[i]['크기'] + '바이트) — ' + infos[i]['이름']);
      }
    }
    return files;
  }

  /**
   * 큰 파일 통로(확장): 확장 출처의 숨은 iframe(video-bridge.html, web_accessible_resources)이
   * 토큰으로 내 PC 서버에서 동영상을 스트리밍으로 받아 File 로 만들고, MessageChannel 로 이 콘텐츠 스크립트에만 넘김.
   *  - 왜: 서비스 워커 메시지는 JSON(=base64)이라 수백 MB 동영상은 메모리 3~4배·메시지 크기 한계. File 은 복사 없이 넘어감
   *  - 안전: 받을 파일 목록은 서비스 워커가 일회용 '표'로 묶어 둠(파일 주소만, 2분). 네이버 페이지 스크립트는 표를 모르니
   *          받기를 시킬 수 없고, 파일은 비공개 MessageChannel 로만 오가서 엿볼 수 없음. 토큰은 네이버 페이지로 넘기지 않음
   *  - 실측 필요: 네이버 페이지 정책(CSP)이 확장 iframe 을 막지 않는지, 확장 iframe 에서 127.0.0.1 요청이 되는지
   */
  async function bridgeFetch(send, infos, progress) {
    var t = await send({ 종류: '영상표', 파일: infos.map(function (f) {
      return { 주소: f['주소'], 이름: f['이름'], 형식: f['형식'], 크기: f['크기'] };
    }) });
    if (!t || !t.ok) {
      var conn = !t || t['코드'] === '서버꺼짐' || t['코드'] === '시간초과';
      throw new StepError(conn ? '서버' : '영상전달', '동영상 받을 준비를 못 함: ' + ((t && t['오류']) || '응답 없음'));
    }
    var extOrigin = new URL(chrome.runtime.getURL('/')).origin;
    var frame = document.createElement('iframe');
    frame.src = chrome.runtime.getURL('video-bridge.html');
    frame.setAttribute('aria-hidden', 'true');
    frame.setAttribute('data-blog-helper-bridge', '1');
    frame.tabIndex = -1;
    frame.style.cssText = 'position:fixed;width:1px;height:1px;left:-10px;top:-10px;border:0;opacity:0;pointer-events:none';
    (PANEL_UI ? PANEL_UI.root : document.documentElement).appendChild(frame);  // 닫힌 그림자 루트 안 — 페이지가 이 창을 찾지 못함
    return await new Promise(function (resolve, reject) {
      var ch = new MessageChannel();
      var settled = false;
      var hello = false;
      var timers = [];
      function end(err, files) {
        if (settled) return;
        settled = true;
        timers.forEach(function (x) { clearTimeout(x); clearInterval(x); });
        if (err) { try { ch.port1.postMessage({ 종류: '멈춤' }); } catch (_) { /* 무시 */ } }
        try { ch.port1.close(); } catch (_) { /* 무시 */ }
        setTimeout(function () { if (frame.isConnected) frame.remove(); }, 0);
        if (err) reject(err); else resolve(files);
      }
      ch.port1.onmessage = function (e) {
        var d = e.data || {};
        if (d['종류'] === '연결됨') { hello = true; return; }
        if (d['종류'] === '진행') { if (progress) progress(d); return; }
        if (d['종류'] === '파일') { end(null, d['파일'] || []); return; }
        if (d['종류'] === '오류') {
          var c = d['코드'];
          end(new StepError(c === '서버꺼짐' ? '서버' : c === '연결필요' ? '연결필요' : '영상없음', '동영상을 받지 못함: ' + d['오류']));
        }
      };
      frame.addEventListener('load', function () {
        try {
          frame.contentWindow.postMessage({ 종류: '영상다리', 표: t['표'] }, extOrigin, [ch.port2]);
        } catch (err) {
          end(new StepError('영상전달', '동영상 다리 창에 연결하지 못함: ' + err.message));
          return;
        }
        timers.push(setTimeout(function () {
          if (!hello) end(new StepError('영상전달', '확장의 동영상 다리 창이 응답하지 않음(페이지가 확장 창을 막았을 수 있음 — 실측 필요)'));
        }, 10000));
      }, { once: true });
      timers.push(setTimeout(function () {
        end(new StepError('시간초과', '동영상을 내 PC 서버에서 받는 데 ' + Math.round(S.timing.videoFetchMs / 60000) + '분이 넘음'));
      }, S.timing.videoFetchMs));
      timers.push(setInterval(function () {
        if (RUN.cancelled) end(new StepError('시간초과', '단계를 멈췄습니다(시간 초과)'));
      }, 300));
    });
  }

  // ── 진단(실측용) ───────────────────────────────────────────────────────
  // 사람이 [진단 보내기]를 눌렀을 때만: 화면의 '구조'(태그·id·class·속성 이름/값·짧은 UI 글자)만 모아 내 PC 서버로.
  // 넣지 않는 것: 본문 글·제목·태그 값·입력값·사진/영상 주소·주소의 쿼리 값. 글이 들어가는 곳(에디터 캔버스·제목·
  // 사진 설명·입력칸·태그·카테고리 목록·장소 결과·contenteditable)의 글자는 '[글]'로, 작업의 글 값과 같은 글자도 '[글]'로.
  var DIAG = { budgets: [8000, 4000, 2000], maxDepth: 40, maxChildren: 400, maxText: 20, maxBytes: 2000000 };
  var DIAG_SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, LINK: 1, META: 1, HEAD: 1, BASE: 1 };
  var DIAG_UI_TAGS = { BUTTON: 1, LABEL: 1, A: 1, SUMMARY: 1, LEGEND: 1, OPTION: 1, TH: 1, H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1 };
  var DIAG_UI_ROLE = /^(button|tab|menuitem|menuitemradio|menuitemcheckbox|option|switch|checkbox|radio|heading|dialog|alertdialog|tooltip|link|combobox|listbox|toolbar)$/;
  var DIAG_UI_CLASS = /(popup|layer|dialog|toolbar|modal|tooltip|menu)/i;
  var DIAG_ATTRS = ['role', 'type', 'name', 'for', 'placeholder', 'title', 'alt', 'accept', 'contenteditable', 'tabindex',
    'disabled', 'checked', 'multiple', 'readonly', 'src', 'href', 'aria-label', 'aria-checked', 'aria-pressed',
    'aria-expanded', 'aria-selected', 'aria-disabled', 'aria-hidden', 'aria-haspopup', 'aria-controls', 'aria-labelledby'];
  var DIAG_FLAGS = { disabled: 1, checked: 1, multiple: 1, readonly: 1 };
  var DIAG_UI_WORDS = ['제목', '본문', '사진', '동영상', '장소', '지도', '구분선', '인용구', '소제목', '글감', '스티커', '파일', '링크',
    '표', '일정', '코드', '수식', '템플릿', '라이브러리', '대표', '편집', '삭제', '설명', '캡션', '이미지', '갤러리', '콜라주', '슬라이드',
    '개별 사진', '텍스트', '저장', '발행', '취소', '확인', '완료', '닫기', '추가', '검색', '예약', '태그', '카테고리', '공개'];
  var SAFE_ID_RE = /^[A-Za-z0-9_.:\-]{1,40}$/;
  // 파일 이름처럼 보이는 값(사진·영상·문서) — 'tpb.save' 같은 화면 이름은 남김
  var FILE_LIKE_RE = /\.(jpe?g|png|gif|webp|bmp|heic|heif|tiff?|mp4|m4v|mov|avi|wmv|mkv|webm|3gp|flv|mpe?g|pdf|txt|docx?|hwpx?|xlsx?|pptx?|zip|json|html?|csv)$/i;
  var URLISH_RE = /(:\/\/|^\/|\\|@|\{|\[|www\.|\.com\b|\.net\b|\.kr\b)/i;
  var PRIVATE_RE = /([\w.+-]+@[\w-]+\.[\w.]+|\d{2,4}-\d{3,4}-\d{4}|https?:)/i;

  function diagScrubUrl(href) {
    var u;
    try { u = new URL(href, location.href); } catch (_) { return '[주소]'; }
    if (/^(blob|data|javascript):$/.test(u.protocol)) return u.protocol + '[생략]';
    var path = u.pathname.split('/').map(function (seg, i) {
      var plain = seg;
      try { plain = decodeURIComponent(seg); } catch (_) { /* 그대로 */ }
      if (FILE_LIKE_RE.test(plain)) return '{파일}';  // 사진·문서 파일 이름은 사용자 내용
      if (!seg || seg.indexOf('.') >= 0 || /^(postwrite|Redirect|PostWriteForm\.naver|GoBlogWrite\.naver)$/i.test(seg)) return seg;
      return i === 1 ? '{아이디}' : '{값}';
    }).join('/');
    var names = [];
    u.searchParams.forEach(function (_, k) { if (names.indexOf(k) < 0) names.push(k); });
    return u.protocol + '//' + u.host + path + (names.length ? '?' + names.map(function (k) { return k + '=…'; }).join('&') : '') + (u.hash ? '#…' : '');
  }

  /** 작업의 글 값(제목·블록 글·설명·태그·카테고리·장소·파일 이름)으로 지울 목록 */
  function diagJobValues(job) {
    var out = [];
    var add = function (v) {
      String(v == null ? '' : v).split('\n').forEach(function (line) {
        var s = norm(line).replace(/^#/, '');
        if (s.length >= 2 && out.indexOf(s) < 0) out.push(s);
      });
    };
    if (!job) return out;
    var g = job['글'] || {};
    add(g['제목']); add(job['제목']); add(g['카테고리']);
    (g['태그'] || []).forEach(add);
    (g['블록'] || []).forEach(function (b) {
      ['글', '설명', '출처', '제목'].forEach(function (k) { add(b[k]); });
      (b['목록'] || []).forEach(add);
      (b['장소'] || []).forEach(add);
    });
    (job['묶음'] || []).forEach(function (b) {
      add(b['폴더']); add(b['앞소제목']); add(b['설명']);
      (b['파일'] || []).forEach(function (f) { add(f['이름']); add(f['경로']); });
    });
    return out.sort(function (a, b) { return b.length - a.length; });
  }
  function diagRedactor(values) {
    return {
      hit: function (text) { var t = norm(text); return values.some(function (v) { return t.indexOf(v) >= 0; }); },
      mask: function (text) {
        var s = String(text == null ? '' : text);
        values.forEach(function (v) { if (v) s = s.split(v).join('[글]'); });
        return s.replace(/blob:[^\s'"”)]+/g, 'blob:[생략]');
      },
    };
  }

  function diagZones(doc) {
    // 입력칸(input·select)은 값을 아예 읽지 않으므로 이름·placeholder 는 남김. textarea 의 글자는 아래에서 [글]
    var sels = ['[contenteditable]:not([contenteditable="false"])']
      .concat(S.editorRoot || [], S.title || [], S.imageCaption || [], S.tagChip || [], S.categoryItem || [],
        ['.se-component'], (S.place && S.place.resultItem) || [], (S.video && S.video.titleInput) || [], (S.video && S.video.descInput) || []);
    var set = new Set();
    sels.forEach(function (sel) { try { doc.querySelectorAll(sel).forEach(function (n) { set.add(n); }); } catch (_) { /* 잘못된 선택자 */ } });
    return set;
  }

  function diagAttrValue(name, value, zone, red, tag) {
    if (DIAG_FLAGS[name]) return '';
    var v = String(value == null ? '' : value);
    if (name === 'src' && /^(img|video|audio|source|track|embed|object)$/.test(tag || '')) return '[주소]';  // 사진·영상 주소는 넣지 않음
    if (name === 'src' || name === 'href') return /^(javascript|blob|data):/i.test(v) ? v.split(':')[0] + ':[생략]' : diagScrubUrl(v);
    if (!v) return '';
    if (red.hit(v) || PRIVATE_RE.test(v)) return '[글]';
    if (zone) {
      if (name === 'role' || name === 'type' || name === 'contenteditable' || name === 'tabindex') return v.slice(0, 40);
      if ((/^(data|aria)-/.test(name)) && ((SAFE_ID_RE.test(v) && !FILE_LIKE_RE.test(v)) || DIAG_UI_WORDS.indexOf(v) >= 0)) return v;
      return '[값]';
    }
    if (v.length > 40 || URLISH_RE.test(v) || FILE_LIKE_RE.test(v)) return '[값 ' + v.length + '자]';
    return v;
  }

  function diagUiContext(el) {
    for (var e = el, i = 0; e && i < 5; e = e.parentElement, i++) {
      if (DIAG_UI_TAGS[e.tagName]) return true;
      var role = e.getAttribute && e.getAttribute('role');
      if (role && DIAG_UI_ROLE.test(role)) return true;
      var cls = typeof e.className === 'string' ? e.className : '';
      if (cls && DIAG_UI_CLASS.test(cls)) return true;
    }
    return false;
  }

  function diagNode(el, depth, zone, ctx) {
    if (DIAG_SKIP[el.tagName]) return null;
    if (el.getAttribute && el.getAttribute('data-blog-helper-bridge')) return null;
    if (ctx.count >= ctx.max) { ctx.cut = true; return null; }
    ctx.count++;
    var tag = el.tagName.toLowerCase();
    if (el.id === PANEL_ID) return { t: tag, id: el.id, 생략: '블로그 도우미 패널' };
    var z = zone || ctx.zones.has(el);
    var node = { t: tag };
    if (el.id) node.id = String(el.id).slice(0, 80);
    var cls = typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '');
    if (cls) node.c = norm(cls).slice(0, 200);
    var attrs = null;
    for (var i = 0; i < el.attributes.length; i++) {
      var an = el.attributes[i].name;
      if (an === 'id' || an === 'class' || an === 'value' || an === 'style') continue;
      if (an.indexOf('data-') !== 0 && DIAG_ATTRS.indexOf(an) < 0) continue;
      if (an.indexOf('data-blog-helper') === 0) continue;
      (attrs = attrs || {})[an] = diagAttrValue(an, el.attributes[i].value, z, ctx.red, tag);
    }
    if (attrs) node.a = attrs;
    var own = '';
    for (var c = el.firstChild; c; c = c.nextSibling) if (c.nodeType === 3) own += c.nodeValue;
    own = norm(own);
    if (own) {
      if (z || tag === 'textarea' || ctx.red.hit(own) || PRIVATE_RE.test(own)) node.x = '[글]';
      else if (own.length > DIAG.maxText) node.x = '[긴 글 ' + own.length + '자]';
      else if (diagUiContext(el)) node.x = own;
      else node.x = '[글]';
    }
    if (!isVisible(el)) node.v = 0;
    if (el.shadowRoot) node.그림자 = 1;
    if (tag === 'iframe') {
      var d = null;
      try { d = el.contentDocument; } catch (_) { d = null; }
      node.f = d && d.documentElement ? diagDoc(d, depth + 1, ctx) : '[다른 출처 또는 비어 있음]';
      return node;
    }
    if (tag === 'svg') { if (el.childElementCount) node.n = el.childElementCount; return node; }
    if (depth >= DIAG.maxDepth) { if (el.childElementCount) node.n = el.childElementCount; return node; }
    var kids = [];
    var children = el.children;
    for (var j = 0; j < children.length && j < DIAG.maxChildren; j++) {
      var k = diagNode(children[j], depth + 1, z, ctx);
      if (k) kids.push(k);
      if (ctx.cut) break;
    }
    if (kids.length) node.k = kids;
    if (children.length > kids.length) node.n = children.length - kids.length;
    return node;
  }

  function diagDoc(doc, depth, ctx) {
    var saved = ctx.zones;
    ctx.zones = diagZones(doc);
    var before = ctx.count;
    var root = doc.body || doc.documentElement;
    var tree = diagNode(root, depth, false, ctx);
    ctx.zones = saved;
    return { 주소: diagScrubUrl(doc.location ? doc.location.href : ''), 요소수: ctx.count - before, 트리: tree };
  }

  var DIAG_NOT_SELECTORS = { writeUrl: 1, textMethods: 1, newParagraphMethods: 1, clickEvents: 1, photoButtonEvents: 1,
    barrierText: 1, doneText: 1, timing: 1, layoutText: 1, searchTries: 1, categoryItemControl: 1, restorePopupText: 1 };
  function diagSelectors(editorDoc, topDoc) {
    var out = {};
    var count = function (doc, sel) {
      var n = 0;
      var vis = 0;
      doc.querySelectorAll(sel).forEach(function (e) { if (!isOurs(e)) { n++; if (isVisible(e)) vis++; } });
      return [n, vis];
    };
    (function walk(obj, path) {
      Object.keys(obj).forEach(function (key) {
        if (DIAG_NOT_SELECTORS[key]) return;
        var v = obj[key];
        var p = path ? path + '.' + key : key;
        if (Array.isArray(v)) {
          if (!v.length) { out[p] = '비어 있음(미실측)'; return; }
          if (!v.every(function (x) { return typeof x === 'string'; })) return;
          out[p] = v.map(function (sel) {
            try {
              var a = count(editorDoc, sel);
              var r = { 선택자: sel, 에디터: a[0], 보임: a[1] };
              if (topDoc && topDoc !== editorDoc) r['바깥'] = count(topDoc, sel)[0];
              return r;
            } catch (_) { return { 선택자: sel, 오류: '잘못된 선택자' }; }
          });
        } else if (v && typeof v === 'object' && !(v instanceof RegExp)) walk(v, p);
      });
    })(S, '');
    return out;
  }

  /** 진단 만들기(읽기만 함 — 화면을 바꾸지 않음). opts: {job, lastRun, log} */
  function collectDiagnostics(opts) {
    opts = opts || {};
    var editorDoc = document;
    var topDoc = null;
    var topNote = null;
    if (window.top !== window) {
      try { topDoc = window.top.document; topDoc.documentElement; } catch (_) { topDoc = null; topNote = '[접근 불가(다른 출처)]'; }
    }
    var red = diagRedactor(diagJobValues(opts.job));
    var last = null;
    if (opts.lastRun) {
      last = JSON.parse(JSON.stringify(opts.lastRun));
      (last['단계'] || []).forEach(function (s) { s['메시지'] = red.mask(s['메시지']); });
      if (last['결과']) last['결과']['메시지'] = red.mask(last['결과']['메시지']);
    }
    var logLines = String(opts.log || '').split('\n').filter(Boolean).slice(-120).map(function (l) { return red.mask(l).slice(0, 300); });
    var ua = navigator.userAgentData;
    var base = {
      종류: '블로그도우미진단', 버전: 1, 시각: new Date().toISOString(),
      확장: { 버전: VERSION, 확장안: IS_EXTENSION },
      브라우저: { UA: navigator.userAgent, 브랜드: ua && ua.brands ? ua.brands.map(function (b) { return b.brand + ' ' + b.version; }) : [],
        언어: navigator.language, 화면: window.innerWidth + 'x' + window.innerHeight, 배율: window.devicePixelRatio },
      주소: { 이화면: diagScrubUrl(location.href), 바깥: topDoc ? diagScrubUrl(topDoc.location.href) : topNote, 프레임역할: frameRole(document) },
      선택자: diagSelectors(editorDoc, topDoc),
      마지막작업: last,
      기록: logLines,
    };
    var result = null;
    var size = 0;
    for (var i = 0; i < DIAG.budgets.length; i++) {
      var ctx = { count: 0, max: DIAG.budgets[i], cut: false, zones: null, red: red };
      var docInfo = diagDoc(topDoc || editorDoc, 0, ctx);
      result = Object.assign({}, base, { 구조: { 요소수: ctx.count, 잘림: ctx.cut, 한도: DIAG.budgets[i], 문서: docInfo } });
      size = new Blob([JSON.stringify(result)]).size;
      if (size <= DIAG.maxBytes) break;
    }
    return { data: result, size: size };
  }

  async function gzipBase64(text) {
    if (typeof CompressionStream !== 'function') return null;
    var stream = new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'));
    var buf = new Uint8Array(await new Response(stream).arrayBuffer());
    var bin = '';
    for (var i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(bin);
  }

  var STATE_LABEL = { 대기: '대기', 진행: '진행 중', 완료: '완료', 주의: '완료(주의)', 실패: '실패', 사람: '사람이 함', 건너뜀: '건너뜀' };
  var REASON_TEXT = {
    없음: '할 작업이 없습니다. 작업이 생기면 저절로 시작합니다.',
    간격: '다음 글까지 쉬는 중입니다(한 번에 한 편, 최소 간격).',
    다른작업진행중: '다른 화면에서 글을 채우는 중입니다(한 번에 한 편).',
    다른화면진행중: '이 작업은 다른 탭에서 채우는 중입니다.',
  };

  function mountPanel(options) {
    options = options || {};
    var transport = options.transport || extensionTransport();
    var doc = document;
    if (doc.getElementById(PANEL_ID)) return doc.getElementById(PANEL_ID);

    var st = { mode: 'idle', job: null, failedStep: null, stop: false, busy: false, timer: null, countdown: null, steps: {} };

    var panel = el('section', { 'class': 'bh-panel', role: 'region', 'aria-label': '블로그 도우미', 'data-state': 'idle' });
    var head = el('div', { 'class': 'bh-head' });
    var conn = el('span', { 'class': 'bh-conn', 'data-conn': 'checking' }, '확인 중');
    var sideBtn = el('button', { type: 'button', 'class': 'bh-btn bh-mini', 'data-bh': 'side', 'aria-label': '패널을 반대쪽으로 옮기기', title: '반대쪽으로' }, '⇆');
    var toggleBtn = el('button', { type: 'button', 'class': 'bh-btn bh-mini', 'data-bh': 'toggle', 'aria-expanded': 'true', 'aria-label': '패널 접기' }, '접기');
    head.append(el('strong', { 'class': 'bh-title' }, '블로그 도우미'), conn, sideBtn, toggleBtn);

    var body = el('div', { 'class': 'bh-body' });
    var jobTitle = el('div', { 'class': 'bh-jobtitle' });
    var status = el('div', { 'class': 'bh-result', role: 'status', 'aria-live': 'polite', 'data-kind': 'info' }, '작업을 확인하는 중…');
    var steps = el('ol', { 'class': 'bh-steps', 'aria-label': '단계' });
    var btnRow = el('div', { 'class': 'bh-actions' });
    var mk = function (key, text, label) {
      var b = el('button', { type: 'button', 'class': 'bh-btn', 'data-bh': key, 'aria-label': label || text }, text);
      b.hidden = true;
      btnRow.append(b);
      return b;
    };
    var bStart = mk('start-now', '지금 시작');
    var bStop = mk('stop', '멈춤', '작업 멈춤');
    var bRetry = mk('retry', '이 단계부터 다시');
    var bHuman = mk('human', '이 단계는 내가 했음 → 다음', '이 단계는 사람이 했음, 다음 단계부터');
    var bCheck = mk('check', '작업 확인', '서버에 작업이 있는지 지금 확인');

    // 보조: 사진 묶음만 넣기(v1)
    var tool = el('details', { 'class': 'bh-adv bh-tool' });
    var toolSummary = el('summary', {}, '사진 묶음만 넣기(보조)');
    var pkgRow = el('div', { 'class': 'bh-row' });
    var pkgSelect = el('select', { id: 'blog-helper-package', 'class': 'bh-select', 'aria-label': '넣을 글(발행 패키지) 고르기' });
    var refreshBtn = el('button', { type: 'button', 'class': 'bh-btn bh-mini', 'data-bh': 'refresh', 'aria-label': '글 목록 새로고침' }, '새로고침');
    pkgRow.append(el('label', { 'for': 'blog-helper-package', 'class': 'bh-label' }, '글'), pkgSelect, refreshBtn);
    var list = el('ol', { 'class': 'bh-list', 'aria-label': '사진 묶음 목록' });
    tool.append(toolSummary, el('p', { 'class': 'bh-tip' }, '사진이 들어갈 자리를 본문에서 먼저 클릭한 뒤 누르세요. 배치 선택 창은 사람이 고릅니다.'), pkgRow, list);
    // 검수 M2: 보조 도구는 기본으로 숨김 — 확장 아이콘(팝업)에서 사람이 켰을 때만(다른 글의 사진 목록이 보이므로)
    tool.hidden = IS_EXTENSION;
    if (IS_EXTENSION) {
      try {
        chrome.storage.local.get('auxTool', function (v) { tool.hidden = !(v && v.auxTool); });
      } catch (_) { /* 확장이 다시 로드됨 */ }
    }

    var adv = el('details', { 'class': 'bh-adv' });
    var methodSelect = el('select', { id: 'blog-helper-method', 'class': 'bh-select', 'aria-label': '사진 넣기 방법' });
    [['auto', '자동: (a) 다음 (b)'], ['a', '(a) 사진 업로드 칸만'], ['b', '(b) 끌어다 놓기만']].forEach(function (o) {
      methodSelect.append(el('option', { value: o[0] }, o[1]));
    });
    var methodRow = el('div', { 'class': 'bh-row' });
    methodRow.append(el('label', { 'for': 'blog-helper-method', 'class': 'bh-label' }, '사진 방법'), methodSelect);
    var logBox = el('pre', { 'class': 'bh-log', 'aria-label': '자세한 기록' });
    var diagRow = el('div', { 'class': 'bh-row' });
    var bDiag = el('button', { type: 'button', 'class': 'bh-btn', 'data-bh': 'diag', 'aria-label': '진단 보내기(화면 구조만 내 PC 서버로)' }, '진단 보내기');
    diagRow.append(bDiag);
    var diagTip = el('p', { 'class': 'bh-tip' }, '막혔을 때 누르세요. 화면의 구조(버튼·칸 이름)만 내 PC 서버에 저장합니다 — 글·제목·태그 값·입력값·사진은 넣지 않습니다. 그다음 Claude 에게 "진단 읽고 선택자 고쳐줘".');
    adv.append(el('summary', {}, '고급(실측용)'), methodRow, diagRow, diagTip, logBox,
      el('div', { 'class': 'bh-ver' }, '블로그 도우미 ' + VERSION + ' · 외부 전송 없음 · 발행 확인은 누르지 않음(예약발행 허용 작업만 예외)'));

    body.append(jobTitle, status, steps, btnRow, tool, adv);
    panel.append(head, body);
    var host = el('div', { id: PANEL_ID });
    host.setAttribute('style', 'all: initial !important;');
    var shadow = host.attachShadow({ mode: SHADOW_MODE });
    var style = document.createElement('style');
    style.textContent = globalThis.BLOG_HELPER_PANEL_CSS || '';
    shadow.append(style, panel);
    (doc.body || doc.documentElement).appendChild(host);
    PANEL_UI = { host: host, root: shadow, panel: panel };

    // 검수 M2: 사람의 클릭·키보드(브라우저가 만든 isTrusted 이벤트)만 받음 — 스크립트의 .click()·dispatchEvent 는 무시
    ['click', 'change', 'input', 'keydown', 'submit'].forEach(function (t) {
      panel.addEventListener(t, function (e) {
        if (!e.isTrusted) { e.preventDefault(); e.stopImmediatePropagation(); }
      }, true);
    });

    // 패널을 눌러도 에디터 커서가 빠지지 않게, 에디터가 패널 키 입력을 가져가지 않게
    panel.addEventListener('mousedown', function (e) {
      if (e.target.closest('button')) e.preventDefault();
      e.stopPropagation();
    });
    ['click', 'keydown', 'keyup', 'keypress', 'input', 'paste', 'pointerdown'].forEach(function (t) {
      panel.addEventListener(t, function (e) { e.stopPropagation(); });
    });

    function log(m) {
      logBox.textContent += m + '\n';
      logBox.scrollTop = logBox.scrollHeight;
      try { console.debug('[블로그 도우미] ' + m); } catch (_) { /* 무시 */ }
    }
    function setConn(kind, text) { conn.setAttribute('data-conn', kind); conn.textContent = text; }
    function setStatus(text, kind) { status.textContent = text; status.setAttribute('data-kind', kind || 'info'); }
    function setMode(mode) {
      st.mode = mode;
      panel.setAttribute('data-state', mode);
      bStart.hidden = mode !== 'countdown';
      bStop.hidden = !(mode === 'countdown' || mode === 'running');
      bRetry.hidden = mode !== 'failed' || !st.job;
      bHuman.hidden = mode !== 'failed' || !st.job || !st.failedStep || st.failedStep === '준비';
      bCheck.hidden = !(mode === 'idle' || mode === 'done' || mode === 'failed' || mode === 'offline');
      if (st.failedStep) {
        bRetry.textContent = "'" + st.failedStep + "' 단계부터 다시";
        bRetry.setAttribute('aria-label', st.failedStep + ' 단계부터 다시');
      }
    }

    function stepLabel(name) {
      var m = /^블록 (\d+)$/.exec(name);
      if (!m || !st.job) return name;
      var b = (st.job['글']['블록'] || []).filter(function (x) { return String(x['번호']) === m[1]; })[0];
      return name + (b ? ' · ' + b['종류'] + (b['글'] ? ' “' + String(b['글']).slice(0, 14) + '”' : '') : '');
    }
    function renderSteps(job) {
      steps.textContent = '';
      st.steps = {};
      (job['단계목록'] || []).forEach(function (name) {
        var li = el('li', { 'class': 'bh-step', 'data-step': name, 'data-state': '대기' });
        var label = el('span', { 'class': 'bh-step-name' }, stepLabel(name));
        var state = el('span', { 'class': 'bh-step-state' }, STATE_LABEL['대기']);
        li.append(label, state);
        steps.append(li);
        st.steps[name] = { li: li, state: state };
      });
      (job['단계'] || []).forEach(function (s) { markStep(s['이름'], s['상태'], s['메시지']); });
    }
    function markStep(name, state, msg) {
      var s = st.steps[name];
      if (!s) return;
      s.li.setAttribute('data-state', state);
      s.state.textContent = STATE_LABEL[state] || state;
      s.li.title = msg || '';
      if (state === '진행') { try { s.li.scrollIntoView({ block: 'nearest' }); } catch (_) { /* 무시 */ } }
    }

    function showJob(job) {
      st.job = job;
      jobTitle.textContent = '“' + (job['제목'] || job['글']['제목']) + '” · ' + job['모드'] +
        (job['모드'] === '예약발행' && job['예약'] ? (job['예약']['허용'] ? ' ' + job['예약']['시각'] : ' (예약 조건 안 맞음 → 임시저장까지만)') : '');
      renderSteps(job);
    }

    async function poll(manual) {
      if (st.busy) return;
      var fresh = st.mode === 'idle' || st.mode === 'offline';
      if (!fresh && !(manual && (st.mode === 'done' || st.mode === 'failed'))) return;
      st.busy = true;
      try {
        if (!fresh) {
          // 이 화면에는 이미 글이 있음 → 다른 글을 받지 않음. 이 작업을 (스튜디오·Claude 가) 다시 하라고 했을 때만 받음
          var mine = st.job ? await transport.send({ 종류: '작업', 작업ID: st.job['작업ID'] }) : null;
          var mineState = mine && mine.ok && mine['데이터'] && mine['데이터']['작업'] && mine['데이터']['작업']['상태'];
          if (mineState !== '대기') {
            setStatus('이 화면에는 이미 글이 있어 새 작업을 받지 않습니다. 다음 글은 새 글쓰기 화면을 열면 저절로 받습니다.' +
              (mineState ? " (이 작업: '" + mineState + "')" : ''), 'info');
            return;
          }
        }
        // 글이 있는 화면에서는 이 화면의 작업만 받음(서버가 그 작업ID 만 내줌 — 다른 글을 받지 않게)
        var r = await transport.send(fresh ? { 종류: '대기작업' } : { 종류: '대기작업', 작업ID: st.job['작업ID'] });
        if (!r || !r.ok) {
          setMode(st.mode === 'failed' || st.mode === 'done' ? st.mode : 'offline');
          if (r && r['코드'] === '연결필요') {
            setConn('off', '연결 필요');
            setStatus('확장 연결이 필요합니다 — 브라우저 오른쪽 위 확장 아이콘(블로그 도우미)을 누르고 연결 코드를 넣으세요.', 'error');
          } else {
            setConn('off', '서버 꺼짐');
            setStatus((r && r['오류']) || '로컬 서버에 연결할 수 없습니다.', 'error');
          }
          return;
        }
        var d = r['데이터'] || {};
        setConn('on', '연결됨 · ' + (d['서버'] || '서버'));
        if (d['작업']) {
          if (!fresh && d['작업']['작업ID'] !== st.job['작업ID']) return await releaseWrong(d['작업']);
          if (d['사유'] === '재개') return await handleResume(d['작업']);
          if (!fresh) { st.busy = false; showJob(d['작업']); return run(d['작업'], false); } // 사람이 눌러서 받은 같은 작업
          return startCountdown(d['작업']);
        }
        if (st.mode === 'offline') setMode('idle');
        if (st.mode === 'idle') {
          setStatus((REASON_TEXT[d['사유']] || '할 작업이 없습니다.') + (d['다음가능'] ? ' 다음 가능: ' + d['다음가능'] : ''), 'info');
        } else if (manual) {
          setStatus('이 작업을 지금 받지 못했습니다: ' + (REASON_TEXT[d['사유']] || d['사유'] || '') + (d['다음가능'] ? ' 다음 가능: ' + d['다음가능'] : ''), 'info');
        }
      } finally {
        st.busy = false;
      }
    }

    /** (예전 서버 등으로) 이 화면의 것이 아닌 작업을 받았을 때: 손대지 않고 바로 돌려줌 */
    async function releaseWrong(job) {
      await transport.send({ 종류: '결과', 본문: { 작업ID: job['작업ID'], 단계: '준비', 상태: '실패', 코드: '확인필요',
        메시지: '다른 글이 있는 화면이 받은 작업이라 손대지 않고 돌려줌 — 새 글쓰기 화면에서 다시' } });
      setStatus("이 화면의 작업이 아닌 '" + (job['제목'] || job['작업ID']) + "'을 받아 손대지 않고 돌려줬습니다. 새 글쓰기 화면에서 다시 하세요.", 'warn');
    }

    async function handleResume(job) {
      // 새로고침 등으로 화면이 바뀌어 같은 작업을 다시 받음 → 이어서 하지 않고 확인을 맡김(중복 방지)
      showJob(job);
      var plan = job['단계목록'] || [];
      var at = job['현재단계'] || '준비';
      // '준비'에서 끊겼고(예: '작성 중인 글' 창을 [취소]해 에디터가 새로 그려짐) 화면이 비어 있으면 아직 넣은 것이 없으므로 처음부터
      var prepLast = (job['단계'] || []).filter(function (x) { return x['이름'] === '준비'; })[0];
      if (at === '준비' && !(prepLast && prepLast['상태'] === '실패') && !titleText(doc) && bodyIsEmpty(doc)) {
        startCountdown(job);
        return;
      }
      var last = (job['단계'] || []).filter(function (x) { return x['이름'] === at; })[0];
      if (last && ['완료', '주의', '사람', '건너뜀'].indexOf(last['상태']) >= 0 && plan.indexOf(at) >= 0 && plan.indexOf(at) < plan.length - 1) {
        at = plan[plan.indexOf(at) + 1];
      }
      await transport.send({ 종류: '결과', 본문: { 작업ID: job['작업ID'], 단계: at, 상태: '실패', 코드: '확인필요',
        메시지: '화면이 새로 열려 이어서 할 수 없음 — 네이버 화면을 확인하고 다시 시도하세요' } });
      st.failedStep = at;
      markStep(at, '실패', '');
      setMode('failed');
      setStatus("이 작업은 새로고침 전에 '" + at + "' 단계를 하던 중이었습니다. 화면을 확인한 뒤 [이 단계부터 다시] 또는 처음부터(새 글쓰기 화면) 다시 하세요.", 'warn');
    }

    function startCountdown(job) {
      showJob(job);
      st.failedStep = null;
      st.stop = false;
      setMode('countdown');
      var left = Math.ceil(S.timing.countdownMs / 1000);
      var tick = function () {
        if (st.mode !== 'countdown') return;
        if (left <= 0) { run(job, false); return; }
        setStatus('작업을 받았습니다. ' + left + '초 뒤 글 채우기를 시작합니다. 멈추려면 [멈춤].', 'busy');
        left -= 1;
        st.countdown = setTimeout(tick, 1000);
      };
      tick();
    }

    async function run(job, humanFirst) {
      clearTimeout(st.countdown);
      setMode('running');
      st.stop = false;
      logBox.textContent = '';
      setStatus('글을 채우는 중입니다. 화면을 만지지 마세요.', 'busy');
      var lastRun = st.lastRun = { 작업ID: job['작업ID'], 모드: job['모드'], 시작단계: job['시작단계'] || null,
        시작: new Date().toISOString(), 단계: [], 결과: null };
      var res = await runJob(job, {
        doc: doc, transport: transport, method: methodSelect.value, log: log, humanFirst: humanFirst,
        shouldStop: function () { return st.stop; },
        fetchFiles: function (bundle) {
          return fetchBundleFiles(transport, bundle, function (i, n) { setStatus('사진 받는 중 (' + i + '/' + n + ')', 'busy'); });
        },
        fetchVideo: function (infos) {
          return fetchVideoFiles(transport, infos, function (p) {
            setStatus('동영상 받는 중 (' + p['번호'] + '/' + p['전체수'] + ') ' + formatBytes(p['받은']) +
              (p['크기'] ? ' / ' + formatBytes(p['크기']) : ''), 'busy');
          });
        },
        onStatus: function (text) { setStatus(text, 'busy'); },
        onStep: function (name, state, msg) {
          lastRun['단계'].push({ 단계: name, 상태: state, 메시지: String(msg || '').slice(0, 500), 시각: new Date().toISOString() });
          if (lastRun['단계'].length > 300) lastRun['단계'].shift();
          markStep(name, state, msg);
          if (state === '진행') setStatus('채우는 중: ' + stepLabel(name), 'busy');
          log(name + ' → ' + state + (msg ? ' — ' + msg : ''));
        },
      });
      lastRun['결과'] = { ok: !!res.ok, 실패단계: res['실패단계'] || null, 코드: res['코드'] || null,
        메시지: String(res['메시지'] || '').slice(0, 500) };
      lastRun['끝'] = new Date().toISOString();
      if (res.ok) {
        var notes = Object.keys(st.steps).filter(function (n) { return st.steps[n].li.getAttribute('data-state') === '주의'; });
        st.failedStep = null;
        setMode('done');
        var last = (job['단계목록'] || []).slice(-1)[0];
        setStatus((last === '예약발행' ? '예약 발행까지 끝났습니다.' : "임시저장까지 끝났습니다. 네이버 화면에서 모바일 보기로 확인한 뒤 '발행'은 사람이 누르세요.") +
          ' 다음 글은 새 글쓰기 화면을 열면 받습니다.' +
          (notes.length ? ' 주의가 있는 단계: ' + notes.join(', ') + '(단계에 마우스를 올리면 내용).' : ''), notes.length ? 'warn' : 'done');
      } else {
        st.failedStep = res['실패단계'];
        setMode('failed');
        setStatus((res['실패단계'] ? "'" + res['실패단계'] + "' 단계에서 멈췄습니다: " : '멈췄습니다: ') + res['메시지'] +
          (res['코드'] === '로그인필요' || res['코드'] === '보안확인' ? ' (사람이 처리한 뒤 다시)' : ''), 'error');
      }
    }

    async function retryFrom(stepName, humanFirst) {
      if (!st.job || st.busy) return;
      st.busy = true;
      try {
        var r = await transport.send({ 종류: '재시도', 작업ID: st.job['작업ID'], 단계: stepName, 사람: !!humanFirst });
        if (!r || !r.ok) { setStatus('다시 하기를 서버가 받지 않았습니다: ' + ((r && r['오류']) || ''), 'error'); return; }
        var c = await transport.send({ 종류: '대기작업', 작업ID: st.job['작업ID'] }); // 이 작업만 받음
        var job = c && c.ok && c['데이터'] && c['데이터']['작업'];
        if (job && job['작업ID'] !== st.job['작업ID']) { await releaseWrong(job); return; }
        if (!job) {
          var d2 = (c && c['데이터']) || {};
          setStatus('작업을 다시 받지 못했습니다: ' + ((REASON_TEXT[d2['사유']] || '') + (d2['다음가능'] ? ' 다음 가능: ' + d2['다음가능'] + ' 뒤 [작업 확인]' : '') || (c && c['오류']) || ''), 'error');
          return;
        }
        showJob(job);
      } finally {
        st.busy = false;
      }
      run(st.job, false); // '사람' 처리는 서버가 준 시작단계사람 값으로
    }

    /** [진단 보내기] — 사람이 누른 클릭(isTrusted)에서만 부름. 화면을 바꾸지 않고 읽기만 함 */
    async function sendDiag() {
      if (st.diagBusy) return;
      st.diagBusy = true;
      bDiag.disabled = true;
      try {
        setStatus('진단을 만드는 중…(화면 구조만)', 'busy');
        var made = collectDiagnostics({ job: st.job, lastRun: st.lastRun, log: logBox.textContent });
        var raw = JSON.stringify(made.data);
        var gz = null;
        try { gz = await gzipBase64(raw); } catch (_) { gz = null; }
        var body = gz ? { 압축: 'gzip', 데이터: gz, 원래크기: made.size } : { 진단: made.data };
        var r = await transport.send({ 종류: '진단', 본문: body });
        if (!r || !r.ok) {
          setStatus('진단을 보내지 못했습니다: ' + ((r && r['오류']) || '응답 없음') + (r && r['코드'] === '연결필요' ? ' — 확장 연결부터' : ''), 'error');
          return;
        }
        var d = r['데이터'] || {};
        var s = made.data['구조'];
        setStatus('진단을 보냈습니다(요소 ' + s['요소수'] + '개' + (s['잘림'] ? ', 일부 잘림' : '') + '). Claude 에게 "진단 읽고 선택자 고쳐줘"라고 하세요. 저장: ' +
          (d['경로'] || '(서버)'), 'done');
        log('진단 저장: ' + (d['경로'] || '') + ' (' + formatBytes(made.size) + (gz ? ', 압축 ' + formatBytes(gz.length) : '') + ')');
      } catch (err) {
        setStatus('진단을 만들지 못했습니다: ' + String((err && err.message) || err), 'error');
      } finally {
        st.diagBusy = false;
        bDiag.disabled = false;
      }
    }

    async function stopNow() {
      if (st.mode === 'countdown') {
        clearTimeout(st.countdown);
        var r = await transport.send({ 종류: '결과', 본문: { 작업ID: st.job['작업ID'], 단계: '준비', 상태: '실패', 코드: '사람이멈춤', 메시지: '시작 전에 사람이 멈춤' } });
        st.failedStep = '준비';
        markStep('준비', '실패', '');
        setMode('failed');
        setStatus('시작 전에 멈췄습니다.' + (r && r.ok ? '' : ' (서버 보고 실패)'), 'warn');
      } else if (st.mode === 'running') {
        st.stop = true;
        setStatus('지금 단계가 끝나면 멈춥니다…', 'warn');
      }
    }

    // 보조 도구: 사진 묶음만 넣기
    var tl = { packages: [], bundles: null, busy: false };
    async function loadPackages() {
      list.textContent = '';
      pkgSelect.textContent = '';
      var r = await transport.send({ 종류: '목록' });
      if (!r || !r.ok) { list.append(el('li', { 'class': 'bh-empty' }, (r && r['오류']) || '서버에 연결할 수 없습니다.')); return; }
      tl.packages = (r['데이터'] || {})['목록'] || [];
      tl.packages.forEach(function (p, i) {
        pkgSelect.append(el('option', { value: String(i) }, (p['여행ID'] ? p['여행ID'] + ' · ' : '') + (p['제목'] || p['패키지']) + ' (' + p['묶음수'] + '묶음)'));
      });
      if (tl.packages.length) await loadBundles(0);
    }
    async function loadBundles(i) {
      list.textContent = '';
      var p = tl.packages[i];
      if (!p) return;
      var r = await transport.send({ 종류: '묶음', 주소: p['묶음주소'] });
      if (!r || !r.ok || String(i) !== pkgSelect.value) return;
      tl.bundles = r['데이터'];
      (tl.bundles['묶음'] || []).forEach(function (b) {
        var li = el('li', { 'class': 'bh-item', 'data-bundle': String(b['번호']) });
        li.append(el('div', { 'class': 'bh-meta' }, '묶음 ' + b['번호'] + ' · ' + b['방식'] + ' · ' + b['장수'] + '장 · ' + formatBytes(b['합계크기'])));
        (b['경고'] || []).forEach(function (w) { li.append(el('div', { 'class': 'bh-warn' }, '주의: ' + w)); });
        var btn = el('button', { type: 'button', 'class': 'bh-btn bh-insert', 'data-bh': 'insert', 'data-bundle': String(b['번호']),
          'aria-label': '묶음 ' + b['번호'] + ' 넣기 (' + b['방식'] + ', ' + b['장수'] + '장)' }, '묶음 ' + b['번호'] + ' 넣기');
        if (!b['장수']) btn.disabled = true;
        li.append(btn);
        list.append(li);
      });
    }
    async function insertBundle(n) {
      if (tl.busy || st.mode === 'running') return;
      var b = ((tl.bundles || {})['묶음'] || []).filter(function (x) { return String(x['번호']) === String(n); })[0];
      if (!b) return;
      if ((b['거절'] || []).length) {
        setStatus('묶음 ' + n + ': 위치·기기 정보 등이 남은 사진이 있어 넣지 않습니다(' + b['거절'].map(function (x) { return x['이름']; }).join(', ') +
          ') — 업로드 사본을 다시 만드세요.', 'error');
        return;
      }
      tl.busy = true;
      try {
        var files = await fetchBundleFiles(transport, b, function (i, k) { setStatus('사진 받는 중 (' + i + '/' + k + ')', 'busy'); });
        var res = await insertFiles(files, { doc: doc, method: methodSelect.value, onLog: log });
        if (res.ok) {
          setStatus('묶음 ' + n + ' 넣기 완료 — 방법 (' + res['방법'] + '). ' + (files.length > 1 ? "네이버 창에서 '" + b['방식'] + "'를 고르세요(사람). " : '') +
            ((res['주의'] || []).length ? '주의: ' + res['주의'].join(' / ') : ''), 'done');
        } else if (res['확인필요']) {
          setStatus('묶음 ' + n + ': 확인 필요 — 사진 칸에 넣었지만 화면에 안 보입니다. 네이버 화면을 확인하세요.', 'warn');
        } else {
          setStatus('묶음 ' + n + ': 이 방법으로는 안 됨. ' + (res['시도'] || []).map(function (t) { return '(' + t['방법'] + ') ' + t['사유']; }).join(' / ') +
            ". 네이버의 '사진' 버튼으로 직접 올리세요" + (b['폴더'] ? ' — 사진 위치: ' + b['폴더'] : '') + '.', 'error');
        }
      } catch (err) {
        setStatus('묶음 ' + n + ': ' + (err.message || err), 'error');
      } finally {
        tl.busy = false;
      }
    }

    panel.addEventListener('click', function (e) {
      if (!e.isTrusted) return;  // (위의 잡기와 함께 한 번 더)
      var btn = e.target.closest('button[data-bh]');
      if (!btn || btn.disabled) return;
      var what = btn.getAttribute('data-bh');
      if (what === 'start-now') { clearTimeout(st.countdown); run(st.job, false); }
      else if (what === 'stop') stopNow();
      else if (what === 'retry') retryFrom(st.failedStep, false);
      else if (what === 'human') retryFrom(st.failedStep, true);
      else if (what === 'check') poll(true);
      else if (what === 'refresh') loadPackages();
      else if (what === 'diag') sendDiag();  // 사람 클릭으로만(위에서 isTrusted 확인)
      else if (what === 'insert') insertBundle(btn.getAttribute('data-bundle'));
      else if (what === 'side') panel.classList.toggle('bh-left');
      else if (what === 'toggle') {
        var collapsed = panel.classList.toggle('bh-collapsed');
        toggleBtn.textContent = collapsed ? '펼치기' : '접기';
        toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        toggleBtn.setAttribute('aria-label', collapsed ? '패널 펼치기' : '패널 접기');
      }
    });
    pkgSelect.addEventListener('change', function (e) { if (e.isTrusted) loadBundles(Number(pkgSelect.value)); });
    // 목록은 사람이 '사진 묶음만 넣기'를 눌러 펼칠 때만 받음('toggle' 이벤트는 스크립트가 open 을 바꿔도 생기므로 쓰지 않음)
    toolSummary.addEventListener('click', function (e) {
      if (e.isTrusted && !tool.open && !tool.hidden && !tl.packages.length) loadPackages();
    });

    setMode('idle');
    poll(false);
    st.timer = setInterval(function () { poll(false); }, S.timing.pollMs);
    return panel;
  }

  // ── 6. 시작 ────────────────────────────────────────────────────────────
  /** 바깥 화면에서: 안쪽 에디터 프레임에 패널이 끝내 안 뜨면 실측용 표시(shell-no-panel)와 콘솔 안내를 남김 */
  async function watchInnerPanel() {
    await rawSleep(S.timing.editorWaitMs + 2000);
    var found = first(document, S.shellIframe);
    var innerDoc = null;
    try { innerDoc = found && found.el.contentDocument; } catch (_) { innerDoc = null; }
    if (innerDoc && !innerDoc.getElementById(PANEL_ID)) {
      mark('shell-no-panel');
      console.warn('[블로그 도우미] 에디터 프레임에 패널이 뜨지 않았습니다. 안쪽 프레임 주소(' +
        (innerDoc.location ? innerDoc.location.href : '?') + ')가 manifest.json 의 matches 에 있는지, ' +
        'selectors.js 의 editorRoot 가 맞는지 확인하세요.');
    }
  }

  async function boot() {
    if (!isWriteUrl(location.href)) return; // 글쓰기 화면이 아니면 아무것도 안 함
    mark('waiting');
    var deadline = Date.now() + S.timing.editorWaitMs;
    while (Date.now() < deadline) {
      var role = frameRole(document);
      if (role === 'shell') {
        mark('shell'); // 에디터는 안쪽 iframe 에 있음 → 그 프레임의 도우미가 패널을 띄움
        watchInnerPanel();
        return;
      }
      if (role === 'editor' && window.innerWidth >= 400 && window.innerHeight >= 200) {
        mark('editor');
        document.addEventListener('pointerdown', rememberPoint, true);
        mountPanel({});
        return;
      }
      await rawSleep(500);
    }
    mark('no-editor');
  }

  // 테스트 하네스(모의에디터.html)에서 확장 없이 같은 함수를 쓰도록 공개.
  // 확장 안에서는 확장 전용 세계(isolated world)의 전역이라 네이버 페이지에서는 보이지 않습니다.
  globalThis.BlogHelper = {
    version: VERSION,
    collectDiagnostics: collectDiagnostics,
    insertFiles: insertFiles,
    tryFileInput: tryFileInput,
    tryDrop: tryDrop,
    snapshot: snapshot,
    frameRole: frameRole,
    isWriteUrl: isWriteUrl,
    mountPanel: mountPanel,
    rememberPoint: rememberPoint,
    runJob: runJob,
    reserveAllowed: reserveAllowed,
  };

  if (IS_EXTENSION) boot();
})();
