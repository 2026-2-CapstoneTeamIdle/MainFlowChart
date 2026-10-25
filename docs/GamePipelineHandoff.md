# 게임 생성 파이프라인 개발 인계서

이 문서는 게임 파트의 현재 구현 범위, 다음 구현 순서, 다른 팀원이나 Codex가 작업을 이어갈 때
반드시 지켜야 할 계약과 검증 절차를 정리한다. 문서와 코드가 충돌하면
`mainflow/contracts.py`와 JSON Schema를 기계 판독 기준으로 삼는다.

## 1. 현재 목표

사용자가 장르, 시점, 이미지 스타일, 분위기와 기능 요구사항을 입력하면 다음 과정을 거쳐 Unity
2D vertical slice를 생성한다.

```text
요구사항 분석
→ 7개 설계 문서 생성
→ 기존 Unity 모듈 선택
→ 부족한 기능별 C# 생성
→ Unity 프로젝트와 씬 조립
→ 컴파일·Play Mode 검증 및 제한된 수정 반복
→ 이미지·사운드 생성과 검증
→ 검증된 에셋 적용
→ 최종 검증과 프로젝트 패키징
```

지원 장르는 플랫포머, 타워 디펜스, 카드, 비주얼 노벨, 육성 시뮬레이션, 뱀서류다. 현재 품질
고도화의 기준 장르는 플랫포머이며, 다른 장르는 공통 계약과 기본 조립기를 제공하는 단계다.

## 2. 구현 완료 범위

### 입력·계약·파일 교환

- 계약 버전 3.4.0과 `ArtifactReference` 기반 파일 교환
- 이미지·사운드별 `generation_spec`과 `unity_binding_key`
- 프로젝트별 workspace, checksum, 원자적 쓰기와 manifest
- LangGraph의 게임·이미지·사운드 병렬 실행 및 게임 실패 격리

### 게임 설계와 코드 생성

- 장르별 기본 `GameSpec`, 공통/장르 모듈 카탈로그
- `game_design.json`부터 `validation_plan.json`까지 7개 v2 설계 문서
- 결정론적 기본 설계와 LocalAI/Gemini 단계별 보강
- 요청별 `GameBlueprint` 생성과 검증 실패 시 결정론적 fallback
- 미지원 기능을 기능별 호출로 나누는 C# 생성기
- 금지 API, 3D 물리 API, 선언·바인딩 계약과 소스 해시 검사
- 생성 코드에 Unity 컴파일 오류를 돌려주는 제한된 repair loop

### Unity 생성·검증

- Unity 6 2D 프로젝트와 ZIP 생성
- 기존 모듈, 생성 모듈, prefab, UI와 장르별 씬 조립
- 플랫포머 `level_plan`의 구역·발판·위험물·수집물·체크포인트 배치
- 정적 검사, Unity Batchmode 컴파일, SceneAssembler, Play Mode smoke test
- AI 생성 모듈이 있으면 Unity 실행 전에 MCP로 조립된 프로젝트의 관련 C#과 바인딩 API를 검수
- 문맥 검수 오류는 생성 모듈 repair와 프로젝트 재조립을 거쳐 Unity 검증으로 전달
- 실패를 code/scene/level/balance/content/binding/test/infrastructure로 분류
- 레벨·밸런스·콘텐츠의 결정론적 수정과 프로젝트 재생성
- Play Mode 로그 기반 100점 품질 보고서

### 이미지·사운드와 Unity 적용

- placeholder/OpenAI/LocalAI 이미지 backend와 이미지 기술 검증
- ElevenLabs/절차적 합성 사운드 생성, 기술 QC와 DSP 보정
- 새 사운드 요청의 길이·루프·믹서·바인딩 계약 반영
- 검증된 ID의 에셋만 Unity 프로젝트에 복사하고 바인딩 manifest 생성

현재 자동 테스트 기준은 175개 통과, Unity 실컴파일 opt-in 테스트 1개 제외다.

## 3. 다음 구현 순서

### P0. 최종 결과의 정확성 완성

