# Agent 데이터 계약 규칙

이 문서는 Agent 사이에서 교환하는 State와 파일 payload 규격을 정의한다. 기계 판독 기준은
`mainflow/contracts.py`이며, 현재 계약 버전은 **3.4.0**이다.

## 공통 원칙

1. Node는 자신의 Output 계약에 선언된 State key만 반환한다.
2. 실제 파일 내용이나 임의 경로 대신 `ArtifactReference`를 State로 전달한다.
3. 파일은 반드시 `ArtifactManager`로 저장하고 읽는다.
4. payload와 `ArtifactReference`에는 `contract_version`을 기록한다.
5. 계약 `3.4.0`은 게임 설계를 7개 v2 문서로 분리하고 `level_plan`을 Unity Scene 조립에 전달한다.
6. `condition`은 비어 있지 않은 한 문장으로 보관하며, Analysis가 기능 요구사항으로 변환한다.
7. `image_style`이 `Custom`이면 PNG/JPG 파일을 함께 제공해야 한다.

## 사용자 입력 계약

| 필드 | 형식 | 허용 값 및 규칙 |
|---|---|---|
| `image_style` | `ImageStyle` | `Pixel Art`, `Anime`, `Cartoon`, `Realistic`, `Low Poly`, `Custom` |
| `mood_style` | `MoodStyle` | `Cyberpunk`, `Medieval`, `Modern`, `Fantasy`, `Horror`, `Cozy` |
| `genre` | `GameGenre` | `플랫포머`, `타워 디펜스`, `카드`, `비주얼 노벨`, `육성 시뮬레이션`, `뱀서류` |
| `viewpoint` | `Viewpoint` | `사이드뷰`, `탑다운`, `쿼터뷰`, `고정 화면` |
| `condition` | `str` | 사용자의 요구를 담은 비어 있지 않은 한 문장 |
| `custom_image_path` | `str` | `image_style=Custom`일 때만 필요한 PNG/JPG 원본 경로 |

`custom_image_path`는 외부 입력 경계에서만 사용한다. `parse_input`이 파일을 workspace로 가져온
후에는 `ParsedRequest.custom_image`의 `ArtifactReference`만 전달한다.

## 핵심 payload

### `ParsedRequest`

- `contract_version`
- `image_style`
- `mood_style`
- `genre`
- `viewpoint`
- `condition`
- `custom_image`: Custom 참고 이미지의 `ArtifactReference`, 없으면 `null`

### `AnalysisResult`

- `analysis_id`
- `condition_summary`: 원문 조건
- `features`: `FeatureRequirement` 목록

`FeatureRequirement`은 `feature_id`, `name`, `description`, `source_text`로 구성한다. 현재
Analysis 구현은 알려진 기능 표현을 규칙 기반으로 추출하고, 일치 항목이 없으면 조건 전체를
`사용자 지정 조건` 기능으로 보존한다. 향후 LLM 분석기로 교체해도 이 출력 계약을 유지한다.

### `GameSpec`

`design_game_logic`은 분석된 기능과 장르 프리셋을 결합해 Unity 구현용 `GameSpec`을 만든다.

- `title`, `genre`, `viewpoint`, `features`, `mechanics`, `controls`
- `win_conditions`, `lose_conditions`, `target_engine`
- `asset_requirements`: 게임 설계가 이미지·사운드 요청 JSON으로 분리하는 에셋 요구사항
- `asset_id`: 한 워크플로 안에서 중복되지 않는 불투명 ID. 문자열을 분석해 종류를 추론하지 않는다.
- `asset_type`: `image | sound`
- `purpose`, `description`, `required`: 용도, 생성 설명, 필수 여부
- `asset_id`는 게임 설계에서 한 번 정하고 이미지·사운드 생성 및 Unity 적용 단계가 그대로 사용한다.
- 상세 JSON 규격의 기준은 [`schemas/game_spec.schema.json`](../schemas/game_spec.schema.json)이다.

