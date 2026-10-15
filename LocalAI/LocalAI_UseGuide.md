# LocalAI 사용 가이드

- 통합 버전: `1.1.0`
- 기준일: `2026-10-15`
- Docker 서비스/컨테이너: `Local-AIModel`
- 기본 모델: `Gemma 4 E2B QAT Q4_0`
- 기본 API 모델명: `gemma4-e2b-q4`
- 선택 가능한 고성능 모델: `Gemma 4 E4B` (`gemma4-e4b`)
- LocalAI 이미지: `localai/localai:v4.11.0-gpu-nvidia-cuda-12`

## 1. 구성 목적

LocalAI를 Docker Desktop에서 실행하고 Workflow Node가 기존 MCP 권한 체계를 유지한 채 로컬
LLM을 사용할 수 있게 한다.

```text
Workflow Node
  └─ run_llm(ai="gemma4_e2b_q4")
      └─ Local-AIModel:8080/v1/chat/completions
          ├─ Gemma 4 E2B Q4 추론
          └─ MCPToolLLMRunner
              └─ node_name과 project_id 범위 안에서 MCP Tool 실행
```

LocalAI는 모델 추론을 담당하고, 파일 Tool 권한과 프로젝트 격리는 기존
`MCPToolLLMRunner`와 `MCPManager`가 담당한다.

## 2. 버전 1.1.0 변경 사항

- 전용 VRAM 6GB 환경을 위한 `Gemma 4 E2B QAT Q4_0` 프로필 추가
- E2B Q4를 기본 시작 모델로 변경
- 공식 GGUF 본체만 다운로드하고 약 987MB의 이미지·오디오용 `mmproj`는 제외
- E2B 컨텍스트를 4,096 tokens로 제한
- llama.cpp의 GPU offload와 저 VRAM 모드 사용
- 기존 E4B 모델은 별도 preload 설정으로 보존
- `run_llm(ai="gemma4_e2b_q4")` 선택 지원

## 3. 파일 구성

```text
LocalAI/
├─ compose.yaml                  # Local-AIModel Docker 서비스
├─ preload-models.yaml           # 기본 E2B Q4 설치 정의
├─ preload-gemma4-e4b.yaml       # 선택형 E4B 설치 정의
├─ profiles.py                   # run_llm의 ai 이름과 API 모델명 연결
├─ check_connection.py           # API와 모델 등록 상태 검사
├─ .env.example                  # 환경 변수 예시
├─ VERSION                       # 통합 버전
└─ LocalAI_UseGuide.md           # 이 문서
```

모델 가중치는 Git 저장소가 아니라 Docker named volume
`idle-capstone-local-ai-models`에 저장된다.

## 4. 모델별 하드웨어 기준

### Gemma 4 E2B Q4 — 기본값

- 공식 GGUF 본체 크기: `3,349,516,256 bytes`(약 3.35GB)
- Google의 Q4_0 기본 추론 메모리 추정치: 약 2.9GB
- 프로젝트 기본 context: 4,096 tokens
- 전용 VRAM 6GB 환경에서 사용하는 프로필
- MTP 보조 모델과 멀티모달 projector를 사용하지 않음

모델 외에도 KV Cache와 llama.cpp 실행 메모리가 필요하므로 다른 GPU 프로그램을 종료하는 것이
좋다. 그래도 OOM이 발생하면 `gpu_layers`나 `context_size`를 낮춰야 한다.

### Gemma 4 E4B — 선택형

- 현재 정의는 SGLang MTP 방식
- 전용 VRAM 24GB 이상 권장
- 6GB GPU에서는 사용하지 않는 것을 권장

## 5. 사전 준비

1. Docker Desktop과 WSL2를 실행한다.
2. NVIDIA 드라이버와 Docker GPU 지원을 준비한다.
3. Docker Desktop의 WSL 자원 제한에 충분한 시스템 RAM을 배정한다.
4. 모델 저장을 위한 디스크 여유 공간을 확보한다.

E2B Q4 공식 저장소는 공개되어 있으므로 일반적으로 `HF_TOKEN` 없이도 받을 수 있다. 다운로드
제한이나 인증 정책이 바뀌는 상황을 대비해 토큰 환경 변수는 계속 지원한다.

```powershell
$env:HF_TOKEN = "본인의 Hugging Face 토큰"
```

토큰을 사용하더라도 Git, YAML, workspace에는 저장하지 않는다.

## 6. E2B Q4 실행

저장소 루트에서 실행한다.

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml up -d Local-AIModel
```

최초 실행 시 다음 파일이 Docker named volume으로 다운로드된다.

```text
google/gemma-4-E2B-it-qat-q4_0-gguf
└─ gemma-4-E2B_q4_0-it.gguf
```

텍스트 기반 Workflow와 MCP Tool 호출만 대상으로 하므로
`gemma-4-E2B-it-mmproj.gguf`는 다운로드하지 않는다.

로그 확인:

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml logs -f Local-AIModel
```

접속 주소:

```text
Web UI: http://127.0.0.1:8080
API:    http://127.0.0.1:8080/v1
```

