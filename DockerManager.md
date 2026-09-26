# Docker and Runtime Guide

이 문서는 팀원이 저장소를 받은 뒤 동일한 Python/LangGraph 환경에서 MainFlowChart를 바로 실행하는 방법과 Docker 운영 규약을 설명한다.

## 1. 이번 구성에서 추가된 항목

| 파일 | 역할 |
|---|---|
| `pyproject.toml` | 지원 Python 버전과 직접 의존성 선언 |
| `uv.lock` | LangGraph를 포함한 전체 전이 의존성 버전 고정 |
| `.python-version` | 로컬 개발 Python 3.11 선택 |
| `Dockerfile` | Python 3.11과 잠긴 의존성을 포함한 실행 이미지 |
| `compose.yaml` | production 실행과 테스트 실행 서비스 |
| `.dockerignore` | 이미지에 로컬 환경·workspace 결과·비밀 파일이 들어가는 것을 차단 |
| `run_flow.py` | Tkinter 없이 실행하는 headless CLI |
| `request.example.json` | JSON 요청 형식 예시 |

`langgraph_game_flow_skeleton.py`의 Graph 노드와 Edge는 유지한다. `user_input_node`는 초기 State에 입력값이 있으면 GUI를 건너뛰고, 입력이 없을 때만 기존 Tkinter GUI를 표시한다.

## 2. 빠른 시작: Docker

### 준비 사항

- Git
- Docker Desktop 또는 Docker Engine + Compose plugin

저장소를 받은 뒤 루트에서 실행한다.

```powershell
git clone https://github.com/2026-2-CapstoneTeamIdle/MainFlowChart.git
cd MainFlowChart
docker compose build
docker compose run --rm mainflow
```

기본 입력값은 다음과 같다.

```text
image_style = Pixel Art
genre       = Action
quality     = Medium
```

실행이 끝나면 터미널에 `project_id`, 실제 project 경로, 최종 검증 결과와 State가 JSON으로 출력된다. 생성 파일은 컨테이너가 아니라 호스트의 `workspace/{project_id}`에 남는다.

현재 production Node에는 실제 AI/게임 엔진 연동 대신 TODO placeholder가 남아 있으므로 환경과 파일 전달은 정상 실행되지만 최종 검증 상태는 `pending`으로 출력된다. `tests/mock_nodes.py`를 사용하는 테스트에서는 실제 SVG, WAV, 게임 코드와 검증 로직을 넣어 최종 `passed`까지 확인한다. Docker는 실행 환경을 재현하는 장치이며 미구현 Agent 기능을 자동으로 구현하지는 않는다.

## 3. 입력값을 지정해 실행하기

Compose의 기본 command를 원하는 명령으로 교체한다.

```powershell
docker compose run --rm mainflow `
  /app/.venv/bin/python run_flow.py `
  --image-style Anime `
  --genre RPG `
  --quality High
```

PowerShell이 아닌 Bash에서는 줄 연결 문자로 `\`를 사용한다.

허용 값:

- `image_style`: `Pixel Art`, `Anime`, `Cartoon`, `Realistic`, `Low Poly`
- `genre`: `Action`, `RPG`, `Platformer`, `Puzzle`, `Simulation`
- `quality`: `Low`, `Medium`, `High`

JSON 파일로 실행할 수도 있다.

```powershell
docker compose run --rm mainflow `
  /app/.venv/bin/python run_flow.py `
  --request-file request.example.json
```

## 4. 테스트 실행

Docker에서 전체 테스트를 실행한다.

```powershell
docker compose --profile test run --rm test
```

테스트는 다음을 검증한다.

- 실제 LangGraph `StateGraph.compile().invoke()` 실행
- 운영 계약을 사용하는 12개 mock Node
- 이미지·게임·사운드 생성 병렬 처리
- 이미지·사운드 검증 병렬 처리
- 실제 SVG, WAV, Python mock 게임 파일 생성과 소비
- manifest 동시 갱신, SHA-256, 크기, 경로 안전성
- 최종 검증 `passed`

테스트 결과와 기준은 `tests/TestResult.md`에서 확인한다.

## 5. Docker 없이 로컬에서 실행하기

Docker를 사용하지 않는 팀원은 uv만 설치하면 된다.

```powershell
uv sync --locked
uv run --locked python run_flow.py `
  --image-style "Pixel Art" `
  --genre Action `
  --quality Medium
```

테스트 실행:

```powershell
uv run --locked python -m unittest discover -s tests -v
```

`uv.lock`을 사용하므로 팀원마다 임의의 LangGraph 버전을 설치하면 안 된다. `pip install langgraph`를 별도로 실행하지 않는다.

## 6. GUI 실행과 headless 실행의 차이