### `AssetGenerationRequest`

`design_game_logic`은 Unity 프로젝트에 필요한 에셋을 이미지와 사운드 요청으로 분리한다.

- 공통: `request_id`, `source_design_id`, `game_title`, `genre`, `asset_type`
- 생성 문맥: `image_style`, `mood_style`, `viewpoint`, `reference_image`, `output_directory`
- `assets`: `asset_id`, 용도, 설명, 필수 여부, 권장 파일명, `unity_binding_key`, `generation_spec`
- 생성 Flow는 `asset_id`와 `unity_binding_key`를 변경하지 않고 결과 draft에 반환한다.
- 이미지 `generation_spec`: 종류, 출력 크기, 투명도, Sprite Mode, Pixels Per Unit을 포함한다.
  타일셋은 32×32 타일을 4열×4행으로 배치한 128×128 PNG를 기본값으로 사용한다.
- 사운드 `generation_spec`: 종류, 목표 길이(초), loop, mono/stereo, sample rate, Unity load type,
  mixer group, 2D/3D 혼합값(`spatial_blend`)을 포함한다. 기본값은 BGM 90초 loop/streaming,
  환경음 60초 loop/streaming, 효과음 1초 non-loop/decompress-on-load이다.
- 같은 JSON은 workspace와 생성된 Unity 프로젝트의 `AssetRequests/` 양쪽에 저장한다.
- 이미지 요청의 `reference_image`에는 Custom 참고 이미지의 `ArtifactReference`가 들어가며,
  참고 이미지가 없거나 사운드 요청이면 `null`이다.
- 이미지·사운드 요청 모두 공통 정보인 `image_style`, `genre`를 유지한다. 이미지 생성은 여기에
  `mood_style`, `viewpoint`, `reference_image`를 함께 사용하고, 사운드 생성은 `mood_style`을
  우선적인 생성 문맥으로 사용한다.
- 기계 판독 스키마는
  [`schemas/asset_generation_request.schema.json`](../schemas/asset_generation_request.schema.json)이다.

### `ValidatedAssetManifest` (추가 계약)

이미지·사운드 검증 결과의 `validated_assets`는 다음 객체를 담는다.

- `manifest_version=1.0.0`, `contract_version=3.4.0`
- `assets[]`: `asset_id`, `asset_type`, `unity_binding_key`, `artifact`, `file_format`
- `assets`의 ID 집합은 `validated_asset_ids`와 같아야 하며 중복을 허용하지 않는다.
- 이미지는 검증된 원본을 선택한다. 사운드는 DSP 보정본이 있으면 보정 WAV 참조와 `file_format=wav`를 선택한다.
- 스키마: [`validated_asset_manifest.schema.json`](../schemas/validated_asset_manifest.schema.json).

기존 3.4.0 payload를 읽기 위해 이 필드는 TypedDict에서 선택적이다. 기존 ID 목록만 가진 결과는
적용기에서 원본 적용까지 호환하지만, 최종 검증에서는 선택 파일 증거가 없으므로 실패한다.
현재 producer와 mock은 항상 새 manifest를 기록한다. 기본 Graph 순서와 기존 계약 버전은 유지한다.

`IntegratedGame.asset_binding_manifest`는 workspace 바인딩 manifest의 `ArtifactReference`다.
최종 검증을 통과한 패키지는 `FinalValidationResult.entry_artifact`로 전달하며, 적용 직후의
`IntegratedGame.entry_artifact` ZIP과 구분한다. 실패 시 최종 패키지 참조는 `null`이다.
`FinalValidationResult.evidence`에는 최종 Unity 로그와 바인딩 보고서 참조가 들어간다.

### `LogicAnalysis`

- `logic_analysis_id`
- `genre`, `viewpoint`, `mood_style`
- `core_loop`: 장르에 따른 핵심 플레이 반복 구조
- `features`: Analysis가 전달한 기능 목록
- `criteria`: 게임·이미지·사운드·통합 최종 검증에 사용하는 기준

