# Agent 데이터 계약 규칙

이 문서는 Agent 사이에서 교환하는 State와 파일 payload 규격을 정의한다. 기계 판독 기준은
`mainflow/contracts.py`이며, 현재 계약 버전은 **3.0.0**이다.

## 공통 원칙

1. Node는 자신의 Output 계약에 선언된 State key만 반환한다.
2. 실제 파일 내용이나 임의 경로 대신 `ArtifactReference`를 State로 전달한다.
3. 파일은 반드시 `ArtifactManager`로 저장하고 읽는다.
4. payload와 `ArtifactReference`에는 `contract_version`을 기록한다.
5. 계약 `3.0.0`은 `quality`를 제거하고 필수 사용자 입력 및 분석 흐름을 변경한 Major 버전이다.
6. `condition`은 비어 있지 않은 한 문장으로 보관하며, Analysis가 기능 요구사항으로 변환한다.
7. `image_style`이 `Custom`이면 PNG/JPG 파일을 함께 제공해야 한다.

## 사용자 입력 계약

| 필드 | 형식 | 허용 값 및 규칙 |
|---|---|---|
| `image_style` | `ImageStyle` | `Pixel Art`, `Anime`, `Cartoon`, `Realistic`, `Low Poly`, `Custom` |
| `mood_style` | `MoodStyle` | `Cyberpunk`, `Medieval`, `Modern`, `Fantasy`, `Horror`, `Cozy` |
| `genre` | `GameGenre` | `플랫포머`, `타워 디펜스`, `카드`, `비주얼 노벨`, `육성 시뮬레이션`, `뱀서류` |
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

- `title`, `genre`, `features`, `mechanics`, `controls`
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
- 생성 문맥: `creative_style`, `mood_style`, `output_directory`
- `assets`: `asset_id`, 용도, 설명, 필수 여부, 권장 파일명, `unity_binding_key`
- 생성 Flow는 `asset_id`와 `unity_binding_key`를 변경하지 않고 결과 draft에 반환한다.
- 같은 JSON은 workspace와 생성된 Unity 프로젝트의 `AssetRequests/` 양쪽에 저장한다.
- 기계 판독 스키마는
  [`schemas/asset_generation_request.schema.json`](../schemas/asset_generation_request.schema.json)이다.

### `LogicAnalysis`

- `logic_analysis_id`
- `genre`, `mood_style`
- `core_loop`: 장르에 따른 핵심 플레이 반복 구조
- `features`: Analysis가 전달한 기능 목록
- `criteria`: 게임·이미지·사운드·통합 최종 검증에 사용하는 기준

기존 `InitialFinalValidationSpec`은 제거됐다. 최종 검증 기준은 `LogicAnalysis.criteria`에서 읽는다.

## Node별 Input/Output

| Node | 입력 State | 출력 State | 출력 파일 |
|---|---|---|---|
| `user_input` | 선택적 사용자 입력 | 네 가지 필수 입력, 조건부 `custom_image_path` | 없음 |
| `parse_input` | 사용자 입력 | `project_id`, `parsed_request` | `data/parsed_request.json`, 조건부 Custom 이미지 |
| `analysis` | `project_id`, `parsed_request` | `analysis` | `data/analysis.json` |
| `logic_analysis` | `project_id`, `parsed_request`, `analysis` | `logic_analysis` | `data/logic_analysis.json` |
| `design_game_logic` | 위 세 참조와 `project_id` | 게임 draft, 이미지·사운드 요청 참조 | 설계 JSON, `game/asset_requests/*.json`, Unity 프로젝트, ZIP |
| `generate_image` | 분석 참조와 `image_asset_request` | `image_draft` | `generated/images/image_draft.json` |
| `generate_sound` | 분석 참조와 `sound_asset_request` | `sound_draft` | `generated/sounds/sound_draft.json` |
| `validate_game` | `parsed_request`, `logic_analysis`, 게임 draft | `game_validation_result` | validation 결과 |
| `create_asset_validation_spec` | 요청, 게임 검증 결과 | `asset_validation_spec` | validation 기준 |
| `validate_image` | 요청, 이미지 draft, 에셋 기준 | `image_validation_result` | validation 결과 |
| `validate_sound` | 요청, 사운드 draft, 에셋 기준 | `sound_validation_result` | validation 결과 |
| `apply_assets_to_game` | 세 draft와 이미지·사운드 검증 결과 | `integrated_game` | 통합 게임 |
| `final_validation` | `logic_analysis`, 통합 게임 | `final_validation_result` | 최종 검증 결과 |

## 변경 체크리스트

- `contracts.py`의 payload, State, Agent I/O를 함께 수정한다.
- 생산 Node와 mock Node를 함께 수정한다.
- `CONTRACT_VERSION`, 예제 요청, Docker 기본 명령을 갱신한다.
- `ContractRule.md`, `FileSystem.md`, Workflow 그림을 갱신한다.
- Python formatter와 전체 테스트를 실행한다.
