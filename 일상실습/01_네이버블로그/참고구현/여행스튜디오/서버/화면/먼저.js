// 고른 화면 밝기(밝게/어둡게)를 그리기 전에 먼저 적용(깜빡임 방지). 고른 적 없으면 컴퓨터 설정을 따름.
// (index.html 안의 인라인 스크립트 대신 — 화면 CSP 가 인라인 스크립트를 막음)
try { var t = localStorage.getItem('여행스튜디오:테마'); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch (e) { /* 저장소를 못 써도 컴퓨터 설정대로 */ }