기존 `InitialFinalValidationSpec`은 제거됐다. 최종 검증 기준은 `LogicAnalysis.criteria`에서 읽는다.

### `GameBlueprint`

`design_game_logic`은 장르 프리셋을 최소 실행 기반으로만 사용하고, 요청 문장별 Blueprint를 만들어
Unity 조립기에 전달한다. Blueprint에는 장면 크기·배경 색, 콘텐츠 밀도, 엔티티 위치·색·역할,
핵심 루프, 성장 선택지, UI 라벨이 포함된다. Unity는 고정 샘플 씬 대신 이 Blueprint를 읽어
기존 모듈의 콘텐츠 수를 조정하고 추가 엔티티를 배치한다. 플랫폼 게임은 안전한 점프 범위 안에서
경로·수집물·위험물·목표 위치를 다시 조립하고, 타워 디펜스는 적 경로를, 뱀서류는 맵 반경과
특전 풀을 Blueprint에 맞게 바꾼다.

기본 제공자는 `deterministic`이며 외부 모델 호출 없이 항상 실행된다. `MAINFLOW_BLUEPRINT_PROVIDER`
를 `local` 또는 `gemini`로 설정하면 해당 모델이 Blueprint만 제안한다. 제안은 JSON Schema와
필수 콘텐츠·엔티티 검증을 통과해야 하며, 실패·시간 초과 시에는 전체 파이프라인을 중단하지 않고
기본 Blueprint를 유지한다. 모델은 C# 코드, 파일 경로, Unity 패키지를 생성할 수 없다.

### `DesignV2Bundle`

`design_game_logic`은 작은 모델이 한 번에 전체 게임을 생성하지 않도록 설계를 다음 문서로
분리한다.

- `game_design`: 핵심 경험, 목표 시간, 차별점, 초·중·후반 경험, 승패 조건
- `system_design`: 플레이어·적 상태, 공식, 자원, 진행, 저장 데이터, 이벤트 연결
- `content_plan`: 적·장애물·보상·스테이지·최종 목표 데이터
- `level_plan`: 구역, 도전, 보상, 체크포인트와 실제 씬 배치 좌표
- `balance_plan`: 초기 능력치, 허용 범위, 공식, 난이도 곡선
- `presentation_plan`: UI 상태, 피드백, 카메라, 파티클, 애니메이션, 에셋 ID
- `validation_plan`: 시작부터 클리어까지의 시나리오와 진행 불가·배치·바인딩 검사

플랫포머 `level_plan`은 최소 3개 구역을 가져야 하며 발판 폭·수평 간격·상승 높이가 계획에
기록된 이동 한계를 벗어나면 LLM 결과를 사용하지 않는다. Unity의 `PrefabSceneAssembler`는
고정 발판 패턴이 아니라 이 문서를 읽어 구역 계층과 콘텐츠를 생성한다.

### `ImplementationTaskPlan`

설계가 끝나면 `design_game_logic`은 구현을 의존성 있는 작업 목록으로 변환한다. 기본 작업은
설계 검토, 기존 모듈 선택·바인딩, 콘텐츠 구성, 구역별 조립, UI·연출 바인딩, Unity 프로젝트
생성, Unity 검증, 객관적 품질 평가, 패키징이며, 미지원 기능마다 별도의 코드 생성 작업이 추가된다.
각 작업은 `max_attempts`, `attempts`, `status`, `evidence`,
`last_error`를 가져야 한다. 선행 작업이 통과하기 전에는 후속 작업을 실행하지 않고, 작업별 재시도
한도와 전체 시간 예산을 넘기면 실패한다. 최종 상태는 `game/implementation_tasks.json`과 생성된
Unity 프로젝트의 `Assets/GameTemplate/Generated/ImplementationTasks.json`에 함께 기록한다.

