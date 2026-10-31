# Vast.ai vLLM 원격 추론 가이드

버전: 1.0.0

## 범위

Vast.ai는 Local AI 모델의 추론만 담당한다. MainFlow, MCP 서버, `workspace`, ArtifactManager,
Unity Editor와 테스트는 기존 로컬 또는 팀 서버에 남는다. `VAST_API_KEY`는 인스턴스 생성·종료용
계정 키이므로 MainFlow에 전달하지 않는다. 모델 API 인증에는 별도
`VASTAI_INFERENCE_API_KEY`만 사용한다.

```text
MainFlow/Unity/workspace
  ├─ Coder 요청 ── SSH tunnel ── Vast vLLM :8000
  ├─ VLM 요청 ──── SSH tunnel ── Vast vLLM :8001
  └─ 목표 이미지 ─ SSH tunnel ── Vast vLLM-Omni :8002
```

## 사전 준비

1. Vast.ai에서 NVIDIA GPU 인스턴스를 만든다.
2. Coder와 VLM을 같이 올릴 VRAM이 부족하면 역할별 인스턴스를 사용하거나 순차적으로 실행한다.
3. 디스크에는 모델 캐시를 포함할 충분한 용량을 할당한다. 인스턴스 생성 후 디스크 크기는 쉽게
   바꿀 수 없으므로 여유를 둔다.
4. SSH/Direct 연결을 활성화한다. 모델 포트를 인터넷에 무인증으로 직접 공개하지 않는다.
5. vLLM 이미지 또는 vLLM이 설치된 PyTorch 템플릿을 사용한다.

공식 참고 문서:

- Vast.ai CLI/인스턴스: https://cloud.vast.ai/cli/
- Vast.ai 포트 매핑: https://github.com/vast-ai/docs/blob/main/guides/instances/docker-environment.mdx
- vLLM Docker: https://docs.vllm.ai/en/latest/deployment/docker/
- vLLM Tool Calling: https://docs.vllm.ai/en/latest/features/tool_calling/
- vLLM 멀티모달 입력: https://docs.vllm.ai/en/stable/features/multimodal_inputs/

## Vast 인스턴스에서 vLLM 실행

`VastAI/start_vllm.sh`를 인스턴스로 복사하거나 같은 옵션으로 템플릿 시작 명령을 구성한다.
Coder 예시는 다음과 같다.

```bash
export VASTAI_ROLE=coder
export VASTAI_MODEL=<Hugging-Face-Coder-모델-ID>
export VASTAI_SERVED_MODEL=mainflow-coder
export VASTAI_PORT=8000
export VASTAI_MAX_MODEL_LEN=32768
export VASTAI_INFERENCE_API_KEY=<추론용-임의의-긴-키>
export VASTAI_TOOL_CALL_PARSER=<모델에-맞는-vLLM-parser>
bash VastAI/start_vllm.sh
```

`run_node_llm`의 MCP Tool 호출까지 사용할 모델은 `--enable-auto-tool-choice`와 모델에 맞는
`--tool-call-parser`가 필요하다. Qwen2.5는 일반적으로 `hermes`, Qwen3-Coder는 해당 vLLM 버전의
Qwen3 parser 지원 목록을 확인한다.

VLM은 별도 프로세스 또는 인스턴스에서 실행한다.

```bash
export VASTAI_ROLE=vlm
export VASTAI_MODEL=<멀티모달-VLM-모델-ID>
export VASTAI_SERVED_MODEL=mainflow-vlm
export VASTAI_PORT=8001
export VASTAI_MAX_MODEL_LEN=8192
export VASTAI_INFERENCE_API_KEY=<Coder와-같거나-별도인-추론키>
bash VastAI/start_vllm.sh --limit-mm-per-prompt '{"image":2}'
```

목표 이미지까지 Vast에서 생성하려면 OpenAI Images API를 제공하는 vLLM-Omni 호환 모델을
8002에서 실행한다. 지원하지 않는 모델이면 목표 이미지만 기존 로컬 `sd_turbo`를 유지한다.

