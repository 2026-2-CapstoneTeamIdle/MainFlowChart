# Local Web Manager

`CI/CD/LocalWeb`은 MainFlowChart를 브라우저에서 확인하기 위한 로컬 전용 웹 골격이다.
현재 단계에서는 정적 입력 화면과 서버 상태 확인만 제공하며 LangGraph Workflow는 실행하지 않는다.

## 현재 제공 범위

- 로컬 웹 화면: `http://localhost:8000`
- FastAPI 문서: `http://localhost:8000/docs`
- 서버 상태 API: `http://localhost:8000/api/health`
- Workflow 입력 화면 골격
- 호스트 `workspace/`와 컨테이너 `/app/workspace` 연결

`/api/health`의 `workflow` 값이 `not_connected`인 것은 의도한 현재 상태다.

## 디렉터리

```text
CI/CD/LocalWeb/
├─ app.py
├─ requirements.txt
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

브라우저에서 다음 주소를 연다.

```text
http://localhost:8000
```

종료할 때는 다음 명령을 실행한다.

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" down
```

Docker 포트는 호스트의 `127.0.0.1`에만 바인딩한다. 같은 네트워크의 다른 장치에서는
기본 설정으로 접근할 수 없다.

## Python으로 직접 실행

Python 3.11 환경에서 다음 명령을 실행한다.

```powershell
Set-Location "CI/CD/LocalWeb"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

종료는 실행 중인 터미널에서 `Ctrl+C`를 누른다.

## 포트 충돌

이미 8000번 포트를 사용하는 프로그램이 있으면 `compose.yaml`의 호스트 포트를 변경한다.

```yaml
ports:
  - "127.0.0.1:8001:8000"
```

이 경우 접속 주소는 `http://localhost:8001`이다.

## Workspace 연결

Docker 실행 시 다음 두 경로가 연결된다.

```text
호스트:    ./workspace
컨테이너: /app/workspace
```

현재 웹 골격은 Workspace를 읽거나 변경하지 않는다. 이후 Workflow API를 연결하면 기존
`ArtifactManager`가 이 경로 아래에 프로젝트 파일을 생성한다.

## 다음 구현 단계

1. 웹 요청·응답 데이터 모델 정의
2. Workflow 실행 API 추가
3. `graph.stream()` 이벤트를 실행 상태로 변환
4. Artifact 목록과 미리보기 API 추가
5. 개별 파일 및 프로젝트 ZIP 다운로드 추가

Agent Node와 결정적인 Graph Edge는 이 로컬 웹 계층에서 변경하지 않는다.