## 7. 모델 등록 확인

```powershell
.\.venv\Scripts\python.exe -m LocalAI.check_connection
```

정상 상태에서는 `available_models`에 `gemma4-e2b-q4`가 표시된다.

E4B를 확인하려면 모델명을 명시한다.

```powershell
.\.venv\Scripts\python.exe -m LocalAI.check_connection --model gemma4-e4b
```

## 8. Node에서 E2B Q4 호출

`run_llm`은 MCP가 바인딩된 비동기 Node 안에서 호출한다. `project_id`는 Workflow state를 통해
MCPManager에 바인딩된다.

```python
from MCP import run_llm


async def analysis_node(state):
    result = await run_llm(
        prompt=(
            f"project_id={state['project_id']}의 입력 파일을 읽고 "
            "필요한 게임 기능을 분석하세요."
        ),
        system_prompt="게임 기능 분석가로 작업하세요.",
        ai="gemma4_e2b_q4",
    )
    return {"analysis_text": result.text}
```

대소문자와 하이픈은 정규화되므로 `ai="Gemma4-E2B-Q4"`도 같은 프로필을 선택한다.

`ai`를 지정한 호출에는 `provider` 또는 `model`을 동시에 지정할 수 없다.

```python
# 잘못된 호출
await run_llm(prompt=prompt, ai="gemma4_e2b_q4", provider="local")
```

## 9. MainFlow와 함께 실행

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml run --rm mainflow
```

Docker 내부에서는 다음 주소를 자동 사용한다.

```text
LOCAL_LLM_BASE_URL=http://Local-AIModel:8080/v1
LOCAL_LLM_MODEL=gemma4-e2b-q4
```

호스트 Python에서 직접 호출할 때는 기본 주소 `http://127.0.0.1:8080/v1`을 사용한다.

## 10. E4B로 전환

E4B를 사용하려면 기존 컨테이너를 내리고 preload 파일과 기본 모델을 바꿔 실행한다.

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml down
$env:LOCALAI_PRELOAD_MODELS_CONFIG = "/configuration/preload-gemma4-e4b.yaml"
$env:LOCALAI_DEFAULT_MODEL = "gemma4-e4b"
docker compose -f compose.yaml -f LocalAI/compose.yaml up -d Local-AIModel
```

Node 호출:

```python
result = await run_llm(prompt=prompt, ai="gemma4_e4b")
```

E2B로 돌아갈 때는 현재 PowerShell 세션의 변수를 제거하고 다시 실행한다.

```powershell
Remove-Item Env:LOCALAI_PRELOAD_MODELS_CONFIG -ErrorAction SilentlyContinue
Remove-Item Env:LOCALAI_DEFAULT_MODEL -ErrorAction SilentlyContinue
```

## 11. Docker 모델 저장소 관리

저장 위치 확인:

```powershell
docker volume inspect idle-capstone-local-ai-models
```

컨테이너만 종료하면 모델은 유지된다.

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml down
```

다음 명령은 Docker volume과 다운로드한 모델까지 제거한다.

```powershell
docker compose -f compose.yaml -f LocalAI/compose.yaml down -v
```

## 12. 다른 모델 추가

### 12.1 설치 정의 추가

`LocalAI/` 아래에 새 preload YAML을 만들고 LocalAI gallery 설정이나 직접 다운로드할 GGUF 파일을
등록한다.

```yaml
- url: https://example.com/localai-model-config.yaml
  name: new-model-api-name
```

GGUF를 직접 등록할 때는 파일명, URI, SHA-256, backend, context 크기와 GPU layer 수를 함께
검토한다. 모델 파일은 Git에 넣지 않고 `/models` Docker volume으로 다운로드한다.

### 12.2 호출 프로필 추가

`LocalAI/profiles.py`의 `AI_MODEL_PROFILES`에 별칭을 추가한다.

```python
"new_model": LocalAIModelProfile(
    provider="local",
    model="new-model-api-name",
    base_url_environment="LOCAL_LLM_BASE_URL",
    default_base_url="http://127.0.0.1:8080/v1",
    api_key_environment="LOCAL_LLM_API_KEY",
),
```

호출 시 등록한 별칭을 사용한다.

```python
result = await run_llm(prompt=prompt, ai="new_model")
```

### 12.3 확인 사항

- LocalAI/llama.cpp가 모델 architecture를 지원하는지
- 모델의 OpenAI Chat Completions 및 Tool Calling 출력이 호환되는지
- 모델 가중치와 KV Cache가 전용 VRAM 안에 들어오는지
- API 모델명과 `profiles.py`의 `model` 값이 일치하는지
- 모델 라이선스와 인증 토큰이 필요한지

## 13. 버전 변경 규칙

- 문서나 기존 프로필 수정: patch 버전 증가
- 새 모델 또는 backend 추가: minor 버전 증가
- 호출 API나 Docker 저장 구조의 비호환 변경: major 버전 증가

버전 변경 시 `LocalAI/VERSION`, 이 문서의 통합 버전, preload 주석을 함께 갱신한다.
