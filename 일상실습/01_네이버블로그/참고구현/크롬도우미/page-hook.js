/*
 * 블로그 도우미 — 페이지 쪽 작은 갈고리 (MAIN world, document_start)
 * ---------------------------------------------------------------------------
 * 왜 필요한가?
 *   공개 자료에 따르면 네이버 에디터의 '사진' 버튼은 누르는 순간 file input을 만들어
 *   곧바로 파일 선택 창을 엽니다. 그 input이 문서에 붙지 않는 경우도 있어
 *   (selectors.js [C3]) 확장 쪽(content.js)에서는 그 input을 찾을 수 없습니다.
 *
 * 무엇을 하나?
 *   content.js 가 '넣기'에서 사진 칸을 구하는 몇 초 동안만, 페이지가 file input을
 *   열려고(click / showPicker / click 이벤트 보내기) 하면 파일 선택 창을 열지 않고 그 input에 표시를 붙여
 *   content.js 가 찾을 수 있게 문서에 잠깐 붙여 둡니다.
 *   그 밖의 시간에는 원래 동작을 그대로 합니다(사람이 사진 버튼을 누르면 평소처럼 창이 열림).
 *
 * 하지 않는 것: 네트워크 요청, 데이터 읽기·보내기, 다른 기능 변경. 이 파일은 이것뿐입니다.
 *
 * content.js 와의 약속(둘은 서로 다른 '세계'라 DOM 속성과 이벤트로만 이야기합니다)
 *   - <html data-blog-helper-arm="만료시각(ms):난수">  : content.js 가 켜 둠(만료되면 자동 해제).
 *     검수 L6: 난수(16진 16자 이상)가 없거나 만료가 20초보다 먼 값은 무시(페이지가 오래 켜 두지 못하게)
 *   - 가로챈 input 에 data-blog-helper-captured="순번:난수" — content.js 는 이번 난수가 붙은 input 만 인정
 *     (페이지가 미리 심어 둔 가짜 input 은 무시. 같은 세계라 완전한 비밀은 아님 — 영향은 '파일 선택 창이 안 열림' 정도)
 *   - 문서에 없던 input 은 숨겨서 붙이고 data-blog-helper-attached="1"
 *   - document 에 'blog-helper:file-input' 이벤트를 보냄
 */
(function () {
  'use strict';
  if (window.__blogHelperPageHook) return;
  window.__blogHelperPageHook = true;

  var ARM = 'data-blog-helper-arm';
  // click 은 HTMLElement 에 정의되어 있으므로 거기서 가로챔(HTMLElement.prototype.click.call(input) 도 잡힘)
  var clickOwner = HTMLElement.prototype;
  var originalClick = clickOwner.click;
  var proto = HTMLInputElement.prototype;
  var originalShowPicker = proto.showPicker;
  var originalDispatch = EventTarget.prototype.dispatchEvent;
  var seq = 0;

  var MAX_ARM_MS = 20000;

  /** 켜져 있으면 그 난수, 아니면 null */
  function armed() {
    var v = document.documentElement && document.documentElement.getAttribute(ARM);
    if (!v) return null;
    var i = String(v).indexOf(':');
    if (i < 0) return null;
    var until = Number(String(v).slice(0, i));
    var nonce = String(v).slice(i + 1);
    var left = until - Date.now();
    if (!(left > 0) || left > MAX_ARM_MS || !/^[0-9a-f]{16,64}$/.test(nonce)) return null;
    return nonce;
  }

  function isFileInput(el) {
    return !!el && el.tagName === 'INPUT' && String(el.type).toLowerCase() === 'file';
  }

  function capture(input, nonce) {
    seq += 1;
    input.setAttribute('data-blog-helper-captured', String(seq) + ':' + nonce);
    if (!input.isConnected) {
      input.style.display = 'none';
      input.setAttribute('data-blog-helper-attached', '1');
      (document.body || document.documentElement).appendChild(input);
    }
    document.dispatchEvent(new CustomEvent('blog-helper:file-input'));
  }

  clickOwner.click = function () {
    var nonce = isFileInput(this) ? armed() : null;
    if (nonce) {
      capture(this, nonce);
      return undefined; // 파일 선택 창을 열지 않음
    }
    return originalClick.apply(this, arguments);
  };

  // input.dispatchEvent(new MouseEvent('click')) 로 여는 경우(문서에 없는 input)도 넣기 중에만 가로챔
  EventTarget.prototype.dispatchEvent = function (event) {
    var nonce = event && event.type === 'click' && isFileInput(this) ? armed() : null;
    if (nonce) {
      capture(this, nonce);
      return false;
    }
    return originalDispatch.apply(this, arguments);
  };

  if (typeof originalShowPicker === 'function') {
    proto.showPicker = function () {
      var nonce = isFileInput(this) ? armed() : null;
      if (nonce) {
        capture(this, nonce);
        return undefined;
      }
      return originalShowPicker.apply(this, arguments);
    };
  }
})();