Unity 검증 실패는 `code`, `scene`, `level_plan`, `balance_plan`, `content_plan`, `binding`,
`test`, `infrastructure`로 분류한다. 코드·바인딩 실패만 생성 모델에 피드백하고, 경로 폭·간격,
능력치 범위, 콘텐츠 개수 같은 결정적 오류는 해당 설계 JSON을 보정한 뒤 프로젝트를 다시 만든다.
동일 실패 signature가 반복되거나 전체 재시도·시간 예산을 넘으면 루프를 중단한다.

Play Mode 검증은 `UNITY_PLAYTEST_METRICS` JSON 로그로 완료 여부, 경과 시간, 사망·정체 시간,
최종 도달 구역, 실패 전환, 미사용 요청 기능, 통과 시나리오를 남긴다. 이를 기능 연결, 시나리오,
구역 구조, 콘텐츠 밀도·다양성, UI 피드백, 난이도 상승, 요청 기능 사용의 100점 척도로 평가한다.
결과는 `game/game_quality_report.json`과 생성 프로젝트의
`Assets/GameTemplate/Generated/Validation/GameQualityReport.json`에 저장한다.

## Node별 Input/Output

| Node | 입력 State | 출력 State | 출력 파일 |
|---|---|---|---|
| `user_input` | 선택적 사용자 입력 | 다섯 가지 필수 입력, 조건부 `custom_image_path` | 없음 |
| `parse_input` | 사용자 입력 | `project_id`, `parsed_request` | `data/parsed_request.json`, 조건부 Custom 이미지 |
| `analysis` | `project_id`, `parsed_request` | `analysis` | `data/analysis.json` |
| `logic_analysis` | `project_id`, `parsed_request`, `analysis` | `logic_analysis` | `data/logic_analysis.json` |
| `design_game_logic` | 위 세 참조와 `project_id` | 게임 draft, 이미지·사운드 요청 참조 | 7개 v2 설계 JSON, `game/implementation_tasks.json`, `game/project_context_index.json`, 단계별 실행 증거, `game/asset_requests/*.json`, Unity 프로젝트, ZIP |
| `generate_image` | 분석 참조와 `image_asset_request` | `image_draft` | `generated/images/image_draft.json` |
| `generate_sound` | 분석 참조와 `sound_asset_request` | `sound_draft` | `generated/sounds/sound_draft.json` |
| `validate_game` | `parsed_request`, `logic_analysis`, 게임 draft | `game_validation_result` | validation 결과 |
| `create_asset_validation_spec` | 요청, 게임 검증 결과 | `asset_validation_spec` | validation 기준 |
| `validate_image` | 요청, 이미지 에셋 요청, 이미지 draft, 에셋 기준 | `image_validation_result` | validation 결과 |
| `validate_sound` | 요청, 사운드 에셋 요청, 사운드 draft, 에셋 기준 | `sound_validation_result` | validation 결과 |
| `apply_assets_to_game` | 세 draft와 이미지·사운드 검증 결과 | `integrated_game` | 통합 게임 |
| `final_validation` | `parsed_request`, `logic_analysis`, 게임 draft, 게임·이미지·사운드 검증 결과, 통합 게임 | `final_validation_result` | 최종 검증 결과 |
| `game_quality_validator` | 전체 요구사항, draft, 게임·이미지·사운드·최종 검증 결과, 통합 게임 | `game_validator_ai_result` | 독립 AI 품질 평가 |

`game/project_context_index.json`은 자연어 요약이 아니라 생성된 C#을 결정적으로 스캔한 계약이다.
파일 해시, 클래스와 상속 관계, 공개 메서드·속성·필드·이벤트, `module_id`, 기능 및 검증 기준 ID,
설계 이벤트 연결을 원문 구조로 보존한다. 코드 생성기와 Validator는 이 인덱스에 없는 프로젝트
멤버를 존재한다고 가정할 수 없다.

### `validate_game` 실행 모드

