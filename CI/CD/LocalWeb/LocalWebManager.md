# Local Web Manager

버전: **1.1.0**

`CI/CD/LocalWeb`은 MainFlowChart를 `http://127.0.0.1:8000`에서 설정하고 실행하는 로컬
전용 웹 서비스다. 메인 LangGraph의 Edge는 바꾸지 않으며, 웹 계층이 Feature 승인 단계를
관리하고 승인된 `logic_analysis.json`을 기존 Flow에 전달한다.

## 제공 기능

- 실제 프로젝트 역할별 AI Provider/Model 선택
- LocalAI 등록 모델 목록 선택
- OpenAI, Gemini, Vast.ai, ElevenLabs API 키의 서버 전용 저장
- 실제 게임 이미지 에셋 백엔드(Placeholder/LocalAI/OpenAI)와 사운드 백엔드
  (Procedural/ElevenLabs) 선택
- 전체 **Generate**와 에셋 제외 **test-Generate**
- Condition → Feature 분석 결과 확인
- Confirm 시 표시된 Feature를 고정하여 생성 계속
- Reject 시 Condition → Feature 분석 재실행
- 분석, 생성, 컴파일, 기능 검증, 시각 검증의 진행 로그 표시
- 종료 시 `프로젝트 ID / 실패 단계 / 실패 Feature / 오류 요약`만 화면에 표시하고 전체
  Workflow JSON은 작업 파일로 별도 보존
- 게임 생성 성공 후 Unity WebGL Preview 자동 빌드
- Preview 준비 후 `Preview 플레이` 버튼으로 새 브라우저 탭에서 게임 실행
- Preview 빌드 실패/중단 상태를 게임 생성 결과와 분리하고 화면에서 재시도
- 검증 실패 작업도 Unity 프로젝트가 생성되었다면 진단용 WebGL Preview 수동 빌드·실행

## Generate 모드 차이

| 버튼 | 실행 범위 |
|---|---|
| Generate | 기존 운영 Graph 전체: 게임, 이미지, 사운드 생성·검증·적용과 최종 검증 |
| test-Generate | `--game-test`: 이미지·사운드 생성/검증/적용 제외, 모듈 합성 → 컴파일 → Feature Checklist → Visual Checklist |

두 모드 모두 먼저 `user_input → parse_input → analysis → logic_analysis`를 실행한다. 화면에
Feature가 표시된 뒤 사용자가 Confirm해야 나머지 단계가 시작된다.

## API 키 보안 경계

웹에서 입력한 키는 다음 무시된 로컬 파일에만 저장된다.

```text
workspace/.localweb/secrets.env
```

- API 응답은 키 값 대신 `configured: true/false`만 반환한다.
- 키를 Workflow State, 요청 JSON, 모델 프롬프트, 로그, Artifact에 기록하지 않는다.
- 실행 시 서버가 키를 자식 Python 프로세스 환경변수로만 전달한다.
- 역할/모델처럼 비밀이 아닌 설정은 `workspace/.localweb/settings.json`에 저장한다.
- 이 방식은 로컬 비밀의 Git 커밋을 막지만, PC 관리자나 같은 사용자 계정의 파일 접근까지
  막는 비밀 저장소는 아니다. 운영 서비스에서는 OS Secret Store 또는 Vault로 교체해야 한다.
- 로컬 HTTP이므로 포트는 반드시 `127.0.0.1`에만 바인딩한다.

기존 PowerShell 환경변수의 `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`VASTAI_INFERENCE_API_KEY`, `ELEVENLABS_API_KEY`도 사용할 수 있다. 화면에서 새 키를
저장하지 않으면 기존 키를 덮어쓰지 않는다.

## Docker 실행

저장소 최상위에서 실행한다.

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" up --build
```

브라우저:

```text
http://127.0.0.1:8000
```

종료:

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" down
```

Docker의 LocalWeb 컨테이너는 호스트 LocalAI를 기본적으로
`http://host.docker.internal:8080/v1`에서 찾는다. 다른 주소를 쓰면 실행 전에 지정한다.

```powershell
$env:LOCAL_LLM_BASE_URL = "http://host.docker.internal:8080/v1"
$env:LOCAL_IMAGE_BASE_URL = "http://host.docker.internal:8080/v1"
docker compose -f "CI/CD/LocalWeb/compose.yaml" up --build
```

LocalAI Compose와 함께 같은 Docker 네트워크에서 실행할 때는 서비스 주소에 맞춰
`http://Local-AIModel:8080/v1`을 사용할 수 있다.

## Python으로 직접 실행

저장소 최상위에서 기존 잠금 환경을 설치한 뒤 LocalWeb 의존성을 추가한다.

```powershell
uv sync --locked
uv pip install --python .venv\Scripts\python.exe -r "CI/CD/LocalWeb/requirements.txt"
uv run --locked python -m uvicorn --app-dir "CI/CD/LocalWeb" app:app `
  --host 127.0.0.1 --port 8000 --reload
```

실행을 끝낼 때는 터미널에서 `Ctrl+C`를 누른다.

### WebGL Preview 사전 조건

Preview는 생성된 Unity 프로젝트를 실제 WebGL 플레이어로 빌드한다. LocalWeb을 실행하는
컴퓨터에 다음 항목이 필요하다.

1. Unity Editor
2. 같은 Editor 버전의 **WebGL Build Support** 모듈
3. 해당 컴퓨터에서 활성화된 Unity 라이선스

Editor를 자동으로 찾지 못하면 LocalWeb 서버를 시작한 PowerShell에서 경로를 지정한다.
프로젝트 버전의 Editor에 WebGL 모듈이 없고 다른 설치 Editor에 모듈이 있으면, 명시적인
`UNITY_EDITOR_PATH`가 없는 경우 WebGL 모듈이 있는 최신 Editor를 자동으로 사용한다.

```powershell
$env:UNITY_EDITOR_PATH = "C:\Program Files\Unity\Hub\Editor\6000.3.20f1\Editor\Unity.exe"
$env:MAINFLOW_WEBGL_BUILD_TIMEOUT_SECONDS = "1200"
uv run --locked python -m uvicorn --app-dir "CI/CD/LocalWeb" app:app `
  --host 127.0.0.1 --port 8000 --reload
```

