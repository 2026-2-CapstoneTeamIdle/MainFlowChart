# Agent Data Contract Rules

이 문서는 `MainFlowChart` 워크플로에서 Agent 사이에 교환하는 데이터 규격의 사람용 기준서다. 실제 Python 타입의 단일 기준(source of truth)은 [`contracts.py`](./contracts.py)이며, 데이터 규격을 추가하거나 변경할 때는 **두 파일을 같은 커밋에서 함께 수정한다.**

## 1. 공통 원칙

1. 모든 Agent는 전체 State를 임의로 수정하지 않고, 자신의 Output 계약에 선언된 키만 반환한다.
2. Agent 입력은 State 전체가 전달되더라도 Input 계약에 선언된 키만 의존한다.
3. Agent 간 payload와 `ArtifactReference`에는 `contract_version`을 포함한다. 현재 버전은 `2.0.0`이다.
4. State는 노드가 순차·병렬로 채우므로 `WorkflowState`만 부분 상태(`total=False`)를 허용한다. 개별 payload와 Agent Output의 필드는 기본적으로 필수다.
5. State에는 대용량 payload나 파일 경로를 직접 넣지 않고 `ArtifactReference`만 넣는다. 소비 Agent는 반드시 `ArtifactManager`로 실제 파일을 읽는다.
6. 값이 아직 생성되지 않은 참조는 빈 문자열 대신 `null`(`None`)을 사용한다. 여러 값은 값이 없어도 빈 배열 `[]`을 사용한다.
7. ID는 실행 중 중복되지 않는 문자열로 만든다. 권장 형식은 `<종류>-<UUID>`이며, 다른 payload에서는 ID로 참조한다.
8. 실제 경로는 `ArtifactManager`만 조합한다. 외부 저장소를 쓸 때도 비밀키나 접근 토큰은 payload에 넣지 않는다.
9. 상태값은 `contracts.py`에 선언된 `Literal` 값만 쓴다. 임의 문자열을 추가하지 않는다.
10. 치명적 실패는 잘못된 형태의 payload를 반환하지 말고 예외로 전달한다. 복구 가능한 검증 실패는 `status`, `checks`, `issues`로 표현한다.
11. 결정적인 Graph 노드와 Edge를 바꾸려면 별도의 팀 합의가 필요하다. 계약 변경만으로 Flow를 임의 변경하지 않는다.

## 2. 버전 변경 규칙

- **Patch** (`1.0.x`): 설명 보완, 타입 의미를 바꾸지 않는 수정.
- **Minor** (`1.x.0`): 선택 필드 또는 하위 호환 가능한 상태값 추가.
- **Major** (`x.0.0`): 필수 필드 삭제·이름 변경·타입 변경 등 기존 Agent가 깨지는 변경.
- 계약을 변경한 사람은 생산 Agent와 소비 Agent 양쪽을 함께 수정하고, 아래 Agent 계약표도 갱신한다.
- 소비 Agent는 자신이 지원하지 않는 Major 버전의 payload를 처리하지 말고 명시적으로 실패시킨다.

## 3. Agent별 Input / Output

LangGraph는 각 노드에 전체 State를 넘기지만, 아래 Input은 해당 Agent가 읽어도 되는 최소 범위다. Output은 State에 합쳐지는 patch다. `project_id`를 제외한 파일 기반 State 값은 모두 `ArtifactReference`이며 실제 payload는 `workspace`에 저장된다.

| Agent(Node) | Input 계약 | 읽는 State 키 | Output 계약 | 쓰는 State 키 |
|---|---|---|---|---|
| `user_input` | `UserInputAgentInput` | 없음 | `UserInputAgentOutput` | `image_style`, `genre`, `quality` |
| `parse_input` | `ParseInputAgentInput` | `image_style`, `genre`, `quality` | `ParseInputAgentOutput` | `project_id`, `parsed_request` |
| `create_initial_final_validation_spec` | `InitialValidationSpecAgentInput` | `project_id`, `parsed_request` | `InitialValidationSpecAgentOutput` | `initial_final_validation_spec` |
| `generate_image` | `GenerateImageAgentInput` | `project_id`, `parsed_request`, `initial_final_validation_spec` | `GenerateImageAgentOutput` | `image_draft` |
| `design_game_logic` | `DesignGameLogicAgentInput` | `project_id`, `parsed_request`, `initial_final_validation_spec` | `DesignGameLogicAgentOutput` | `game_logic_draft` |
| `generate_sound` | `GenerateSoundAgentInput` | `project_id`, `parsed_request`, `initial_final_validation_spec` | `GenerateSoundAgentOutput` | `sound_draft` |
| `validate_game` | `ValidateGameAgentInput` | `project_id`, `parsed_request`, `initial_final_validation_spec`, `game_logic_draft` | `ValidateGameAgentOutput` | `game_validation_result` |
| `create_asset_validation_spec` | `AssetValidationSpecAgentInput` | `project_id`, `parsed_request`, `game_validation_result` | `AssetValidationSpecAgentOutput` | `asset_validation_spec` |
| `validate_image` | `ValidateImageAgentInput` | `project_id`, `parsed_request`, `image_draft`, `asset_validation_spec` | `ValidateImageAgentOutput` | `image_validation_result` |
| `validate_sound` | `ValidateSoundAgentInput` | `project_id`, `parsed_request`, `sound_draft`, `asset_validation_spec` | `ValidateSoundAgentOutput` | `sound_validation_result` |
| `apply_assets_to_game` | `ApplyAssetsAgentInput` | `project_id`, `game_logic_draft`, 두 draft, 두 validation result | `ApplyAssetsAgentOutput` | `integrated_game` |
| `final_validation` | `FinalValidationAgentInput` | `project_id`, `initial_final_validation_spec`, `integrated_game` | `FinalValidationAgentOutput` | `final_validation_result` |