1. `final_validation`을 실제 검증 Node로 구현한다.
   - `LogicAnalysis.criteria`, `GameValidationResult`, 이미지·사운드 검증 결과와
     `AssetBindingManifest`를 함께 판정한다.
   - 최종 에셋 적용 후 Unity를 다시 열어 import/binding/컴파일/Play Mode를 검증한다.
   - 필수 기능, 필수 에셋, 시작부터 승리까지의 시나리오 중 하나라도 실패하면 `passed`가 될 수
     없게 한다.
   - 시작점: `mainflow/nodes/final_validation.py`.

2. 검증·보정된 에셋을 실제 적용 대상으로 만든다.
   - 현재 사운드 DSP 보정본은 `generated/sounds/processed/`에 저장되지만 Unity 적용기는
     `SoundDraft`의 원본을 복사한다.
   - 이미지·사운드 검증 결과에 최종 선택된 `ArtifactReference`를 명시하거나 별도
     `ValidatedAssetManifest` 계약을 추가한다.
   - 계약 변경 후 `mainflow/contracts.py`, `schemas/`, `docs/ContractRule.md`, mock과 테스트를
     한 번에 갱신한다.

3. 이미지·사운드 재생성 loop를 연결한다.
   - `needs_revision`을 최종 상태로 방치하지 말고 실패한 asset ID만 제한 횟수로 다시 생성한다.
   - 이미지 스타일/내용 적합성, 사운드 내용 적합성과 게임 내 음량·루프를 검사한다.
   - 동일 실패 signature 반복, 비용 한도와 시간 한도를 중단 조건으로 둔다.

4. `create_asset_validation_spec`을 설계 기반으로 변경한다.
   - 현재는 고정된 이미지·사운드 기준 목록을 반환한다.
   - `presentation_plan`, 에셋 `generation_spec`, 게임 검증 실패를 사용해 에셋별 기준을 생성한다.

### P1. 게임 복잡도와 플레이 품질 향상

1. 구현 작업 DAG를 실제 executor로 만든다.
   - 현재 module binding, content, zone, presentation 작업 일부는 구조가 있다는 이유로
     `mark_passed`된다.
   - 각 작업이 실제 파일·씬·컴포넌트를 생성하거나 검사하고 그 증거를 남기도록 바꾼다.
   - 시작점: `game_pipeline/implementation_task_planner.py`,
     `game_pipeline/game_development_loop.py`, `mainflow/nodes/design_game_logic.py`.

2. 플랫포머 vertical slice를 먼저 완성한다.
   - 3~5분 플레이, 3개 이상 구역, 튜토리얼→응용 난이도, 체크포인트와 명확한 클리어 흐름을
     실제 Play Mode 자동 시나리오로 보장한다.
   - 캐릭터 크기·점프 높이·대시 거리와 발판 폭·간격을 같은 단위의 이동 가능성 모델로 계산한다.
   - 적·함정·보상이 계획 데이터뿐 아니라 실제 씬 오브젝트와 동작으로 존재하는지 확인한다.

3. 나머지 장르의 전용 조립기를 확장한다.
   - 타워 디펜스: 경로, 웨이브, 건설 가능 영역, 경제와 승패 흐름
   - 카드: 덱/손패/코스트, 대상 선택, 턴 상태와 적 AI
   - 비주얼 노벨: 대화 그래프, 선택지 조건, 플래그와 엔딩
   - 육성 시뮬레이션: 일정, 능력치, 비용, 이벤트 조건과 기간 종료
   - 뱀서류: 웨이브/스폰, 경험치, 레벨업 선택, 무기 진화와 보스

4. 설계 비평 단계를 강화한다.
   - 7개 문서의 개별 형식 검증뿐 아니라 시스템·콘텐츠·레벨·밸런스 간 수치와 ID를 교차 검사한다.
   - 비평 결과로 관련 문서만 다시 생성하고, 마지막 검증된 문서는 유지한다.
   - 작은 모델에는 전체 게임을 한 번에 요청하지 않고 단계별 JSON과 필요한 문맥만 전달한다.

### P2. 서비스화와 평가

1. Local Web에 실제 Workflow API를 연결한다.
   - 요청 등록, background job, 진행 이벤트, 취소, 결과 목록/미리보기/ZIP 다운로드를 구현한다.
   - 현재 `CI/CD/LocalWeb`은 정적 화면과 health API만 제공한다.

