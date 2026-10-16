# Local Web Manager

`CI/CD/LocalWeb`은 MainFlowChart를 브라우저에서 실행하기 위한 로컬 전용 웹 계층이다.
사용자 입력(계약 3.1.0)을 받아 LangGraph Workflow를 백그라운드에서 실행하고, Node 진행 상황·결과·생성 파일을 보여 준다.

## 제공 기능

- 로컬 웹 화면: `http://localhost:8000`
- FastAPI 문서: `http://localhost:8000/docs`
- 입력: 이미지 스타일, 분위기 스타일, 장르, 시점, 한 문장 조건, Custom 이미지(PNG/JPG, 10MB 이하)
- 실행: `mainflow.langgraph_game_flow_skeleton.build_graph()`를 그대로 사용하고 `graph.stream(stream_mode="updates")`로 Node 완료를 실시간 표시
- 결과: 게임 검증, 이미지·사운드 생성, 최종 검증 상태와 주요 issue
- 생성 파일: 프로젝트 manifest 목록과 개별 파일 다운로드(`ArtifactManager`가 크기·SHA-256 검증 후 반환)
- 실행은 한 번에 하나씩 순서대로 처리한다. 실행 중 추가 요청은 대기열에 들어간다.

입력값 검증은 CLI와 같은 `mainflow.run_flow.load_request()`를 사용하므로 웹과 CLI의 규칙이 항상 같다.

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/health` | 서버 상태, Workflow 연결 여부(`connected`/`unavailable`), 실행 중 여부 |
| GET | `/api/workflow` | 계약의 입력 선택지와 Graph Node 순서 |
| POST | `/api/runs` | multipart form으로 실행 요청. `202`와 `run_id` 반환, 잘못된 입력은 `422` |
| GET | `/api/runs` | 최근 실행 목록 |
| GET | `/api/runs/{run_id}` | 상태(`queued`/`running`/`succeeded`/`failed`), Node 이벤트, 결과, 오류 |
| GET | `/api/runs/{run_id}/artifacts` | 프로젝트 생성 파일 목록 |
| GET | `/api/runs/{run_id}/artifacts/{artifact_id}` | 파일 다운로드 |

`succeeded`인데 `outcome`이 `game_validation_failed`이면 Workflow는 끝까지 실행됐지만 Unity 검증을 통과하지 못한 것이다. CLI의 종료 코드 1과 같은 의미다.

## 디렉터리

```text
CI/CD/LocalWeb/
├─ app.py               # FastAPI 라우트, 입력 검증, Custom 이미지 저장
├─ workflow_runner.py   # 백그라운드 실행, Node 이벤트 수집, 결과 요약
├─ Dockerfile
├─ compose.yaml
├─ LocalWebManager.md
└─ static/
   ├─ index.html
   ├─ app.js
   └─ styles.css
```

## Docker로 실행

저장소 최상위 디렉터리에서 실행한다.

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" up --build
```

브라우저에서 `http://localhost:8000`을 열면 상단에 `Workflow 연결됨`이 표시된다.

종료:

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" down
```

이미지는 저장소 루트를 빌드 컨텍스트로 사용한다. 의존성은 루트의 `pyproject.toml`/`uv.lock`과 `web` 그룹(FastAPI)으로 설치하므로 Workflow 이미지와 버전이 같다. 의존성이나 Python 코드가 바뀌면 `--build`로 다시 빌드한다.

LLM 관련 환경변수(`GEMINI_API_KEY`, `LLM_PROVIDER`, `OPENAI_API_KEY`, `LOCAL_LLM_*` 등)는 루트 `compose.yaml`의 `mainflow` 서비스와 같은 이름으로 전달된다. 키가 없어도 기본 Workflow는 끝까지 실행된다.

Docker 포트는 호스트의 `127.0.0.1`에만 바인딩한다. 같은 네트워크의 다른 장치에서는 기본 설정으로 접근할 수 없다.

## Python으로 직접 실행

저장소 최상위 디렉터리에서 실행한다.

```powershell
uv sync --locked --group web
uv run --locked --group web python -m uvicorn app:app --app-dir CI/CD/LocalWeb --host 127.0.0.1 --port 8000 --reload
```

종료는 실행 중인 터미널에서 `Ctrl+C`를 누른다.

## 테스트

```powershell
uv run --locked --group web python -m unittest tests.test_local_web -v
```

테스트는 Graph를 간단한 stub으로 바꿔 실행·파일 목록·다운로드·입력 거부·실패 보고를 확인한다. `web` 그룹이 없으면 이 테스트는 건너뛴다.

## 포트 충돌

이미 8000번 포트를 사용하는 프로그램이 있으면 `compose.yaml`의 호스트 포트를 변경한다.

```yaml
ports:
  - "127.0.0.1:8001:8000"
```

이 경우 접속 주소는 `http://localhost:8001`이다. 루트 `compose.yaml`의 MCP 서버도 8001을 사용하므로 함께 띄운다면 다른 포트를 고른다.

## Workspace 연결

```text
호스트:    ./workspace
컨테이너: /app/workspace
```

웹에서 실행한 프로젝트는 CLI와 똑같이 `workspace/{project_id}/`에 생성된다. Custom 이미지는 `workspace/_uploads/upload-<id>/`에 저장한 뒤 그 경로를 Workflow 입력으로 전달한다.

## 현재 한계와 다음 단계

1. 실행 기록은 서버 메모리에만 있다. 컨테이너를 재시작하면 목록은 사라지지만 생성 파일은 `workspace`에 남는다.
2. Node 진행은 "완료" 이벤트 단위로 표시한다. 병렬 Node의 "실행 중" 상태와 Node 내부 로그 스트리밍은 아직 없다.
3. 프로젝트 ZIP 다운로드, 이미지·사운드 미리보기는 아직 없다.
4. 실행 취소 기능이 없다.

Agent Node와 결정적인 Graph Edge는 이 로컬 웹 계층에서 변경하지 않는다.
