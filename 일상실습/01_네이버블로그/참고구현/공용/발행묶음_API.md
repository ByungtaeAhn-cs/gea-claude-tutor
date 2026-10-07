# 발행 묶음 API (v1) → `발행API.md` (v2) 로 옮겼습니다

- v1 의 묶음·파일 응답 형식은 **`공용/발행API.md` 4절**에 그대로 흡수했습니다(필드 `여행` → `여행ID`, `편ID` 추가, 파일 주소 `/api/발행/파일?…`).
- v2 부터 확장 요청에는 연결 토큰(`X-Blog-Helper-Token`)이 필요하고, 발행 작업 API 가 생겼습니다(`발행API.md` 3·5~8절).
- 기준 구현: `공용/발행서버.py` 의 `build_bundles()` · `PublishAPI` (직접 구현하지 말고 import — `발행API.md` 10절).