2. 실행 재개와 비용 기록을 추가한다.
   - project ID를 이용한 checkpoint/resume, 단계별 모델·토큰·지연시간·재시도 원인을 기록한다.
   - 이미 통과한 설계와 생성물은 hash 기반으로 재사용한다.

3. 고정 평가 세트를 만든다.
   - 장르별 대표 요구사항, 난이도별 변형과 여러 seed를 fixture로 보관한다.
   - 생성 시간, 모델 호출 수, 입출력 토큰, Unity 컴파일 성공률, 자동 시나리오 통과율,
     요청 기능 연결률, 최종 품질 점수를 비교한다.
   - `tests/TestResult.md`는 이전 계약 3.1.0 결과이므로 새 자동 리포트로 교체해야 한다.

## 4. Codex 작업 시작 전 읽기 순서

다른 팀원이나 Codex는 다음 순서로 문서를 읽고 작업한다.

1. `AGENTS.md`: 포맷터와 Unity skill 사용 규칙
2. `docs/ContractRule.md`: Node와 payload 계약
3. `docs/FileSystem.md`: workspace와 artifact 경로
4. `mainflow/contracts.py`: 계약의 최종 기준
5. `schemas/game_spec.schema.json`, `schemas/asset_generation_request.schema.json`
6. `mainflow/langgraph_game_flow_skeleton.py`: 변경하면 안 되는 기본 Graph 순서
7. 담당 영역 문서
   - Unity: `unity_template/README.md`와 관련 `.agents/skills/*/SKILL.md`
   - 이미지: `docs/DockerManager.md`, `mainflow/image_generation.py`, `mainflow/image_backends.py`
   - 사운드: `docs/SoundManager.md`, `sound_pipeline/SoundValidationPlan.md`
   - MCP/LLM: `docs/MCPManager.md`, `MCP/`, `LocalAI/`

## 5. 주요 코드 진입점

- 전체 Graph: `mainflow/langgraph_game_flow_skeleton.py`
- 게임 파트 orchestration: `mainflow/nodes/design_game_logic.py`
- 7개 설계 문서: `game_pipeline/design_v2.py`, `game_pipeline/design_v2_planner.py`
- 구현 작업 DAG: `game_pipeline/implementation_task_planner.py`,
  `game_pipeline/game_development_loop.py`
- 기능 분석/모듈 선택: `game_pipeline/feature_planner.py`, `game_pipeline/design_catalog.py`
- 부족한 C# 생성: `game_pipeline/gemini_feature_generator.py`
- 구조화 프로젝트 인덱스: `game_pipeline/project_context_index.py`
- Unity 생성/검증/수정: `game_pipeline/unity_project_generator.py`,
  `game_pipeline/unity_project_validator.py`, `game_pipeline/repair_loop.py`
- Unity 씬 조립: `unity_template/Assets/GameTemplate/Editor/PrefabSceneAssembler.cs`
- Runtime 자동검증: `unity_template/Assets/GameTemplate/Editor/RuntimeSmokeValidator.cs`
- 에셋 적용: `game_pipeline/unity_asset_applicator.py`, `mainflow/nodes/apply_assets.py`
- 최종 검증: `mainflow/nodes/final_validation.py`
- 독립 게임 품질 Validator AI: `mainflow/nodes/game_quality_validator.py`,
  `game_pipeline/game_quality_validator_ai.py`

## 6. 변경 시 지켜야 할 규칙

- `asset_id`와 `unity_binding_key`를 생성·검증·Unity 적용 전 과정에서 바꾸지 않는다.
- State에는 큰 payload나 임의 파일 경로 대신 `ArtifactReference`를 전달한다.
- 산출물은 `ArtifactManager`로만 읽고 쓴다.
- 계약 필드를 바꾸면 Python TypedDict, JSON Schema, 문서, mock, producer와 consumer를 같은
  변경에서 갱신한다.
