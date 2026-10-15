# Docker Manager

Docker는 Python 3.11, uv, LangGraph 의존성을 동일하게 고정해 팀원이 별도 임시 환경 구성 없이
MainFlow를 실행하도록 한다. 호스트의 `workspace/`는 컨테이너 `/app/workspace`에 연결된다.
Compose는 같은 workspace를 사용하는 `mcp-server`를 함께 실행하고 MainFlow는
`http://mcp-server:8001/mcp`로 접속한다.

## 기본 실행

저장소 루트에서 실행한다.

```powershell
docker compose build
docker compose run --rm mainflow
```

MCP 서버만 실행하거나 상태를 확인할 때는 다음 명령을 사용한다.

```powershell
docker compose up --build mcp-server
Invoke-RestMethod http://127.0.0.1:8001/health
```

MCP endpoint는 `http://127.0.0.1:8001/mcp`이며 일반 REST endpoint가 아니라 MCP 클라이언트로
접속해야 한다. 자세한 사용법은 [`MCPManager.md`](MCPManager.md)를 따른다.

기본 요청은 다음과 같다.

```text
image_style = Pixel Art
mood_style  = Fantasy
genre       = 플랫포머
viewpoint   = 사이드뷰
condition   = 공격과 8방향 이동이 가능한 게임
```

입력값을 바꾸려면 다음처럼 명령을 덮어쓴다.

```powershell
docker compose run --rm mainflow `
  /app/.venv/bin/python -m mainflow.run_flow `
  --image-style Anime `
  --mood-style Cyberpunk `
  --genre "뱀서류" `
  --viewpoint "탑다운" `
  --condition "자동 공격과 성장 기능이 있는 게임"
```

Custom 참고 이미지는 저장소 안의 읽기 가능한 파일을 컨테이너 경로로 지정한다.

```powershell
docker compose run --rm mainflow `
  /app/.venv/bin/python -m mainflow.run_flow `
  --image-style Custom `
  --custom-image /app/examples/reference.png `
  --mood-style Medieval `
  --genre "타워 디펜스" `
  --viewpoint "탑다운" `
  --condition "타워를 배치해 적을 막는 게임"
```

## 이미지 생성 백엔드

`generate_image`는 게임 설계가 만든 `image_asset_request`의 이미지 에셋마다 PNG를 만든다.
생성기는 `MAINFLOW_IMAGE_BACKEND`로 고른다.

| 값 | 동작 | 필요 조건 |
|---|---|---|
| `placeholder` (기본) | 스타일별 도형 PNG를 결정적으로 생성 | 없음 |
| `openai` | OpenAI Images API로 생성 후 리사이즈·투명화·Pixel Art 팔레트 축소 | `OPENAI_API_KEY` |

- `MAINFLOW_OPENAI_IMAGE_MODEL`: 모델, 기본값 `gpt-image-1`
- `MAINFLOW_OPENAI_IMAGE_QUALITY`: `low | medium | high`, 기본값 `medium`
- `Custom` 스타일의 참고 이미지(`reference_image`)는 이미지 편집 endpoint로 함께 전달한다.
- 결과가 안전 필터에 차단되면 프롬프트를 바꿔 최대 3회 시도하고, 실패는 draft `notes`에 남긴다.

에셋 종류(스프라이트, 초상화, UI, 타일셋, 일러스트, 배경)는 `asset_id`가 아니라 요청의
`purpose`와 `description`으로 판단하며 종류에 따라 크기와 투명 배경 여부가 정해진다.
`unity_binding_key`와 생성하지 못한 필수 에셋은 계약에 전용 필드가 생기기 전까지 draft `notes`에
`unity_binding:`, `missing_required_asset:` 접두어로 기록한다.

```powershell
$env:MAINFLOW_IMAGE_BACKEND = "openai"
$env:OPENAI_API_KEY = "<개인 키>"
uv run --locked python -m mainflow.run_flow `
  --image-style "Pixel Art" `
  --mood-style Fantasy `
  --genre "플랫포머" `
  --viewpoint "사이드뷰" `
  --condition "점프와 공격이 가능한 게임"
```

Compose는 호스트 셸 또는 `.env`에서 위 변수를 읽는다. 실제 키는 저장소에 커밋하지 않는다.
테스트는 가짜 클라이언트를 사용하므로 API 키 없이 실행된다.

## 테스트

```powershell
docker compose --profile test run --rm test
```

## Local Web

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" up --build
```

브라우저에서 `http://localhost:8000`에 접속한다. 현재 Local Web은 입력 화면과 health API를
제공하는 골격이며 Workflow 실행 API는 아직 연결하지 않았다.

## 문제 해결

- Docker Desktop이 실행 중인지 확인한다.
- `docker version`과 `docker compose version`으로 설치 상태를 확인한다.
- 8000 포트 충돌 시 Local Web compose의 호스트 포트를 변경한다.
- 8001 포트 충돌 시 root `compose.yaml`의 MCP 호스트 포트를 변경한다.
- 실행 산출물은 컨테이너 삭제 후에도 호스트 `workspace/`에 남는다.
