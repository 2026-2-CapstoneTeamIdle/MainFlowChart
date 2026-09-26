# Agent File System Rules

이 문서는 Agent가 생성한 실제 파일을 저장하고 다른 Agent에 전달하는 공통 규약이다. Python 구현의 기준은 [`ArtifactManager.py`](./ArtifactManager.py), 데이터 타입의 기준은 [`contracts.py`](./contracts.py)다.

## 1. Workspace 구조

`workspace`는 실행 중 생성되는 파일을 보관하는 로컬 작업 공간이며 Git에 커밋하지 않는다. 각 워크플로 실행은 하나의 `project_id`를 사용한다.

```text
workspace/                         # workspace/.gitignore로 내용 제외
└─ {project_id}/                   # 예: 20260926_03
   ├─ generated/
   │  ├─ images/                   # 이미지 파일과 image_draft.json
   │  └─ sounds/                   # 사운드 파일과 sound_draft.json
   ├─ game/                        # 게임 코드, 프로젝트 파일, 통합 결과
   ├─ data/                        # 요청/중간 데이터와 artifact_manifest.json
   └─ validation/                  # 검증 기준서와 검증 결과
```

`project_id` 형식은 `YYYYMMDD_NN`이다. `NN`은 해당 날짜에 생성된 프로젝트의 순번이며 두 자리 이상으로 표현한다. 예를 들어 2026년 9월 26일의 세 번째 프로젝트는 `20260926_03`이다. `ArtifactManager.create_project()`가 기존 폴더를 조회하고 다음 번호를 원자적으로 확보한다.

## 2. 폴더별 책임

| Category | 실제 경로 | 주요 생산자 | 주요 소비자 |
|---|---|---|---|
| `image` | `generated/images/` | `generate_image` | `validate_image`, `apply_assets_to_game` |
| `sound` | `generated/sounds/` | `generate_sound` | `validate_sound`, `apply_assets_to_game` |
| `game` | `game/` | `design_game_logic`, `apply_assets_to_game` | `validate_game`, `final_validation` |
| `data` | `data/` | `parse_input` 및 공통 시스템 | 요구사항을 읽는 모든 Agent |
| `validation` | `validation/` | 검증서/검증 Agent | 후속 검증 및 최종 검증 Agent |

`data/artifact_manifest.json`은 `ArtifactManager`가 관리한다. Agent가 직접 편집하면 안 된다.

## 3. Agent 간 파일 전달 방식

State에는 파일 내용이나 임의의 절대 경로 대신 `ArtifactReference`만 전달한다.

1. 생산 Agent가 `write_json`, `write_text`, `write_bytes` 또는 `import_file`을 호출한다.
2. `ArtifactManager`가 category에 맞는 폴더에 파일을 원자적으로 저장한다.
3. 파일의 ID, 상대 경로, 크기, SHA-256, 생산자 정보를 manifest에 기록한다.
4. 생산 Agent는 반환받은 `ArtifactReference`를 자신의 Output State 키에 넣는다.
5. 소비 Agent는 State의 참조를 `read_json`, `read_text`, `read_bytes`에 전달한다.
6. 관리자가 프로젝트 경계, 파일 크기, SHA-256을 확인한 뒤 내용을 반환한다.

```python
manager = ArtifactManager()
project_id = manager.create_project()

request_ref = manager.write_json(
    project_id,
    "data",
    "parsed_request.json",
    {"contract_version": "2.0.0", "genre": "Action"},
    producer="parse_input",
)

# State에는 request_ref만 전달한다.
parsed_request = manager.read_json(request_ref)
```

이미지 생성기처럼 외부 경로에 결과를 만드는 도구는 `import_file()`로 파일을 workspace 안에 복사한 다음 반환된 참조를 전달한다. Unity/Godot 등 외부 도구가 별도 경로를 요구하면 `materialize()`로 검증된 복사본을 만든다.

## 4. `ArtifactReference` 규격

```json
{
  "contract_version": "2.0.0",
  "artifact_id": "image-<uuid>",
  "project_id": "20260926_03",
  "category": "image",
  "relative_path": "generated/images/player.png",
  "media_type": "image/png",
  "size_bytes": 12345,
  "sha256": "<64자리 SHA-256>",
  "created_at": "2026-09-26T10:00:00+00:00",
  "producer": "generate_image"
}
```

참조의 `relative_path`를 직접 이어 붙여 읽지 않는다. 항상 `ArtifactManager`의 읽기 메서드를 사용한다.

## 5. 파일명과 수정 규칙

- 파일명은 영문 소문자 `snake_case`를 기본으로 하고 확장자를 명시한다.
- 동일한 논리 결과는 고정된 의미의 이름을 쓴다. 예: `image_validation_result.json`.
- 이미 등록된 산출물은 불변으로 취급한다. 수정본은 새 파일명으로 저장해 새 `artifact_id`를 발급한다.
- `overwrite=True`는 manifest 같은 시스템 파일이나 명시적으로 교체가 필요한 경우에만 사용한다.
- Agent가 `workspace` 외부 경로를 직접 State에 전달하지 않는다.
- `..`, 절대 경로 또는 category 폴더 밖으로 벗어나는 경로는 금지한다.
- JSON은 UTF-8, 들여쓰기 2칸, 마지막 줄바꿈을 사용한다.

## 6. 병렬 실행과 안전성

- 이미지, 게임, 사운드 Agent는 병렬 실행될 수 있으므로 서로 다른 category/파일을 쓴다.
- manifest 갱신은 `.artifact_manifest.lock`을 이용해 직렬화하며 완료 후 잠금 파일은 삭제된다.
- 실제 파일과 manifest는 임시 파일에 먼저 쓴 뒤 원자적으로 게시한다.
- 읽을 때 크기나 SHA-256이 다르면 손상 또는 외부 수정을 의미하므로 즉시 실패한다.
- 비밀키, API 토큰, 사용자 인증 정보는 workspace와 manifest에 저장하지 않는다.

## 7. Git 및 정리 정책

- `workspace/.gitignore`는 `.gitignore` 자신을 제외한 모든 런타임 프로젝트를 무시한다.
- 코드 리뷰에는 실제 생성물 대신 계약, fixture 또는 작은 테스트 데이터만 별도 테스트 폴더에 추가한다.
- 프로젝트 삭제는 실행 중인 Agent가 없고 결과 보존 여부를 확인한 뒤 수행한다.
- 자동 정리 기능을 추가할 경우 보존 기간과 복구 정책을 팀 합의로 먼저 정한다.

## 8. 변경 체크리스트

- [ ] 새 파일 종류에 맞는 `ArtifactCategory` 또는 기존 category를 선택했다.
- [ ] 생산 Agent가 `ArtifactManager`로 저장하고 참조만 반환한다.
- [ ] 소비 Agent가 `ArtifactManager`로 읽으며 직접 경로 접근을 하지 않는다.
- [ ] `contracts.py`의 Input/Output 및 payload 타입을 갱신했다.
- [ ] `ContractRule.md`와 이 문서를 같은 커밋에서 갱신했다.
- [ ] Graph의 핵심 노드와 Edge가 의도치 않게 바뀌지 않았는지 확인했다.
- [ ] 병렬 실행 시 파일명 충돌과 manifest 갱신을 검증했다.
