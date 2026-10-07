#!/bin/bash
# 여행 스튜디오 실행 (Mac) — 더블클릭하면 서버를 켜고 브라우저로 화면을 엽니다.
#
# ▶ 처음 한 번은 '실행 권한'을 줘야 더블클릭으로 열립니다. 터미널에서:
#      chmod +x 스튜디오실행.command
#    (이 파일이 있는 폴더에서. 또는 'chmod +x ' 를 치고 이 파일을 터미널 창으로 끌어다 놓기)
# ▶ '확인되지 않은 개발자' 경고가 뜨면: 파일을 Control+클릭 → [열기] → [열기].
# ▶ 바탕화면 아이콘은 'python3 바탕화면아이콘만들기.py' 로 만듭니다(이 폴더 경로가 들어간 사본).
# ※ Mac 실기에서는 아직 확인하지 못했습니다(실기 미확인).

# 바탕화면 사본은 아래 STUDIO_DIR 에 이 폴더의 절대 경로가 들어갑니다.
STUDIO_DIR="${STUDIO_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$STUDIO_DIR" || { echo "폴더를 찾지 못했어요: $STUDIO_DIR"; read -r -p "Enter 를 누르면 닫힙니다"; exit 1; }

if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "python3 가 없어요. python.org 에서 Python 을 설치한 뒤 다시 열어 주세요."
  read -r -p "Enter 를 누르면 닫힙니다"
  exit 1
fi

"$PY" "$STUDIO_DIR/스튜디오실행.pyw" "$@"
echo "여행 스튜디오를 열었어요: http://localhost:8765"
echo "이 터미널 창은 닫아도 됩니다(서버는 계속 켜져 있어요)."