현재 Linux 기반 LocalWeb Docker 이미지에는 Unity Editor와 라이선스가 포함되어 있지 않다.
따라서 Docker에서 일반 생성 기능은 사용할 수 있지만 WebGL Preview 빌드는 실패 사유를
로그에 표시한다. Preview까지 사용하려면 위처럼 Windows 호스트에서 LocalWeb을 직접
실행하거나, 별도의 Unity Build Server/라이선스가 포함된 실행 환경을 연결해야 한다.

## 사용 순서

1. `기능별 AI 설정`에서 각 역할의 Provider와 Model을 고른다.
2. API Provider를 선택했다면 `API 인증 정보`에 해당 키를 입력한다.
3. `설정 저장`을 누른다.
4. 이미지 스타일, 분위기, 장르, 시점, Condition을 입력한다.
5. `Generate` 또는 `test-Generate`를 누른다.
6. 로그에서 Condition 분석 진행을 확인한다.
7. `조합 예정 Feature`에서 출처를 확인한다.
   - `사용자 요청`: Condition에서 직접 추출
   - `요청 의존`: 요청 기능이 동작하기 위한 선행 기능
   - `장르 필수`: 선택한 장르의 기본 플레이에 필요한 기능
8. 목록이 맞으면 Confirm, 다시 분석하려면 Reject를 누른다.
9. 완료 또는 실패까지 하단 로그를 확인한다.
10. 생성 성공 후 WebGL 빌드가 끝나면 `Preview 플레이`를 눌러 새 탭에서 게임을 실행한다.
    빌드가 실패하거나 중단되면 같은 버튼으로 다시 빌드할 수 있다.
11. 게임 검증이 실패했더라도 프로젝트 ID와 Unity 프로젝트가 남아 있으면
    `Preview 다시 빌드`를 눌러 현재 실패 상태의 게임을 직접 확인할 수 있다. 이 Preview는
    디버깅 편의 기능이며 실패한 검증 결과를 성공으로 바꾸지는 않는다.

## 생성 파일

```text
workspace/
├─ .localweb/
│  ├─ settings.json
│  ├─ secrets.env
│  └─ jobs/{job_id}/
│     ├─ request.json
│     ├─ feature_preview.json
│     ├─ workflow_result.json
│     └─ workflow.log
├─ {preview_project_id}/       # Feature 분석 Artifact
└─ {generated_project_id}/     # Confirm 이후 실제 생성 프로젝트
   ├─ game/
   │  ├─ unity_project/
   │  └─ webgl/                # LocalWeb이 제공하는 WebGL Preview
   └─ validation/
      └─ webgl_preview_build.json
```

Reject할 때마다 분석 근거를 보존하기 위해 새로운 Preview 프로젝트가 생긴다. Confirm 이후
실제 생성 프로젝트는 승인된 Preview의 Feature 목록을 검증해서 복사하므로 두 번째 분석에서
목록이 임의로 바뀌지 않는다.

`workflow_result.json`에는 CLI 호환을 위한 전체 `final_state`와 세부 검증 결과가 남는다.
브라우저 로그에는 이 큰 JSON을 출력하지 않고 종료 요약만 표시한다. 세부 ArtifactReference가
필요할 때만 해당 파일을 직접 확인한다.

## API 요약

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/health` | 서버/Workflow 연결 상태 |
| GET | `/api/config/models` | 역할/모델과 키 등록 여부 조회 |
| PUT | `/api/config/models` | 역할/모델과 새 키 저장 |
| POST | `/api/jobs` | Feature 분석 작업 시작 |
| GET | `/api/jobs/{job_id}` | 상태, Feature, 로그 조회 |
| POST | `/api/jobs/{job_id}/confirm` | 승인된 Feature로 생성 계속 |
| POST | `/api/jobs/{job_id}/reject` | Feature 분석 재실행 |
| POST | `/api/jobs/{job_id}/build-webgl` | 완료된 프로젝트의 Preview 빌드/재시도 |
| GET | `/preview/{project_id}/` | 빌드된 WebGL 게임 실행 |

OpenAPI 문서는 `http://127.0.0.1:8000/docs`에서 확인한다.

## 제한 사항

- 작업 상태는 서버 메모리에 있으므로 서버 재시작 후 기존 작업을 화면에서 재개하지 않는다.
  파일과 로그는 Workspace에 남는다.
- 동시에 여러 생성 작업을 실행할 수 있지만 LocalAI가 모델을 교체 서빙한다면 GPU 메모리와
  응답 시간이 크게 증가할 수 있다.
- `test-Generate`의 Visual Checklist는 Unity 화면 캡처를 사용하므로 그래픽 렌더링 가능한
  Unity 실행 환경이 필요하다.
- WebGL Preview 빌드 중에는 같은 Unity 프로젝트를 Editor로 열 수 없다. LocalWeb은 자동
  Editor 실행을 끄고 Preview가 끝난 뒤 `Unity Editor 열기` 버튼을 활성화한다.