```bash
export VASTAI_ROLE=image
export VASTAI_MODEL=<vLLM-Omni-이미지-모델-ID>
export VASTAI_SERVED_MODEL=mainflow-image
export VASTAI_PORT=8002
export VASTAI_VLLM_MODE=omni
export VASTAI_INFERENCE_API_KEY=<추론키>
bash VastAI/start_vllm.sh
```

## 로컬 SSH 터널

Vast의 Connect 화면에 표시된 `<HOST>`, `<SSH_PORT>`를 사용한다.

```powershell
ssh -p <SSH_PORT> root@<HOST> `
  -L 18000:localhost:8000 `
  -L 18001:localhost:8001 `
  -L 18002:localhost:8002
```

이 PowerShell은 MainFlow 실행 중 유지한다. 인터넷 공개 URL을 사용하는 경우에도
`VASTAI_INFERENCE_API_KEY`를 설정하고 TLS가 적용된 주소만 사용한다.

## MainFlow 환경 변수

`VastAI/.env.example`을 참고해 현재 PowerShell에 직접 등록한다. `.env` 파일을 만드는 것만으로
PowerShell 환경 변수가 자동 등록되지는 않는다.

```powershell
$env:VASTAI_INFERENCE_API_KEY = "<추론서버용 키>"
$env:VASTAI_CODER_BASE_URL = "http://127.0.0.1:18000/v1"
$env:VASTAI_CODER_MODEL = "mainflow-coder"
$env:VASTAI_CODER_CONTEXT_TOKENS = "32768"
$env:VASTAI_CODER_MAX_OUTPUT_TOKENS = "8192"

$env:VASTAI_VLM_BASE_URL = "http://127.0.0.1:18001/v1"
$env:VASTAI_VLM_MODEL = "mainflow-vlm"

$env:VASTAI_IMAGE_BASE_URL = "http://127.0.0.1:18002/v1"
$env:VASTAI_IMAGE_MODEL = "mainflow-image"

$env:MAINFLOW_FEATURE_PROVIDER = "vastai"
$env:MAINFLOW_DESIGN_V2_PROVIDER = "vastai"
$env:MAINFLOW_BLUEPRINT_PROVIDER = "vastai"
$env:LLM_VISUAL_VALIDATION_PROVIDER = "vastai"
$env:MAINFLOW_VISUAL_TARGET_AI = "vast_image"
```

연결 확인은 키 값을 출력하지 않는다.

```powershell
uv run --locked python -m VastAI.check_connection --role coder
uv run --locked python -m VastAI.check_connection --role vlm
uv run --locked python -m VastAI.check_connection --role image
```

이미지 서버를 아직 준비하지 않았다면 다음 한 줄만 로컬 설정으로 유지한다.

```powershell
$env:MAINFLOW_VISUAL_TARGET_AI = "sd_turbo"
```

## `run_node_llm` 별칭

```python
coder = await run_node_llm(prompt, ai="vast_coder")
vlm = await run_node_llm(prompt, ai="vast_vlm")
image = await run_node_llm(prompt, ai="vast_image", output="image")
```

VLM 별칭은 `visual_validation`, 이미지 별칭은 `visual_validation`과 `generate_image` Node에만
허용한다. 역할별 URL과 모델명을 분리하므로 서로 다른 Vast 인스턴스도 사용할 수 있다.

## 운영 주의사항

- Vast 인스턴스가 실행되는 동안 비용이 발생하므로 사용 후 중지 또는 제거한다.
- 모델 가중치와 캐시는 Vast 인스턴스/볼륨에 있고 저장소에는 넣지 않는다.
- 원격 Coder/VLM에는 프롬프트와 필요한 프로젝트 문맥이 전송된다. 비밀 파일은 MCP 정책과
  workspace 경계 밖에 둔다.
- 더 큰 모델을 써도 잘못된 JSON이 완전히 사라지지는 않는다. 계약 검증과 deterministic fallback을
  계속 유지한다.