`validate_game`은 Unity 프로젝트 구조, 계약 버전, 장르·시점·스타일 문맥, 선택 모듈과
이미지·사운드 `asset_id` 일관성을 항상 검사한다. Unity Editor를 사용할 수 있으면 Batch Mode로
C# 컴파일, 전체 모듈 부착, Bootstrap 씬 조립까지 검사하고 로그를
`validation/unity_validation.log`에 저장한다.

- `MAINFLOW_UNITY_VALIDATION_MODE=auto`: 기본값. 프로젝트 버전에 맞는 Unity를 찾아 실행하고,
  설치되지 않았으면 정적 검증 통과와 함께 경고를 기록한다.
- `MAINFLOW_UNITY_VALIDATION_MODE=required`: Unity 실행이 불가능하거나 배치 검증이 실패하면
  게임 검증을 실패 처리한다.
- `MAINFLOW_UNITY_VALIDATION_MODE=static`: Unity를 실행하지 않고 정적 검사만 수행한다.
- `UNITY_EDITOR_PATH`: 자동 탐색 대신 사용할 Unity 실행 파일 경로다.
- `MAINFLOW_UNITY_VALIDATION_TIMEOUT_SECONDS`: Unity Batch Mode 제한 시간이며 기본값은 300초다.

### `final_validation` 판정

최종 단계는 `pending` 대신 `passed` 또는 `failed`를 기록한다. 게임·이미지·사운드의 선행 검증,
필수 에셋 ID, 선택된 파일의 checksum/바이트, 바인딩 키, workspace와 Unity manifest의 일치성을 검사한다.
이전 바인딩 보고서를 비운 후 `UnityProjectValidator(mode="required")`로 import/컴파일/씬 조립과
Play Mode를 다시 실행한다. `MAINFLOW_UNITY_VALIDATION_MODE=static` 또는 `auto`로 앞 단계를
실행해도 최종 통과에는 실제 Unity 실행이 필요하다. 런타임 검증을 끄거나 Unity를 찾지 못하면 실패한다.

모든 적용 에셋은 새 보고서에서 import·registry 등록·씬 바인딩 증거를 가져야 한다. 모든 설계 시나리오와
`start_to_goal`이 통과하고, 요청 기능의 모듈 바인딩과 미사용 기능 기록도 검증한다.
`LogicAnalysis.criteria`는 같은 ID의 명시적 검증 결과 또는 기능별 Play Mode 증거로 판정한다.
일치하는 증거가 없는 필수 기준은 실패한다. 특히 현재 기술 QC만으로 이미지의 `visual-style`이나
사운드의 `sound-mood`가 통과했다고 추정하지 않는다. 내용 적합성 검증을 연결하기 전에는 이 기준이
최종 통과를 막을 수 있다. 알 수 없는 선택 기준, 손상된 참조와 잘못된 설정도 실패 결과에 기록한다.

통과 시 Unity 실행 이후 프로젝트를 다시 ZIP으로 만든다. CLI는 최종 검증이 실패하면 종료 코드 1을 반환한다.

### `game_quality_validator` 판정

- 모든 결정적 검사와 Unity Play Mode 검증이 끝난 뒤 읽기 전용으로 실행한다.
- 요구사항 충족, 핵심 루프, 진행 가능성, 밸런스, 콘텐츠, UI·피드백, 에셋 통합을 평가한다.
- 파일 경로나 검증 check ID가 없는 주장은 통과 근거로 인정하지 않는다.
- 기존 하드 검증의 실패를 AI가 `passed`로 뒤집을 수 없다.
- 결과는 `passed`, `needs_revision`, `failed` 중 하나와 0~100점, 항목별 근거를 포함한다.

## 변경 체크리스트

- `contracts.py`의 payload, State, Agent I/O를 함께 수정한다.
- 생산 Node와 mock Node를 함께 수정한다.
- `CONTRACT_VERSION`, 예제 요청, Docker 기본 명령을 갱신한다.
- `ContractRule.md`, `FileSystem.md`, Workflow 그림을 갱신한다.
- Python formatter와 전체 테스트를 실행한다.
