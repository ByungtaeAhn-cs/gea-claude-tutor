/*
 * 블로그 도우미 — 네이버 SmartEditor ONE 선택자·방법 모음 (화면이 바뀌면 이 파일만 고칩니다)
 * ---------------------------------------------------------------------------
 * 각 목록은 앞에서부터 시도하고, (보이는 것이 필요한 곳은) 처음 '보이는' 것을 씁니다.
 * 이 파일을 만든 날(2026-10-07)에는 실제 네이버 화면을 열지 않았습니다(로그인 금지).
 * 아래 값은 공개 자료의 단서이며, 모두 강사 실측으로 확인해야 합니다.
 *   [실측 단서] = 출처가 '실측했다'고 적은 값(우리가 확인한 것은 아님)
 *   [추정]      = 이름 규칙으로 짐작한 값
 *   [미실측]    = 단서가 없음. 실측 때 반드시 채울 것
 * Claude Code 에게: "블로그 도우미 선택자를 지금 화면에 맞게 고쳐줘" → 이 파일만 고치면 됩니다.
 *
 * 출처
 *  [N1] 네이버 블로그 고객센터 도움말 #15468(사진·끌어다 놓기), #15528(그룹 사진: 개별 사진/콜라주/슬라이드),
 *       #15515(글 유형: 소제목/본문/인용구), #15533(장소, 1회 5곳), #15541(발행 설정: 카테고리·공개·태그·예약)
 *       https://help.naver.com/service/5593/contents/15528?lang=ko (강사자료 01 문서 4절 요약)
 *  [C1] space-cap/naver-blog-mcp docs/image-upload-research.md (2025) — mainFrame, 사진 버튼, input#hidden-file
 *  [C2] HITENEKEN/blog-auto-poster src/platforms/naver/NaverBrowserPoster.ts (2026-09-21 커밋)
 *       — /{id}/postwrite, .se-container .se-canvas, 숨은 input_buffer 프레임에 paste 이벤트를 던지면
 *         본문 모듈이 만들어짐("라이브 검증"), 태그는 발행 설정 레이어 안 input#tag-input
 *  [C3] bam-bam-2/solo-skills skills/naver-branding-post/SKILL.md (2026-09-13 커밋)
 *       — 페이지에 input[type=file] 없음, .se-text-format-toolbar-button → sectionTitle/quotation,
 *         .se-insert-horizontal-line-default-toolbar-button, 스크립트 선택 범위는 에디터가 안 받음
 *  [C4] kwanwon/naver-blog-automation naver_blog_auto_image.py (2025-06) — ul.se-image-type-list, label.se-image-type-label
 *  [C5] GPTers "네이버 블로그 자동화 실습"(통설) — 여러 장이면 '사진 첨부 방식' 선택 창
 *  [C6] saeu5407/blog-publisher engines/naver/naver_blog_mcp/selectors.py (2026-09-28 커밋, 파일에 "2026-08-25 실측")
 *       — 제목·본문 data-a11y-title, 발행 레이어(div[class*=layer_publish]) 안의 카테고리·공개(#open_*)·태그,
 *         저장(tpb.save)·저장 개수(save_count_btn, aria-label "임시저장된 글 보기, N개"),
 *         장소 팝업(.se-popup-placesMap …), 사진 설명 .se-caption, 도움말 패널, 보호조치 문구.
 *         "레이어를 여는 것만으로는 발행되지 않는다 — 최종 발행은 확인 버튼"
 *  [C7] baessu/naver-blog-uploader, gangj277/tam-landing, Hajin74/naver-blog-bot — 인용구·구분선 툴바 버튼 이름
 */
