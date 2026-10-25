# MainFlowChart

사용자의 이미지 스타일, 분위기 스타일, 게임 장르, 시점, 한 문장 조건을 분석한 뒤 게임을 먼저
설계한다. 설계에서 만든 이미지·사운드 요청 JSON을 각 생성 Agent에 전달하고 결과를
검증·통합하는 LangGraph 기반 게임 제작 파이프라인이다.
게임 로직 Node는 장르별 모듈을 조합하고 prefab·씬 placeholder를 배치한 Unity 프로젝트와 ZIP을 생성한다. 이미지·사운드 생성
Node에는 실제 AI API 연동 전 단계의 placeholder가 포함돼 있다.

## 구조

```text
MainFlowChart/
├─ mainflow/
│  ├─ ArtifactManager.py
│  ├─ contracts.py
│  ├─ langgraph_game_flow_skeleton.py
│  ├─ run_flow.py
│  └─ nodes/
│     ├─ user_input.py
│     ├─ parse_input.py
│     ├─ analysis.py
│     ├─ logic_analysis.py
│     ├─ generate_image.py
│     ├─ design_game_logic.py
│     ├─ generate_sound.py
│     └─ ...                       # 검증·통합 Node 포함
├─ MCP/                            # MCP 서버, 클라이언트, Node 도구 정책
├─ CI/CD/LocalWeb/                  # 로컬 웹 UI
├─ docs/                           # 팀 규약과 운영 문서
│  ├─ assets/langgraph_flow.png
│  ├─ ContractRule.md
│  ├─ DockerManager.md
│  ├─ FileSystem.md
│  └─ MCPManager.md
├─ examples/                       # 실행 요청 예제
│  └─ request.example.json
├─ unity_template/                 # 생성기가 복사할 Unity 6 2D 기본 프로젝트
├─ tests/                          # mock Agent, fixture, 단위·통합 테스트
├─ workspace/                      # 실행 산출물(Git 제외)
├─ Dockerfile
├─ compose.yaml
├─ pyproject.toml
└─ uv.lock
```

## 입력 계약 3.4.0

- 이미지 스타일: `Pixel Art`, `Anime`, `Cartoon`, `Realistic`, `Low Poly`, `Custom`
- 분위기 스타일: `Cyberpunk`, `Medieval`, `Modern`, `Fantasy`, `Horror`, `Cozy`

### 요청별 씬 구성 LLM 사용

기본값은 빠르고 재현 가능한 규칙 기반 `GameBlueprint`이다. LocalAI가 실행 중일 때만 아래처럼
선택적으로 켤 수 있다. 모델 출력이 검증에 실패하면 자동으로 기본 Blueprint를 사용한다.

```powershell
$env:MAINFLOW_BLUEPRINT_PROVIDER="local"
uv run --locked python -m mainflow.run_flow ...
```

### design_game_logic v2 단계별 설계

계약 3.4.0은 하나의 큰 Blueprint 요청 대신 다음 7개 문서를 각각 생성한다.

`game_design.json → system_design.json → content_plan.json → level_plan.json →`
`balance_plan.json → presentation_plan.json → validation_plan.json`

기본값은 테스트 가능한 결정론적 설계이며, LocalAI를 켜면 각 문서를 작은 JSON 호출로 순서대로
보강한다. 형식이 깨지거나 플랫포머 경로가 이동 한계를 벗어난 단계만 안전한 기본 설계로 되돌린다.

```powershell
$env:MAINFLOW_DESIGN_V2_PROVIDER="local"
$env:LOCAL_LLM_BASE_URL="http://127.0.0.1:8080/v1"
$env:LOCAL_LLM_MODEL="qwen2.5-coder-7b-q5-k-m"
```

현재 vertical slice 품질 기준은 플랫포머에 우선 적용된다. `level_plan.json`은 튜토리얼·도전·응용
구역과 발판, 적, 함정, 수집물, 체크포인트, 목표를 명시하며 Unity SceneAssembler가 이 좌표를
직접 읽어 씬을 구성한다.

설계 이후에는 `implementation_tasks.json`의 의존성 DAG를 실행한다. 설계 검토, 기존 모듈 선택,
미지원 기능별 코드 생성, Unity 프로젝트 생성, Play Mode 검증, 패키징을 각각 독립 작업으로
관리하며 작업마다 시도 횟수·상태·오류·통과 증거를 기록한다. 미지원 기능은 한 번의 큰 LLM
호출로 묶지 않고 기능별로 생성하고, 최대 시도 횟수와 전체 30분 시간 예산을 적용한다. 실행 중간
상태는 `workspace/{project_id}/validation/development/`에 남기므로 실패 위치와 재시도 이력을
확인할 수 있다.

생성 모듈은 Unity 실행 전에 MCP 프로젝트 문맥 검수를 거친다. 필수 생성 파일은 호스트가 먼저
읽어 모델에 제공하며 불완전한 검수는 기본 2회까지만 재시도한다. 자연어 요약 대신 C# 파일을
결정적으로 스캔한 `game/project_context_index.json`에 클래스, 실제 공개 API, 이벤트, 모듈 ID와
원본 요구사항 ID를 보존한다. 단계별 설계와 기능 생성에는 선택 모듈 중심의 압축 API 인덱스를
전달한다. 신규 기능 생성 시에는 요구사항의 기능·장르 키워드로 관련 모듈을 검색하고 정확한 API
시그니처만 보내므로 8K 로컬 모델에 전체 프로젝트 인덱스를 반복 전송하지 않는다. 호출 전에는
`LOCAL_LLM_CONTEXT_TOKENS`와 출력 예약량을 기준으로 입력 예산도 검사한다. 문맥 검수 모델은 이
인덱스에 없는 멤버를 사용할 수 없다. 독립 Validator AI도 완성된
프로젝트 인덱스를 먼저 읽고 요구사항 누락 여부를 판정한다. 모든 에셋 적용과 Unity 최종
검증이 끝나면 별도의 읽기 전용 `game_quality_validator`가 요구사항 충족, 진행 가능성, 콘텐츠,
밸런스와 UI 피드백을 평가한다. 결과는
`workspace/{project_id}/validation/game_validator_ai_result.json`에 저장된다.

