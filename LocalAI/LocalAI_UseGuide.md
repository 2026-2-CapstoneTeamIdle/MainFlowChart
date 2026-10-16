# LocalAI 사용 가이드

통합 버전: 1.3.0. 기본 모델은 Qwen2.5-Coder-7B-Instruct Q5_K_M(API 이름: qwen2.5-coder-7b-q5-k-m)이다.
LocalAI v4.11.0 llama.cpp를 사용한다. 공식 텍스트 전용 GGUF는 약 5.44GB이며
멀티모달 파일은 설치하지 않는다. context 8192, gpu_layers 99, 동시 추론 슬롯 1개,
호스트 프롬프트 캐시 상한 1024MiB와
동시 활성 backend 1개로 설정한다. 12GB GPU에서 모델 전체를 GPU에 올리되 Windows와
Unity가 사용할 여유를 남기는 구성이다.
자동 컨텍스트 축소는 끄므로 LocalAI 시작 로그의 effective runtime tuning에서
context=8192인지 확인한다.

## 실행

Docker Desktop과 NVIDIA GPU 지원을 준비한 뒤 저장소 루트에서 실행한다.

```powershell
uv sync --locked
docker compose -f compose.yaml -f LocalAI/compose.yaml up -d --force-recreate Local-AIModel
docker compose -f compose.yaml -f LocalAI/compose.yaml logs -f Local-AIModel
```

최초 다운로드가 끝난 후 등록 상태를 확인한다.

```powershell
uv run --locked python -m LocalAI.check_connection --model qwen2.5-coder-7b-q5-k-m
```

Web UI: http://127.0.0.1:8080 / 호스트 API: http://127.0.0.1:8080/v1.
연결 검사는 등록 여부만 확인하며 코드 생성 성공을 보장하지 않는다.
모델은 idle-capstone-local-ai-models named volume에 저장되며 기존 모델은 삭제하지 않는다.

## 게임 코드 생성

기존 모듈은 재사용하고 없는 기능만 LocalAI에 개별 요청한다.
응답 JSON과 C# 계약을 검사하고 Unity 프로젝트에 추가한다.
검증 실패 시 제한된 횟수로 재요청하며 최종 실패는 게임 생성 오류로 기록한다.
이 경우 이미지/사운드 단계는 계속되지만 정상 게임 생성으로 간주하지 않는다.

```powershell
$env:MAINFLOW_FEATURE_PROVIDER = "local"
$env:LOCAL_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
$env:LOCAL_LLM_MODEL = "qwen2.5-coder-7b-q5-k-m"
$env:LLM_TIMEOUT_SECONDS = "300"
$env:MAINFLOW_LOCAL_MAX_OUTPUT_TOKENS = "2048"
uv run --locked python -m mainflow.run_flow --image-style "Pixel Art" --mood-style "Fantasy" --genre "플랫포머" --viewpoint "사이드뷰" --condition "벽을 타고 올라갈 수 있는 게임"
```

게임 생성 provider 기본값은 local이다. Gemini를 사용하려면
MAINFLOW_FEATURE_PROVIDER=gemini와 GEMINI_API_KEY를 설정한다.
.env.example 복사만으로 PowerShell 환경 변수가 설정되지는 않는다.

Docker 전체 실행은 최신 코드를 빌드한다.

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml run --build --rm mainflow
```

Docker 내부 주소는 http://Local-AIModel:8080/v1 이다.
Unity 없는 환경의 정적 검사는 컴파일과 플레이 검사를 대체하지 않는다.
생성 프로젝트를 Unity에서 열어 실제 동작을 확인해야 한다.

## MCP 경로와 구분

게임 기능 생성기는 제한된 JSON 응답을 받고 호스트가 검증/저장하는 방식이다.
현재 이 경로는 MCP tool calling을 사용하지 않고 모델에 쉘/파일 도구를 제공하지 않는다.
다른 MCP 기반 비동기 노드에서는 기존 run_llm(prompt=prompt, ai="gemma4_e4b")를 사용한다.

## 이전 모델 사용 및 보존

E2B 사용 시 LOCALAI_PRELOAD_MODELS_CONFIG=/configuration/preload-models.yaml,
LOCALAI_DEFAULT_MODEL=gemma4-e2b-q4, LOCAL_LLM_MODEL=gemma4-e2b-q4로 설정하고
컨테이너를 재생성한다. 기본 Qwen으로 돌아갈 때는 preload-qwen-coder.yaml과 qwen2.5-coder-7b-q5-k-m로 바꾼다.
컨테이너 종료만으로 모델은 삭제되지 않는다. down -v는 볼륨 데이터까지 삭제할 수 있다.

## Unity 피드백 수정 반복

새 기능 생성 후 Unity 컴파일/씬 조립, Play Mode 검사를 실행한다.
실패하면 기존 생성 코드와 오류/실패 검사 JSON을 모델에 전달하고 최대 2회 수정한다.
각 회차는 validation/repair/attempt_N.json에 로그와 결과를 남기며,
실패 프로젝트는 game/unity_project_failed_attempt_N에 보존한다.
최종 성공한 코드로 설계 JSON, manifest, ZIP을 다시 만든다.
환경 오류(에디터 없음, 타임아웃 등)는 코드 수정으로 해결하지 않는다.

- MAINFLOW_GAME_MAX_REPAIRS: 0~3, 기본 2
- MAINFLOW_UNITY_VALIDATION_MODE: 새 기능 반복 검증 기본 required
- MAINFLOW_UNITY_RUNTIME_TESTS: 기본 1, 0이면 Play Mode 검사 생략
- UNITY_EDITOR_PATH: 자동 탐색 실패 시 실행 파일 지정
- MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS: Unity 프로세스별 제한, 기본 300

현재 Play Mode 검사는 예외, 모듈 초기화/바인딩, 좌표 유효성, 플랫포머 좌우 이동을 검사한다.
벽 타기/대시 등 개별 기능의 모든 의미적 조건을 검증하지는 않는다.
static 모드는 구조 검사만 수행한다. 성공해도 컴파일/플레이 성공으로 해석하면 안 된다.
Docker Linux 컨테이너에는 Windows Unity가 없으므로 실제 반복 검증은 호스트 Python에서 실행한다.
.env.example은 자동 로드하지 않는다. PowerShell 환경 변수로 설정하거나 실행 환경에 주입한다.

요청 계약은 game_pipeline/feature_contract.py에서 실제 템플릿 API 소스로 구성하고
game/feature_code_contract.json에 기록한다. 테스트 파일/공통 모듈은 모델 수정 대상이 아니다.
입력 테스트 전용 필드와 성공 로그 마커를 생성 코드가 사용하는 것도 차단한다.

모델은 코드 특화 후보로 교체한 것이며, Gemma 대비 모든 작업에서 우수함을 보장하지 않는다.
실제 요구사항별 성공률/수정 횟수/시간을 비교해야 한다.
