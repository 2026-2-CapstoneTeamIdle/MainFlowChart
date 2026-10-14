# MCP Manager

이 문서는 MainFlow의 LLM이 공통 MCP 서버를 통해 Docker workspace 파일 도구를 사용하는
방법을 정의한다. MCP 서버는 LLM 제공자와 독립적이며, 실제 모델 호출 코드는 각 Agent가
선택한 SDK에서 MCP 도구 정의와 실행 결과를 전달한다.

## 1. 구성

```text
LangGraph Node
  └─ run_node_llm(prompt, provider=...)
      ├─ Gemini / OpenAI / Local SLM adapter
      └─ MCPManager(node_name)
          └─ Streamable HTTP Client
              └─ mcp-server:8001/mcp
                  └─ ArtifactManager
                      └─ /app/workspace/{project_id}/...
```

- `MCP/server.py`: 공식 Python MCP SDK v2 기반 Streamable HTTP 서버
- `MCP/manager.py`: 노드별 도구 필터링과 LLM용 도구 정의 변환
- `MCP/policies.py`: 노드 이름별 도구 허용 목록
- `MCP/node_context.py`: 기존 Node 본문 수정 없이 실행 중 `MCPManager` 주입
- `MCP/config.py`: Docker와 로컬 환경 변수 설정
- `MCP/llm_config.py`: 공급자·모델·endpoint 환경 변수 해석
- `MCP/llm_providers.py`: Gemini와 OpenAI 호환 API 응답을 공통 형식으로 변환
- `MCP/llm_runner.py`: LLM Tool 요청을 MCP로 실행하고 결과를 모델에 다시 전달

LangGraph의 Edge와 State 계약은 변경하지 않는다. MCP는 파일 접근 능력을 제공할 뿐이며 Agent
결과는 계속 기존 `ArtifactReference` 계약으로 전달한다.

Graph의 각 Node가 실행될 때 `MCPManager`에는 Node 이름과 State의 `project_id`가 함께 바인딩된다.
따라서 같은 Node를 여러 프로젝트에서 동시에 실행해도 각 실행은 자신의 프로젝트 workspace만
접근할 수 있다.

## 2. Docker 실행

저장소 루트에서 실행한다.

```powershell
docker compose up --build mcp-server
```

MCP endpoint와 health endpoint는 다음과 같다.

```text
http://127.0.0.1:8001/mcp
http://127.0.0.1:8001/health
```

실제 MCP 연결과 Node별 도구 목록은 다음 명령으로 확인한다.

```powershell
uv run --locked python -m MCP.check_connection --node analysis
```

전체 MainFlow 실행 시 Compose가 MCP 서버의 health check를 기다린다.

```powershell
docker compose run --rm mainflow
```

작업이 끝난 뒤 백그라운드 MCP 컨테이너를 종료한다.

```powershell
docker compose down
```

컨테이너 사이에서는 `http://mcp-server:8001/mcp`를 사용한다. 호스트에는 보안을 위해
`127.0.0.1:8001`로만 공개한다.

## 3. 현재 제공 도구

| 도구 | 설명 |
|---|---|
| `list_project_files` | `{project_id}` 내부 파일 목록 조회 |
| `read_project_text` | UTF-8 작업 파일 내용과 SHA-256 조회 |
| `write_project_text` | UTF-8 작업 파일 생성 또는 SHA-256 기반 수정 |

도구가 접근하는 범위는 `MAINFLOW_WORKSPACE/{project_id}` 내부로 제한된다. 절대 경로와 `..` 경로
이탈은 거부한다. 읽기·쓰기는 기본 256 KiB, 목록은 기본 200개로 제한한다.

기존 파일을 수정할 때는 반드시 먼저 읽어서 받은 `sha256`을 `expected_sha256`으로 전달한다.

```json
{
  "project_id": "20261014_01",
  "relative_path": "game/working/design.txt",
  "content": "수정된 내용",
  "expected_sha256": "이전에 읽은 SHA-256"
}
```

다른 Agent가 먼저 파일을 변경하면 해시가 일치하지 않아 수정이 거부된다. 다시 읽은 뒤 변경 내용을
병합해야 한다.

## 4. Artifact와 작업 파일

MCP 쓰기 도구는 Unity 소스처럼 생성 중 수정할 수 있는 **작업 파일**을 대상으로 한다.

- `ArtifactManager.write_json`, `write_text`, `write_bytes`로 등록된 Artifact는 불변이다.
- `data/artifact_manifest.json`과 manifest lock 파일은 MCP로 수정할 수 없다.
- 등록된 Artifact 경로를 `write_project_text`로 덮어쓸 수 없다.
- 최종 결과는 기존 규약대로 `ArtifactManager`에 새 파일로 등록하고 `ArtifactReference`를 반환한다.