(function () {
  'use strict';

  globalThis.BLOG_HELPER_SELECTORS = {
    // ── 1. 글쓰기 화면 주소 (manifest.json 의 matches 와 짝) ──────────────
    writeUrl: [
      /[?&]Redirect=Write/i,              // blog.naver.com/{id}?Redirect=Write  [C1][C6]
      /\/postwrite(?:[/?#]|$)/i,          // blog.naver.com/{id}/postwrite       [C2]
      /\/PostWriteForm\.naver/i,          // mainFrame 안쪽 주소                  [C1]
      /\/GoBlogWrite\.naver/i,            // [추정]
    ],

    // ── 2. 프레임·에디터 ─────────────────────────────────────────────────
    shellIframe: ['iframe#mainFrame', 'iframe[name="mainFrame"]'],               // [C1][C6]
    editorRoot: [
      '.se-container .se-canvas',         // [C2] 2026-09
      '.se-main-container',
      '.se-component.se-documentTitle',
      '.se-documentTitle',
      '.se-content',                      // [C3]
    ],
    // 숨은 입력 프레임: 모듈을 클릭하면 포커스가 이 안의 contenteditable 로 감 [C2]
    inputBuffer: ["iframe[name^='input_buffer']", "iframe[id^='input_buffer']"],

    // ── 3. 제목·본문 ─────────────────────────────────────────────────────
    title: ["[data-a11y-title='제목'] .se-text-paragraph", "[data-a11y-title='제목']",
            '.se-documentTitle .se-text-paragraph', '.se-section-documentTitle .se-module-text'],   // [C6][C2]
    placeholder: ['.se-placeholder'],                                                           // [C6]
    bodyParagraph: ["[data-a11y-title='본문'] .se-text-paragraph", '.se-component.se-text .se-text-paragraph',
                    '.se-component-content .se-text-paragraph'],                                // [C6]
    docComponent: ['.se-component'],                                                            // [C6]
    // 글 유형(본문/소제목/인용구) [N1][C3][C7]. '본문' 옵션 이름은 [추정]
    textFormatButton: ['button.se-text-format-toolbar-button', "button[data-name='text-format']"],
    textFormatOption: {
      '본문': ['button.se-toolbar-option-text-format-text-button', "button[data-value='text']"],
      '소제목': ['button.se-toolbar-option-text-format-sectionTitle-button', "button[data-value='sectionTitle']"],
      '인용구': ['button.se-toolbar-option-text-format-quotation-button', "button[data-value='quotation']"],
    },
    // 글 넣는 방법(앞에서부터 시도, 넣은 뒤 화면 글자로 확인). '방법 표'는 README 참고
    //   paste       : 숨은 입력 프레임(없으면 지금 포커스)에 paste 이벤트(clipboardData: text/html+text/plain) [C2 라이브 검증]
    //   execCommand : document.execCommand('insertText') — 브라우저가 진짜 입력 이벤트를 만듦 [추정]
    textMethods: { title: ['execCommand', 'paste'], body: ['paste', 'execCommand'] },
    newParagraphMethods: ['execCommand'],   // execCommand('insertParagraph') [추정]

    // ── 4. 구분선 ────────────────────────────────────────────────────────
    dividerButton: ['button.se-insert-horizontal-line-default-toolbar-button', "button[data-name='horizontal-line']"],  // [C3][C7]
    dividerComponent: ["[data-a11y-title='구분선']", '.se-component.se-horizontalLine'],                               // [추정]

    // ── 5. 사진(방법 a: 사진 버튼 + 파일 칸, 방법 b: 끌어다 놓기) ──────────
    photoButton: ["button[data-name='image'].se-image-toolbar-button", 'button.se-image-toolbar-button',
                  "button[data-name='image']", 'button[title="사진"]'],                     // [C6][C1][C2]
    photoButtonEvents: ['click'],
    fileInput: ['input[type="file"]#hidden-file', 'input[type="file"][accept*="jpg" i]', 'input[type="file"][accept*="image" i]'],
    allowAnyFileInput: false,
    dropTarget: ['.se-container .se-canvas', '.se-content.__se-scroll-target', '.se-content', '.se-main-container', '.se-container'],
    insertedImage: ["[data-a11y-title='사진']", 'img.se-image-resource', '.se-module-image img', 'div.se-image-container img',
                    '.se-component.se-image', '.se-component.se-imageStrip', '.se-component.se-imageGroup'],  // [C6][C2][C4] + [추정]
    imageComponent: ["[data-a11y-title='사진']", '.se-component.se-image', '.se-component.se-imageStrip', '.se-component.se-imageGroup'],
    // 여러 장일 때 배치 선택 창 [N1][C4][C5] — 이제 확장이 '방식'에 맞는 것을 고름
    layoutPopup: ['ul.se-image-type-list', 'label.se-image-type-label'],
    layoutOption: ['label.se-image-type-label'],
    layoutText: { '개별 사진': ['개별 사진', '개별사진'], '콜라주': ['콜라주'], '슬라이드': ['슬라이드'] },
    layoutConfirm: ['button.se-popup-button-confirm', 'button.se-image-dialog-btn-submit', 'button.se-dialog-btn-submit'],  // [C4]
    // 사진 설명: 사진을 클릭해야 보이고, 설명 칸을 한 번 더 클릭해야 입력됨 [C6]
    imageCaption: ['.se-caption .se-text-paragraph', '.se-caption', "[class*='se-caption']"],
    imageRepresentative: ['button.se-set-rep-image-button', "button[data-name='representative']", "button[aria-label*='대표']"], // [미실측]
    uploadProgress: [],                                                                     // [미실측]

    // ── 5-2. 동영상 [N1 #15530·#15491 — 1회 최대 10개, 본인인증 8GB·7시간 / 미인증 1GB·15분, mp4 등 13가지] ──
    // 흐름(추정): '동영상' 버튼 → 업로드 창 → '동영상 추가'(파일 선택 창 — 확장이 가로챔) → 업로드·인코딩 표시
    //            → (뜨면) 제목·설명 입력 창 → '완료' → 본문에 동영상 모듈. 전부 [미실측] — 실측 때 반드시 채울 것
    video: {
      button: ["button[data-name='video'].se-video-toolbar-button", 'button.se-video-toolbar-button', "button[data-name='video']"], // [추정] 사진 버튼 이름 규칙
      popup: ['.se-popup-video', "[class*='video_upload']", "[class*='VideoUpload']"],                                     // [미실측]
      addButton: ['button.se-video-add-button', "[class*='video'] button[class*='upload']", "[class*='video'] button[class*='add']"], // [미실측]
      fileInput: ["input[type='file'][accept*='video' i]", "input[type='file'][accept*='mp4' i]"],                         // [추정]
      processing: ['.se-video-uploading', "[class*='video'][class*='progress']", "[class*='video'][class*='encod']", "[class*='video'][class*='loading']"], // [미실측]
      error: ['.se-video-error', "[class*='video'][class*='error']", "[class*='video'][class*='fail']"],                  // [미실측]
      infoForm: ['.se-popup-video-info', "[class*='video'][class*='info']"],                                              // [미실측] 제목·설명 창
      titleInput: ['input.se-video-title-input', "[class*='video'] input[placeholder*='제목']", "[class*='video'] input[name*='title' i]"],
      descInput: ['textarea.se-video-desc-input', "[class*='video'] textarea", "[class*='video'] input[placeholder*='설명']"],
      done: ['button.se-popup-button-confirm', "[class*='video'] button[class*='confirm']", "[class*='video'] button[class*='submit']"],
      doneText: ['완료', '확인', '등록'],                                   // 이 글자와 정확히 같은 버튼만 누름(짐작 클릭 방지)
      component: ["[data-a11y-title='동영상']", '.se-component.se-video', ".se-component[class*='se-video']"],             // [추정]
    },

    // ── 6. 장소(멀티 첨부, 1회 5곳) [C6 실측 단서][N1] ──────────────────────
    place: {
      button: ["button[data-name='map']", 'button.se-map-toolbar-button'],
      popup: ['.se-popup-placesMap'],
      input: ['input.react-autosuggest__input', "input[placeholder*='장소']"],
      search: ['button.se-place-search-button'],
      resultItem: ['.se-place-map-search-result-item'],
      resultName: ['.se-place-map-search-result-title', "[class*='result-title']", 'strong'],   // [추정]
      add: ['button.se-place-add-button'],          // 항목에 마우스를 올려야 보임
      confirm: ['button.se-popup-button-confirm'],  // 추가 전에는 꺼져 있음
      component: ["[data-a11y-title='장소']", '.se-component.se-placesMap'],
    },

    // ── 7. 발행 설정 레이어(태그·카테고리·공개·예약) [C6 실측 단서][C2] ─────
    // 여는 버튼을 눌러도 발행되지 않고 레이어만 열림. 최종 발행은 confirm 버튼.
    publishOpen: ["button[data-click-area='tpb.publish']", "button[class*='publish_btn']"],
    publishLayer: ["div[class*='layer_publish']"],
    publishConfirm: ["button[data-testid='seOnePublishBtn']", "button[data-click-area='tpb*i.publish']", "button[class*='confirm_btn']"],
    publishLayerClose: ["div[class*='layer_publish'] button[class*='close']"],   // [미실측] — 없으면 Escape 키 이벤트
    tagInput: ['input#tag-input', "input[placeholder*='태그']"],
    tagChip: ["div[class*='layer_publish'] [class*='tag_item']", "div[class*='layer_publish'] [class*='tag__'] span"],  // [미실측]
    categoryOpen: ["button[data-click-area='tpb*i.category']", "button[aria-label='카테고리 목록 버튼']", "button[class*='selectbox_button']"],
    categoryItem: ["div[class*='option_category'] li[class*='item__']"],
    categoryChildMark: '하위 카테고리',
    visibility: {
      '전체 공개': ['#open_public'], '이웃 공개': ['#open_neighbor'],
      '서로이웃 공개': ['#open_both_neighbor'], '비공개': ['#open_private'],
    },
    // 'AI 활용' 설정 [미실측] — 위치를 모름. 아래 선택자가 비어 있으면 글자로 찾음(라벨·버튼·스위치)
    aiToggle: [],
    aiText: ['AI 활용'],
    // 예약 [N1][미실측] — 발행 시간 '예약' → 날짜·시·분(10분 단위)
    reserve: {
      radio: ['input#radio_time2', "input[name*='time'][value*='reserve' i]"],
      radioText: '예약',
      date: ["div[class*='layer_publish'] input[class*='date']", "div[class*='layer_publish'] input[type='date']"],
      dateFormat: 'YYYY. MM. DD.',
      hour: ["div[class*='layer_publish'] select[class*='hour']"],
      minute: ["div[class*='layer_publish'] select[class*='minute']"],
      done: ["button[class*='reserve']", "[class*='reserve_count']"],   // 에디터 위 '예약 발행 n건'
    },

    // ── 8. 저장(임시저장) [C6 실측 단서] ──────────────────────────────────
    saveButton: ["button[data-click-area='tpb.save']", "button[class*='save_btn']"],
    saveCount: ["button[class*='save_count_btn']"],
    saveToast: ["[class*='toast']", "[role='alert']"],

    // ── 9. 멈춰야 하는 화면 [C6] ─────────────────────────────────────────
    loginFrame: ["iframe[src*='nid.naver.com']"],
    barrierText: ['보호조치', '자동입력 방지문자', '비정상적인 접근'],
    captcha: ["iframe[src*='captcha' i]", "img[src*='captcha' i]", '#captcha'],
    helpPanel: ["[class*='se-help-panel']"],
    helpPanelClose: ['button.se-help-panel-close-button', "[class*='se-help-panel'] button[class*='close']"],
    blockingPopup: ['.se-popup-dim', '.se-popup'],   // '준비' 단계에서 보이면 멈춤(작성 중 글 복구 창 등)

    // ── 10. 클릭·시간 ─────────────────────────────────────────────────────
    clickEvents: ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'],
    timing: {
      editorWaitMs: 30000,    // 에디터가 그려질 때까지
      inputWaitMs: 3000,      // 사진 버튼을 누른 뒤 file input 이 생길 때까지
      effectWaitMs: 8000,     // (b) 끌어다 놓기 뒤 사진이 나타날 때까지
      deliveredWaitMs: 30000, // (a) 사진 칸에 넣은 뒤 사진이 나타날 때까지(업로드 포함)
      settleMs: 3000,         // 첫 사진이 보인 뒤 나머지가 보일 때까지
      verifyMs: 2500,         // 글을 넣은 뒤 화면에서 확인할 때까지
      layerMs: 6000,          // 발행 설정 레이어·팝업이 열릴 때까지
      stepMs: 90000,          // 단계 하나의 최대 시간(사진 단계는 4배)
      cancelWaitMs: 30000,    // 시간 초과된 단계가 실제로 멈출 때까지 기다리는 최대 시간(넘으면 그 단계가 끝날 때까지 새 작업 안 함)
      videoFetchMs: 600000,   // 동영상을 내 PC 서버에서 받는 최대 시간(10분)
      videoWaitMs: 1800000,   // 네이버 업로드·처리(인코딩)를 기다리는 최대 시간(30분)
      videoStepMs: 2700000,   // 동영상 단계 하나의 최대 시간(45분)
      beatMs: 60000,          // 오래 걸리는 단계에서 서버에 '살아 있음'(코드 처리중)을 보내는 간격
      pollMs: 10000,          // 대기 작업을 묻는 간격
      countdownMs: 5000,      // 작업을 받은 뒤 시작까지(사람이 멈출 수 있게)
    },
  };
})();