- 기존 모듈로 해결할 수 있는 기능은 LLM으로 다시 생성하지 않는다.
- 생성 모델이 repository-owned template, 테스트 또는 검증기를 수정하게 하지 않는다.
- Unity는 2D API만 사용하며 생성 C#에서 파일·네트워크·프로세스 실행을 허용하지 않는다.
- 게임 생성 실패가 이미지·사운드 병렬 branch를 중단시키지 않게 한다.
- Graph edge 변경은 join 조건과 실패 격리 테스트를 함께 수정할 때만 한다.

## 7. 권장 작업 단위와 완료 조건

한 PR은 하나의 계약 또는 하나의 실행 단계만 다룬다. 예를 들어 최종 검증 PR에는 다음을 함께
포함한다.

- 계약/Schema 변경과 migration 또는 하위 호환 처리
- 정상·부분 실패·필수 에셋 누락·Unity 실행 불가 테스트
- 실제 생성 프로젝트 fixture 또는 opt-in Unity 검증
- 관련 문서와 `.env.example` 갱신
- 실패 원인이 workspace의 `validation/` 아래에 재현 가능한 증거로 저장됨

작업 완료 전 다음 명령을 실행한다.

```powershell
uv run --locked python tools/format_repo.py --write
uv run --locked python tools/format_repo.py --check
uv run --locked python -m unittest discover -s tests -p "test_*.py"
docker compose build test
docker compose --profile test run --rm test
```

Unity가 설치된 환경에서는 다음도 실행한다.

```powershell
$env:MAINFLOW_RUN_UNITY_INTEGRATION_TESTS="1"
$env:MAINFLOW_UNITY_VALIDATION_MODE="required"
$env:UNITY_EDITOR_PATH="C:/Program Files/Unity/Hub/Editor/6000.0.71f1/Editor/Unity.exe"
uv run --locked python -m unittest tests.test_dynamic_feature_generation -v
```

## 8. 다음 담당자에게 권장하는 첫 작업

가장 먼저 `ValidatedAssetManifest` 계약과 `final_validation`을 구현한다. 현재 파이프라인은 게임을
설계하고 Unity를 생성하는 부분은 상당히 진행됐지만, “검증에서 선택된 최종 에셋이 실제 씬에
적용됐고 완성 게임이 요구사항을 만족한다”는 마지막 증명이 비어 있다. 이 부분을 먼저 닫아야 이후
장르 확장과 LLM 품질 개선 결과를 객관적으로 비교할 수 있다.

## 9. 후속 구현 기록 (2026-10-17)

P0 첫 작업으로 선택 파일 manifest와 최종 판정 단계를 연결했다.
`ValidatedAssetManifest`로 사운드 보정본을 적용하며, 최종 단계는 필수 에셋·선택 바이트·바인딩을
검사하고 Unity를 required 모드로 재실행한다. 통과 시 실행 이후 ZIP과 검증 증거를 반환한다.
기존 3.4.0 결과는 원본 적용까지 호환하되 새 선택 manifest 없이는 최종 통과하지 않는다.

남은 P0 작업은 내용 적합성 검증, 실패 ID별 재생성 loop, 설계 기반 에셋 검증 기준이다.
현재 `visual-style`과 `sound-mood`는 기술 QC만으로 증명할 수 없어 최종 단계에서 실패한다.
Unity 6000.0.71f1 설치 후 실제 컴파일·Play Mode와 최종 에셋 바인딩 검증까지 통과했다.
관련 두 테스트 모듈은 24개 모두 통과했으며 자세한 결과는 `tests/TestResult.md`에 기록했다.

에셋 적용 이후 실제 Unity 검증용 opt-in 테스트도 추가했다. Editor 설치 후 다음과 같이 실행한다.
기능 생성 검증과 함께 에셋 import·씬 바인딩·컴파일·Play Mode·최종 ZIP 경로를 확인한다.
이 fixture는 파일/바인딩/실행을 검증하며 이미지 스타일·사운드 분위기의 내용 적합성을 주장하지 않는다.

```powershell
$env:MAINFLOW_RUN_UNITY_INTEGRATION_TESTS="1"
$env:UNITY_EDITOR_PATH="C:/Program Files/Unity/Hub/Editor/6000.0.71f1/Editor/Unity.exe"
.venv/Scripts/python -m unittest tests.test_dynamic_feature_generation tests.test_final_unity_integration -v
```