- 장르: `플랫포머`, `타워 디펜스`, `카드`, `비주얼 노벨`, `육성 시뮬레이션`, `뱀서류`
- 시점: `사이드뷰`, `탑다운`, `쿼터뷰`, `고정 화면`
- 조건: 비어 있지 않은 한 문장

`Custom` 이미지 스타일은 `--custom-image` 또는 요청 JSON의 `custom_image_path`로 PNG/JPG
파일을 함께 제공한다.

## 실행

```powershell
uv sync --locked
uv run --locked python -m mainflow.run_flow `
  --image-style "Pixel Art" `
  --mood-style Fantasy `
  --genre "플랫포머" `
  --viewpoint "사이드뷰" `
  --condition "공격과 8방향 이동이 가능한 게임"
```

JSON 요청은 `--request-file examples/request.example.json`으로 전달할 수 있다.

### Gemini 새 기능 생성

분석된 기능이 기존 Unity 모듈 카탈로그에 있으면 API를 호출하지 않고 해당 모듈을 재사용한다.
카탈로그로 충족할 수 없는 기능만 `gemini-3-flash-preview`에 전달해
`Assets/GameTemplate/Generated/Scripts/` 아래의 C# 모듈로 생성한다.

```powershell
$env:GEMINI_API_KEY="Google AI Studio에서 발급한 키"
$env:MAINFLOW_GEMINI_MODEL="gemini-3-flash-preview"

uv run --locked python -m mainflow.run_flow `
  --image-style "Pixel Art" `
  --mood-style Fantasy `
  --genre "플랫포머" `
  --viewpoint "사이드뷰" `
  --condition "점프하고 벽을 타고 올라갈 수 있는 게임"
```

API 응답은 JSON Schema, C# 선언 규칙, 금지 API, 소스 해시로 먼저 검사한다. 이후 기존
`validate_game` Node가 생성 파일과 manifest의 일관성을 확인하고 Unity Batchmode에서 실제
컴파일 및 Bootstrap 씬 조립을 검증한다. 키와 선택 설정은 [`.env.example`](.env.example)을
참고하되 실제 키는 저장소에 커밋하지 않는다.

```powershell
docker compose build
docker compose run --rm mainflow
```

## 테스트와 포맷

```powershell
uv run --locked python -m unittest discover -s tests -v
docker compose --profile test run --rm test
python tools/format_repo.py --write
python tools/format_repo.py --check
```

Workflow PNG는 외부 렌더링 서비스 없이 로컬에서 다시 만들 수 있다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/render_workflow_png.ps1
```

## 문서

- [데이터 계약](docs/ContractRule.md)
- [파일 교환 규약](docs/FileSystem.md)
- [Docker 실행](docs/DockerManager.md)
- [MCP 서버와 LLM 도구 연결](docs/MCPManager.md)
- [게임 파이프라인 개발 인계와 로드맵](docs/GamePipelineHandoff.md)
- [Local Web 실행](CI/CD/LocalWeb/LocalWebManager.md)
- [테스트 결과](tests/TestResult.md)
- [Workflow 이미지](docs/assets/langgraph_flow.png)

## Workflow

```mermaid
flowchart TD
    START --> UserInput[사용자 입력]
    UserInput --> Parse[입력 파싱]
    Parse --> Analysis[조건 기능 분석]
    Analysis --> LogicAnalysis[게임 로직 분석]

    LogicAnalysis --> GameDesign[게임 로직 설계]

    GameDesign --> ImageGen[이미지 생성]
    GameDesign --> GameValidate[게임 검증]
    GameDesign --> SoundGen[사운드 생성]
    GameValidate --> AssetSpec[이미지/사운드 검증서 생성]
    ImageGen --> ImageValidate[이미지 검증]
    AssetSpec --> ImageValidate
    SoundGen --> SoundValidate[사운드 검증]
    AssetSpec --> SoundValidate
    ImageValidate --> ApplyAssets[검증 에셋 게임 적용]
    SoundValidate --> ApplyAssets
    ApplyAssets --> FinalValidate[최종 검증]
    FinalValidate --> ValidatorAI[독립 Game Validator AI]
    ValidatorAI --> END
```

State에는 실제 파일 대신 `ArtifactReference`만 전달한다. 각 Node의 입력·출력 State와 파일은
함수 바로 위의 Node 계약 주석에 기록한다.

## Unity 2D 템플릿

`unity_template/`은 게임 생성기가 프로젝트별 작업 공간으로 복사할 Unity 6 LTS 기반 템플릿이다. 공통 런타임 진입점, 모듈 생명주기 계약, 설정 에셋과 검증 이벤트 수집기를 포함한다. Unity에서 프로젝트를 연 뒤 `Tools > Team IDLE > Rebuild Bootstrap Scene`을 실행하면 기본 씬과 설정 에셋을 다시 만들 수 있다. 자세한 내용은 [`unity_template/README.md`](unity_template/README.md)를 참고한다.