## 4. Payload 규격

### `ParsedRequest`

- `contract_version`: 계약 버전
- `image_style`: `Pixel Art | Anime | Cartoon | Realistic | Low Poly`
- `genre`: `Action | RPG | Platformer | Puzzle | Simulation`
- `quality`: `Low | Medium | High`

### `ArtifactReference`

- `contract_version`: 참조 규격 버전
- `artifact_id`: manifest 안에서 유일한 파일 ID
- `project_id`: 파일이 속한 프로젝트 ID
- `category`: `image | sound | game | data | validation`
- `relative_path`: 프로젝트 루트 기준 상대 경로
- `media_type`, `size_bytes`: 파일 형식과 크기
- `sha256`: 소비 시 무결성을 확인하는 체크섬
- `created_at`: UTC ISO 8601 생성 시각
- `producer`: 파일을 만든 Agent(Node) 이름

### 검증 기준서

- `InitialFinalValidationSpec`: `spec_id`, 최종 검증용 `criteria`
- `AssetValidationSpec`: `spec_id`, `image_criteria`, `sound_criteria`
- 각 `ValidationCriterion`: `criterion_id`, `target`, `description`, `required`
- `target`: `game | image | sound | integration`

### 생성 Draft

- `ImageDraft`: `draft_id`, `status`, `assets`, `notes`
- `SoundDraft`: `draft_id`, `status`, `assets`, `notes`
- `GameLogicDraft`: `draft_id`, `status`, `engine`, `entry_scene`, `source_artifacts`, 필요한 이미지/사운드 ID 목록, `notes`
- Draft `status`: `pending | generated | failed`
- 이미지 에셋은 실제 파일의 `artifact`, 크기(`width`, `height`)와 생성 `prompt`를 포함한다.
- 사운드 에셋은 실제 파일의 `artifact`, 길이(`duration_seconds`)와 생성 `prompt`를 포함한다.

### 검증 결과

- 공통 `status`: `pending | passed | failed | needs_revision`
- `checks`: 기준별 `criterion_id`, `passed`, `message`
- `issues`: `code`, `severity`, `message`와 선택적인 `target_id`
- 이미지/사운드 검증 결과는 `validated_asset_ids`를 추가로 포함한다.
- `severity`: `info | warning | error`

### `IntegratedGame`

- `status`: `pending | integrated | failed`
- `entry_artifact`: 실행 진입 파일 참조. 아직 없으면 `null`.
- `game_artifacts`: 통합된 게임을 이루는 전체 파일 참조 목록
- `applied_image_asset_ids`, `applied_sound_asset_ids`: 실제 적용된 에셋 ID 목록
- `notes`: 통합 과정의 비정형 메모

## 5. 변경 체크리스트

- [ ] `contracts.py`의 도메인 payload 타입을 수정했다.
- [ ] 관련 Agent Input/Output 타입을 수정했다.
- [ ] 생산 Agent와 소비 Agent 구현을 모두 수정했다.
- [ ] `WorkflowState`에 필요한 키가 정확히 반영됐다.
- [ ] 이 문서의 표와 payload 설명을 수정했다.
- [ ] 파일 배치나 교환 방식이 바뀌면 `FileSystem.md`도 수정했다.
- [ ] 호환성에 맞게 `CONTRACT_VERSION`을 올렸다.
- [ ] Graph의 핵심 노드/Edge가 의도치 않게 바뀌지 않았는지 확인했다.
- [ ] 컴파일 또는 타입 검사를 수행했다.