기존 파일을 직접 실행하면 입력 State가 없으므로 Tkinter GUI가 열린다.

```powershell
uv run --locked python langgraph_game_flow_skeleton.py
```

Docker 이미지에는 데스크톱 GUI 환경이 없으므로 반드시 `run_flow.py`를 사용한다. CLI가 초기 State를 전달하면 `user_input_node`가 Tkinter를 import하지 않고 바로 다음 단계로 진행한다.

## 7. Workspace와 파일 보존

Compose는 다음 bind mount를 사용한다.

```yaml
source: ./workspace
target: /app/workspace
```

따라서 컨테이너를 삭제해도 결과는 호스트에 보존된다.

```text
workspace/
└─ 20260926_03/
   ├─ generated/images/
   ├─ generated/sounds/
   ├─ game/
   ├─ data/artifact_manifest.json
   └─ validation/
```

`workspace`의 실행 결과는 Git에 커밋하지 않는다. Agent 간 파일 전달 규칙은 `FileSystem.md`, 데이터 계약은 `ContractRule.md`를 따른다.

Docker bind mount는 한 컴퓨터의 호스트와 컨테이너 사이에서만 파일을 공유한다. 서로 다른 팀원 컴퓨터가 같은 artifact를 동시에 사용해야 한다면 S3, MinIO, NAS 같은 원격 backend가 추가로 필요하다.

## 8. 의존성 변경 규칙

의존성을 추가하거나 갱신할 때는 uv를 사용한다.

```powershell
uv add <package>
uv lock
uv sync --locked
```

반드시 `pyproject.toml`과 `uv.lock`을 같은 커밋에 포함한다. Dockerfile에서 직접 `pip install`을 추가하지 않는다.

의존성 변경 후에는 다음을 모두 실행한다.

```powershell
uv run --locked python -m unittest discover -s tests -v
docker compose build --no-cache
docker compose --profile test run --rm test
```

## 9. 이미지 재빌드가 필요한 경우

다음 파일이 바뀌면 이미지를 다시 빌드한다.

- `pyproject.toml`
- `uv.lock`
- `Dockerfile`
- Python 소스 코드

```powershell
docker compose build
```

캐시를 완전히 무시하려면:

```powershell
docker compose build --no-cache
```

## 10. 운영 규약

1. production은 `uv.lock` 기준으로만 실행한다.
2. 비밀키는 이미지, State, workspace, manifest에 넣지 않는다.
3. `.env`는 로컬에서만 사용하고 Git 또는 Docker build context에 포함하지 않는다.
4. 컨테이너 안에서 생성된 artifact는 `/app/workspace` 아래에만 저장한다.
5. State에는 실제 파일 내용이나 절대 경로 대신 `ArtifactReference`를 전달한다.
6. Docker 서비스별로 임의의 의존성 설치를 하지 않는다.
7. Graph Edge 변경은 계약·테스트·문서를 함께 검토한다.
8. 테스트 성공 없이 `uv.lock` 또는 Dockerfile 변경을 병합하지 않는다.

## 11. 문제 해결

### `docker` 명령을 찾을 수 없음

Docker Desktop 또는 Docker Engine/Compose plugin을 설치한 뒤 새 터미널을 연다. 설치가 어려우면 `uv sync --locked` 방식으로 실행한다.

### `workspace` 쓰기 권한 오류

호스트의 `workspace` 폴더가 Docker Desktop 파일 공유 대상인지 확인한다. Windows에서는 저장소가 Docker Desktop에서 접근 가능한 드라이브에 있어야 한다.

### 기존 파일명 충돌

각 실행은 새로운 `project_id`를 생성해야 한다. 기존 project를 억지로 재사용하지 말고 새 실행을 시작한다.

### lockfile 불일치

```powershell
uv lock --check
uv sync --locked
```

`pyproject.toml`을 바꿨는데 `uv.lock`을 갱신하지 않은 경우 담당자가 두 파일을 함께 수정해야 한다.

### 결과 확인

터미널에 출력된 `project_root`를 열거나 다음 파일을 확인한다.

```text
workspace/{project_id}/data/artifact_manifest.json
workspace/{project_id}/validation/final_validation_result.json
```

## 12. 전달 전 체크리스트

- [ ] `pyproject.toml`과 `uv.lock`이 함께 커밋되어 있다.
- [ ] `uv sync --locked`가 성공한다.
- [ ] headless production Flow가 실제 LangGraph에서 실행된다.
- [ ] 전체 unittest가 통과한다.
- [ ] 가능하면 Docker build와 Docker test를 실행한다.
- [ ] `workspace` 결과와 `.env`가 Git에 포함되지 않았다.
- [ ] 실행법 또는 계약 변경을 관련 문서에 반영했다.