`ArtifactManager`에는 MCP가 같은 경계 검사를 재사용하도록 다음 API를 추가했다.

```text
resolve_project_path
list_project_files
read_project_file
write_project_file
write_project_text
```

## 5. Node에서 LLM과 도구 사용

Graph가 Node를 실행하면 해당 Node 이름의 `MCPManager`가 context에 자동으로 들어간다. Node에서는
공급자별 SDK나 Tool 반복문을 작성하지 않고 `run_node_llm()`만 호출한다.

```python
from MCP import run_node_llm


async def analysis_node(state):
    result = await run_node_llm(
        prompt=(
            f"project_id={state['project_id']}의 data/parsed_request.json을 읽고 "
            "게임 기능을 분석하세요. 필요하면 MCP 파일 도구를 사용하세요."
        ),
        system_prompt="게임 요구사항 분석가로 작업하고 JSON만 반환하세요.",
    )
    analysis_json = result.text
    # analysis_json을 contracts.py 형식으로 검증한 뒤 ArtifactManager로 저장한다.
```

`run_node_llm()`은 현재 Node에 허용된 MCP 도구만 모델에 보여 준다. 모델이 Tool을 요청하면 실행기가
권한을 다시 확인하고 도구를 호출한 다음 결과를 모델에 되돌려 준다. 모델이 최종 텍스트를 반환할
때까지 이 과정을 반복한다. 반환값 `LLMRunResult`에는 다음 값이 들어 있다.

- `text`: 모델의 최종 출력
- `provider`, `model`: 실제 사용한 공급자와 모델
- `turns`: 모델 호출 횟수
- `tool_calls`: 실행된 도구 이름, 인자, 결과 기록

프로젝트 파일 Tool을 실행할 때는 Tool 인자의 `project_id`가 현재 Node State의 `project_id`와 정확히
같아야 한다. LLM이 다른 프로젝트 ID를 생성하거나 프롬프트에서 가져와 호출하면 실행 전에
`PermissionError`로 거부된다. State에 `project_id`가 아직 없는 `user_input`, `parse_input` 단계에서는
프로젝트 파일 Tool을 호출할 수 없다. `parse_input`이 프로젝트를 생성한 다음 Node부터 자동으로
바인딩된다.

```text
Node State project_id=20261014_03
  ├─ Tool project_id=20261014_03 → 허용
  ├─ Tool project_id=20261014_04 → 거부
  └─ Tool project_id 누락          → 거부
```

공급자는 호출할 때 명시적으로 선택할 수 있다.

```python
gemini_result = await run_node_llm(prompt, provider="gemini")
openai_result = await run_node_llm(prompt, provider="openai", model="팀 지정 모델")
local_result = await run_node_llm(prompt, provider="local", model="qwen3:8b")
```

`provider`를 생략하면 `LLM_{NODE_NAME}_PROVIDER`, `LLM_PROVIDER`, `gemini` 순서로 선택한다. 예를 들어
Analysis만 OpenAI를 사용하고 나머지는 Gemini를 사용하려면 다음처럼 설정한다.

```powershell
$env:LLM_PROVIDER = "gemini"
$env:LLM_ANALYSIS_PROVIDER = "openai"
$env:LLM_ANALYSIS_MODEL = "팀에서 사용할 OpenAI 모델명"
```

Local SLM은 Ollama, LM Studio, vLLM처럼 OpenAI Chat Completions와 Function Calling을 지원하는
endpoint를 대상으로 한다. 사용하는 모델 자체가 Tool Calling을 지원해야 파일 도구를 호출할 수 있다.

LLM을 사용하는 Node는 `async def`여야 한다. 그래프도 `invoke()`가 아니라 `await ainvoke()` 또는
`astream()`으로 실행해야 한다. LLM을 쓰지 않는 기존 동기 Node는 그대로 둘 수 있다.

LLM 출력은 신뢰하지 말고 반드시 `contracts.py`의 계약으로 검증한다. Node의 공식 결과 파일은 기존과
동일하게 `ArtifactManager`로 등록하고 `ArtifactReference`를 State에 반환한다. MCP 쓰기 도구는 생성
중 수정 가능한 작업 파일에만 사용한다.

저수준 제어가 필요한 경우 `MCPToolLLMRunner`에 직접 Provider를 주입할 수 있다. 이 경우에도
`MCPManager`에 대상 프로젝트를 명시해야 한다.

```python
manager = MCPManager("analysis", project_id=state["project_id"])
runner = MCPToolLLMRunner(manager, provider)
```

테스트에서는 이 방식으로 가짜 Provider를 넣어 실제 API 호출 없이 Tool 반복, Node 권한,
프로젝트 격리를 검증한다.

## 6. Node별 도구 권한

`MCP/policies.py`의 `NODE_TOOL_ALLOWLIST`가 LLM에 공개할 도구를 결정한다.

