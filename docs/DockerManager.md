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
| `local` | 로컬 OpenAI 호환 이미지 서버(LocalAI 등)로 생성 후 동일한 후처리 | 서버에 설치된 이미지 모델 |

- `MAINFLOW_OPENAI_IMAGE_MODEL`: 모델, 기본값 `gpt-image-2` (`gpt-image-1`은 2026-10-23 서비스 종료)
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

### 로컬 이미지 서버 (`local`)

LocalAI처럼 `/v1/images/generations`를 제공하는 OpenAI 호환 서버에 연결한다. 팀 LocalAI가 기본으로
올리는 Gemma는 텍스트 모델이라 이미지를 만들 수 없으므로, 같은 서버에 이미지 모델(예:
LocalAI 갤러리의 `flux.1-dev-ggml`)을 설치하고 그 이름을 지정해야 한다.

| 변수 | 설명 | 기본값 |
|---|---|---|
| `MAINFLOW_LOCAL_IMAGE_MODEL` | 서버에 설치된 이미지 모델 이름 (필수) | 없음 |
| `MAINFLOW_LOCAL_IMAGE_BASE_URL` | 이미지 서버 주소 | `LOCAL_LLM_BASE_URL`, 없으면 `http://127.0.0.1:8080/v1` |
| `LOCAL_LLM_API_KEY` | 서버가 키를 요구할 때만 사용 | 없음 |
| `MAINFLOW_LOCAL_IMAGE_SIZE` | 생성 크기 | `512x512` |
| `MAINFLOW_LOCAL_IMAGE_STEPS` | diffusion step 수 | 서버 기본값 |
| `MAINFLOW_LOCAL_IMAGE_TIMEOUT_SECONDS` | 요청 제한 시간 | `600` |

로컬 diffusion 모델은 투명 배경을 출력하지 못하므로 스프라이트·초상화·UI는 흰 단색 배경으로
요청한 뒤 후처리에서 배경을 제거한다. `Custom` 참고 이미지는 로컬 서버로 전달하지 않는다.

```powershell
$env:MAINFLOW_IMAGE_BACKEND = "local"
$env:MAINFLOW_LOCAL_IMAGE_MODEL = "flux.1-dev-ggml"
uv run --locked python -m mainflow.run_flow `
  --image-style "Pixel Art" `
  --mood-style Fantasy `
  --genre "플랫포머" `
  --viewpoint "사이드뷰" `
  --condition "점프와 공격이 가능한 게임"
```

### 캐릭터 애니메이션 스프라이트 시트

플레이어·캐릭터·적 스프라이트는 기본 이미지와 함께 애니메이션 시트를 만든다. 애니메이션마다
프레임을 만드는 방식(`source`)을 고르며, `MAINFLOW_IMAGE_SPRITE_SHEET_MODE`로 정한다.

| 모드 | 동작 |
|---|---|
| `auto` (기본) | 백엔드가 지원하면 `ai`, 아니면 `transform` |
| `ai` | 기본 스프라이트를 참조 이미지로 넘겨 애니메이션 하나를 한 줄(strip)로 생성한 뒤 프레임으로 분리. 실제 자세(팔다리)가 바뀐다. 현재 `openai` 백엔드가 지원하며 캐릭터당 애니메이션 수만큼 API 호출이 추가된다. |
| `transform` | 기본 스프라이트를 정수 픽셀 연산(위아래 이동, 행 단위 기울임, 행 삭제·복제로 웅크림/늘어남, 다리 벌림)으로 변형. 회전·비정수 리사이즈가 없어 도트가 깨지지 않고 API 비용이 없다. |

`ai` 프레임은 다음 후처리를 거친다.

- 흰 배경이면 제거하고, 빈 열을 기준으로 프레임을 분리한다. 지팡이 끝처럼 얇게 맞닿은 프레임은
  가장 얇은 열에서 자른다.
- 몸통 중심으로 가로 정렬하고 발을 기준선에 맞춘다. 12% 이내의 크기 차이는 같은 높이로 맞추고,
  웅크림처럼 큰 차이는 유지한다.
- Pixel Art는 모든 프레임을 기본 스프라이트 팔레트로 고정한다.
- 프레임 수가 맞지 않거나(겹침), 색이 기본 스프라이트와 크게 다르거나, API가 실패하면 그
  애니메이션만 `transform`으로 대체하고 사유를 메타데이터 `fallbacks`와 draft `notes`에 남긴다.

애니메이션 캐릭터의 기본 스프라이트는 "전신, 오른쪽을 바라봄, 팔다리가 보이는 중립 자세, 소품은 몸에
붙게"로 요청해 프레임 생성에 적합한 자세를 만든다. `MAINFLOW_IMAGE_SPRITE_SHEETS=off`로 시트 생성
자체를 끌 수 있다.

| 장르 | 애니메이션 |
|---|---|
| 플랫포머 | `idle`(4), `run`(6), `jump`(3: 도약·체공·착지) |
| 뱀서류 | `idle`(4), `walk`(6), `hit`(3) |
| 타워 디펜스 | `walk`(6), `hit`(3) |

에셋 요청에 애니메이션 목록 필드가 생기기 전까지 위 장르별 기본값을 사용한다. 투사체·타워·타일·
배경·UI·초상화는 시트를 만들지 않는다.

```text
generated/images/platformer_player.png          # 기존 단일 스프라이트 (asset_id 그대로)
generated/images/platformer_player_sheet.png    # 애니메이션별 1행, 프레임 64x64
generated/images/platformer_player_sheet.json   # Unity 슬라이싱·클립 생성용 메타데이터
```

```json
{
  "asset_id": "platformer_player",
  "unity_binding_key": "asset_registry:platformer_player",
  "frame_width": 64, "frame_height": 64, "columns": 6, "rows": 3,
  "pivot": [0.5, 0.0],
  "sheet_relative_path": "generated/images/platformer_player_sheet.png",
  "animations": {
    "idle": {"row": 0, "frames": 4, "fps": 6, "loop": true, "source": "ai"},
    "run": {"row": 1, "frames": 6, "fps": 12, "loop": true, "source": "ai"},
    "jump": {"row": 2, "frames": 3, "fps": 10, "loop": false, "source": "transform"}
  },
  "fallbacks": {"jump": "ValueError: expected 3 frames in the strip, found 2"}
}
```

`pivot`은 발밑 중앙이며 모든 프레임의 발 위치가 같은 높이에 맞춰져 있다. `image_draft.json`의
`notes`에는 `sprite_sheet:{asset_id}={시트 artifact_id},{메타데이터 artifact_id}`가 기록되고
`validate_image`가 격자 크기, 빈 프레임, 프레임 간 캐릭터 높이를 검사한다.

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
