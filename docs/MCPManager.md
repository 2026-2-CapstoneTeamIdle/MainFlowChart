# MCP Manager

이 문서는 MainFlow의 LLM이 공통 MCP 서버를 통해 Docker workspace 파일 도구를 사용하는
방법을 정의한다. MCP 서버는 LLM 제공자와 독립적이며, 실제 모델 호출 코드는 각 Agent가
선택한 SDK에서 MCP 도구 정의와 실행 결과를 전달한다.

## 1. 구성

```text
LangGraph Node
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

LangGraph의 Edge와 State 계약은 변경하지 않는다. MCP는 파일 접근 능력을 제공할 뿐이며 Agent
결과는 계속 기존 `ArtifactReference` 계약으로 전달한다.

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

## 5. Node에서 LLM에 도구 연결

Graph가 Node를 실행하면 해당 Node 이름의 `MCPManager`가 context에 자동으로 들어간다. 실제 LLM을
호출하는 Node에서는 다음처럼 사용한다.

```python
from MCP import get_current_mcp_manager


async def call_agent_llm(messages):
    manager = get_current_mcp_manager()
    async with manager.connect() as mcp_session:
        tools = await mcp_session.openai_tool_definitions()

        # 사용하는 LLM SDK에 messages와 tools를 전달한다.
        response = await llm_client.create(messages=messages, tools=tools)

        # 모델이 요청한 도구 이름과 arguments를 그대로 실행한다.
        tool_result = await mcp_session.call_tool(
            response.tool_name,
            response.arguments,
        )
        return tool_result
```

`tool_definitions()`은 제공자 독립적인 MCP 스키마를 반환하고,
`openai_tool_definitions()`은 OpenAI 호환 function tool 형식을 반환한다. 실제 Gemini 호출 검증에는
Google Gen AI SDK를 사용하며 API 키 값은 저장소에 저장하지 않는다.

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
| `GEMINI_API_KEY` | 없음 | Gemini API 인증 키 |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | 실통합 검사에 사용할 Gemini 모델 |

API 키와 토큰은 MCP 도구 인자, workspace, manifest에 저장하지 않는다. 외부 공개 환경에서는 별도
인증 계층을 추가해야 하며 현재 Compose 설정은 로컬 개발 전용이다.

## 8. 테스트

```powershell
docker compose --profile test run --rm test
```

테스트는 인프로세스 MCP 연결로 도구 검색·호출, Node 권한 필터, 경로 이탈 방지, 해시 충돌,
Artifact 불변성을 검증한다. Docker 검증에서는 별도 MCP 컨테이너의 health check와 Streamable HTTP
연결도 확인한다.

실제 Gemini가 MCP를 통해 `workspace` 파일을 읽는지 확인하려면 다음 순서로 실행한다.

```powershell
docker compose up -d mcp-server
uv run --locked python -m MCP.check_gemini_file_read
docker compose down
```

검사기는 `workspace/{project_id}/data/mcp_gemini_read_test.txt`에 임의의 고유 문구를 기록한 뒤,
Gemini가 `read_project_text`를 호출했는지와 최종 응답에 그 문구가 포함됐는지를 모두 검사한다.
API 키 값은 출력하지 않으며 실패 시 예외 유형과 상태 코드만 출력한다.