- `user_input`: 파일 목록과 읽기만 허용
- 나머지 현재 Workflow Node: 목록, 읽기, 작업 파일 쓰기 허용

서버에 새 도구를 추가해도 정책에 등록하지 않으면 해당 Node의 LLM에는 보이지 않는다. 모델이 도구
이름을 임의로 호출해도 `MCPManager`가 실행 전에 다시 거부한다.

새 Node를 Graph에 추가할 때는 다음 두 곳을 함께 수정한다.

1. `MCP/policies.py`에 Node 이름과 허용 도구 등록
2. Graph 등록 시 `bind_mcp_tools(node_name, node)` 적용

## 7. 환경 변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `MCP_SERVER_URL` | `http://127.0.0.1:8001/mcp` | Agent가 접속할 endpoint |
| `MCP_HOST` | `127.0.0.1` | 서버 bind 주소 |
| `MCP_PORT` | `8001` | 서버 포트 |
| `MCP_ALLOWED_HOSTS` | localhost와 `mcp-server` | Host header 허용 목록 |
| `MCP_ALLOWED_ORIGINS` | localhost | 브라우저 Origin 허용 목록 |
| `MCP_MAX_TEXT_BYTES` | `262144` | 한 번에 읽거나 쓰는 UTF-8 최대 크기 |
| `MCP_MAX_LIST_ENTRIES` | `200` | 파일 목록 최대 개수 |
| `MAINFLOW_WORKSPACE` | 저장소의 `workspace/` | 접근 가능한 workspace root |
| `LLM_PROVIDER` | `gemini` | 전체 Node 기본 공급자: `gemini`, `openai`, `local` |
| `LLM_MODEL` | 공급자별 기본값 | 전체 Node 기본 모델 재정의 |
| `LLM_{NODE}_PROVIDER` | 없음 | 특정 Node 공급자 재정의, 예: `LLM_ANALYSIS_PROVIDER` |
| `LLM_{NODE}_MODEL` | 없음 | 특정 Node 모델 재정의, 예: `LLM_ANALYSIS_MODEL` |
| `LLM_TIMEOUT_SECONDS` | `120` | OpenAI 호환 HTTP 요청 제한 시간 |
| `GEMINI_API_KEY` | 없음 | Gemini API 인증 키 |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | Gemini 기본 모델 |
| `OPENAI_API_KEY` | 없음 | OpenAI API 인증 키 |
| `OPENAI_MODEL` | `gpt-4.1-mini` | OpenAI 기본 모델 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 호환 endpoint |
| `LOCAL_LLM_API_KEY` | 없음 | Local endpoint가 인증을 요구할 때만 사용 |
| `LOCAL_LLM_MODEL` | `gemma3` | Local SLM 기본 모델 |
| `LOCAL_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | Local OpenAI 호환 endpoint |

API 키와 토큰은 MCP 도구 인자, workspace, manifest에 저장하지 않는다. 외부 공개 환경에서는 별도
인증 계층을 추가해야 하며 현재 Compose 설정은 로컬 개발 전용이다.

Docker의 MainFlow에서 호스트의 Ollama를 호출할 때는 보통 다음 값을 사용한다.

```powershell
$env:LLM_PROVIDER = "local"
$env:LOCAL_LLM_BASE_URL = "http://host.docker.internal:11434/v1"
$env:LOCAL_LLM_MODEL = "qwen3:8b"
docker compose run --rm mainflow
```

MCP로 읽은 파일 내용은 모델 호출 입력에 포함되므로 Gemini/OpenAI를 선택하면 해당 내용이 외부
API로 전송된다. 외부 전송이 불가능한 파일은 Local SLM을 사용하거나 프롬프트에서 제외해야 한다.

## 8. 테스트

```powershell
docker compose --profile test run --rm test
```

테스트는 인프로세스 MCP 연결로 도구 검색·호출, Node 권한 필터, State와 Tool의 프로젝트 ID 일치,
LLM Tool 반복, 공급자별 설정, 경로 이탈 방지, 해시 충돌, Artifact 불변성을 검증한다. Docker
검증에서는 별도 MCP 컨테이너의 health check와 Streamable HTTP 연결도 확인한다.

실제 Gemini가 MCP를 통해 `workspace` 파일을 읽는지 확인하려면 다음 순서로 실행한다.

```powershell
docker compose up -d mcp-server
uv run --locked python -m MCP.check_gemini_file_read
docker compose down
```

검사기는 `workspace/{project_id}/data/mcp_gemini_read_test.txt`에 임의의 고유 문구를 기록한 뒤,
Gemini가 `read_project_text`를 호출했는지와 최종 응답에 그 문구가 포함됐는지를 모두 검사한다.
API 키 값은 출력하지 않으며 실패 시 예외 유형과 상태 코드만 출력한다.
