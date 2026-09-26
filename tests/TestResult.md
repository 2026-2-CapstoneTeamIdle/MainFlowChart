# Mock Graph Test Result

## 1. 테스트 목적과 범위

- 테스트 일자: 2026-09-26
- 실행 환경: Windows, Python 3.11.16 (`uv run --offline`)
- 실행 명령: `uv run --offline python -m unittest discover -s tests -v`
- 테스트 대상: 운영 코드의 `contracts.py`, `ArtifactManager.py`, workspace 규약
- 교체 대상: 실제 `langgraph_game_flow_skeleton.py`의 Node 구현만 `tests/mock_nodes.py`의 결정론적 mock으로 교체
- Flow: 운영 Graph와 같은 의존 순서 및 join 조건 사용
- 시간 측정은 `ThreadPoolExecutor`로 동일 DAG를 재현하며, 별도 테스트에서 같은 mock Node를 실제 LangGraph `StateGraph.compile().invoke()`로도 실행한다.

mock에는 의도적인 처리 지연 fixture가 포함된다. 따라서 아래 수치는 단순 `sleep` 시간이 아니라 파일 생성, 원자적 저장, manifest 잠금, SHA-256 검증, JSON 직렬화 비용이 함께 반영된 end-to-end 시간이다.

## 2. 테스트 구조

```text
tests/
├─ mock_nodes.py
├─ test_artifact_manager.py
├─ test_mock_graph.py
├─ TestResult.md
└─ fixtures/
   ├─ mock_request.json
   └─ mock_timing.json
```

`mock_nodes.py`는 다음과 같은 실제 파일을 생성하고 후속 Node가 다시 읽는다.

- 파싱된 사용자 요청 JSON
- 최종/에셋 검증 기준 JSON
- 실제 파싱 가능한 SVG 이미지
- 실제 읽을 수 있는 WAV 사운드
- 컴파일하고 실행할 수 있는 Python mock 게임 코드
- 이미지·사운드·게임 검증 결과
- 통합 게임 package와 최종 검증 결과

## 3. 테스트 결과 요약

| 항목 | 결과 |
|---|---:|
| 전체 unittest | 6개 통과 |
| 실패/오류 | 0개 |
| 최종 검증 상태 | `passed` |
| 최종 검증 항목 | 4/4 통과 |
| 생성된 artifact | 15개 |
| 대표 1차 전체 실행 시간 | 912.448ms |
| 대표 1차 Node 시간의 순차 합 | 1555.795ms |
| 대표 1차 추정 병렬 가속 | 1.705배 |

동일 테스트의 2차 결과는 전체 855.717ms, 순차 합 1486.388ms, 추정 병렬 가속 1.737배였고, 실제 LangGraph 통합 테스트를 추가한 뒤의 3차 결과는 전체 849.766ms, 순차 합 1471.801ms, 병렬 가속 1.732배였다. 세 실행 평균은 전체 872.644ms, 순차 합 1504.661ms, 병렬 가속 1.725배이며 기능 결과와 모든 성공 조건은 동일했다. 아래 Node별 표는 추적 가능한 대표 1차 실행값이다.

Artifact category별 결과:

| Category | 개수 | 주요 파일 |
|---|---:|---|
| `data` | 1 | `parsed_request.json` |
| `image` | 2 | `player.svg`, `image_draft.json` |
| `sound` | 2 | `theme.wav`, `sound_draft.json` |
| `game` | 4 | `mock_game.py`, `game_logic_draft.json`, `mock_package.json`, `integrated_game.json` |
| `validation` | 6 | 최초 기준서, 게임/에셋/이미지/사운드/최종 검증 결과 |

모든 artifact는 manifest 등록 후 `ArtifactManager.read_bytes()`로 다시 읽었으며 크기와 SHA-256 검증을 통과했다.

## 4. Node별 Input / Output 및 대표 측정 시간

| Node | 주요 Input State 키 | Output State 키 | Thread | 측정 시간 |
|---|---|---|---|---:|
| `user_input` | 없음 | `image_style`, `genre`, `quality` | MainThread | 5.370ms |
| `parse_input` | 사용자 입력 3종 | `project_id`, `parsed_request` | MainThread | 54.717ms |
| `create_initial_final_validation_spec` | `project_id`, `parsed_request` | `initial_final_validation_spec` | MainThread | 43.318ms |
| `generate_image` | `project_id`, 요청, 최초 기준서 | `image_draft` | mock-generation_0 | 374.103ms |
| `design_game_logic` | `project_id`, 요청, 최초 기준서 | `game_logic_draft` | mock-generation_1 | 212.427ms |
| `generate_sound` | `project_id`, 요청, 최초 기준서 | `sound_draft` | mock-generation_2 | 151.562ms |
| `validate_game` | 요청, 최초 기준서, 게임 draft | `game_validation_result` | MainThread | 100.551ms |
| `create_asset_validation_spec` | 요청, 게임 검증 결과 | `asset_validation_spec` | MainThread | 115.555ms |
| `validate_image` | 요청, 이미지 draft, 에셋 기준서 | `image_validation_result` | mock-validation_0 | 177.291ms |
| `validate_sound` | 요청, 사운드 draft, 에셋 기준서 | `sound_validation_result` | mock-validation_1 | 119.994ms |
| `apply_assets_to_game` | 게임/이미지/사운드 draft, 두 검증 결과 | `integrated_game` | MainThread | 126.016ms |
| `final_validation` | 최초 기준서, 통합 게임 | `final_validation_result` | MainThread | 74.891ms |

각 Node 실행 전 필수 Input 키 존재 여부와 실행 후 정확한 Output 키 집합을 검사한다. 선언되지 않은 Output이나 누락된 Input이 있으면 즉시 테스트가 실패한다.

## 5. 병렬 처리 결과

### 이미지·게임·사운드 생성

- 개별 시간 합: 738.092ms
- 실제 병렬 구간: 374.103ms
- 병렬 구간 단축률: 약 49.3%
- 사용 스레드: `mock-generation_0`, `_1`, `_2`

2차 실행은 개별 합 646.760ms, 병렬 구간 296.927ms, 3차 실행은 개별 합 648.502ms, 병렬 구간 310.428ms로 동일한 병렬 실행 조건을 충족했다.

세 생성 Node가 서로 다른 스레드에서 겹쳐 실행됐다. 게임 draft가 먼저 끝나는 즉시 `validate_game`과 `create_asset_validation_spec`을 진행했으며 이미지·사운드 생성 전체를 불필요하게 기다리지 않았다.

### 이미지·사운드 검증

- 개별 시간 합: 297.285ms
- 실제 병렬 구간: 177.291ms
- 병렬 구간 단축률: 약 40.4%
- 사용 스레드: `mock-validation_0`, `_1`

2차 실행은 개별 합 299.881ms, 병렬 구간 174.633ms, 3차 실행은 개별 합 317.957ms, 병렬 구간 206.897ms로 동일한 병렬 실행 조건을 충족했다.

두 검증 Node는 에셋 기준서와 각자의 생성물이 준비된 후 동시에 실행됐고, 두 결과가 모두 준비된 다음에만 통합 Node가 실행됐다.

## 6. 검증한 규약

- `YYYYMMDD_NN` 프로젝트 ID와 필수 디렉터리 생성
- State에는 파일 내용 대신 `ArtifactReference` 전달
- 생산 Agent의 실제 파일 저장과 소비 Agent의 참조 기반 읽기
- category별 파일 배치
- manifest 병렬 갱신 시 항목 유실 방지
- 원자적 파일 게시
- SHA-256 및 파일 크기 무결성 검사
- `..` 경로 탈출 차단
- SVG 파싱, WAV 헤더/길이 검사, Python 게임 코드 컴파일·실행
- 검증되지 않은 에셋의 통합 차단
- 최종 기준 4개와 통합 결과 비교

## 7. 현재 판단

현재 구조는 한 컴퓨터 또는 하나의 공유 volume 안에서 Agent가 병렬로 파일을 교환하는 용도로 정상 작동한다. Mock 결과는 단순히 빈 payload를 통과시킨 것이 아니라 실제 SVG, WAV, Python 파일을 생성하고 후속 Agent가 내용을 해석한 결과다.

다만 시간 측정값은 mock 처리 지연과 표준 스레드 실행기를 사용한 값이므로 실제 AI API나 Unity/Godot 빌드 성능을 의미하지 않는다. 실제 LangGraph `StateGraph` 통합 실행은 별도 테스트로 통과했지만, 해당 실행의 내부 scheduler 시간은 이 표에 포함하지 않았다.

## 8. 발견된 병목과 수정 방안

### 1순위: manifest 단일 잠금 최적화

병렬 Node가 파일을 저장할 때 하나의 manifest 잠금을 공유한다. 데이터 유실은 없었지만 생성·검증 구간에서 대기 시간이 발생했다.

- 단기: 한 Node가 여러 파일을 저장할 때 `write_batch()`로 manifest 갱신 횟수 축소
- 중기: append-only JSON Lines 또는 SQLite WAL 기반 manifest 검토
- 측정 추가: lock 대기 시간과 실제 파일 쓰기 시간을 별도 metric으로 기록

### 2순위: 재시도와 파일명 충돌 정책

현재 같은 프로젝트에서 동일 파일명을 다시 저장하면 실패한다. 이는 기존 참조를 보호하지만 Agent 재시도에는 불편하다.

- `attempt_id` 또는 `run_id`를 파일명에 포함
- 같은 내용이면 기존 참조를 돌려주는 idempotent 저장 옵션 추가
- 실패한 attempt의 orphan artifact 정리 정책 정의

### 3순위: 런타임 계약 검증

`TypedDict`는 정적 타입 규약이므로 외부 API가 잘못된 JSON을 반환해도 실행 시 자동 검증되지 않는다.

- JSON Schema 또는 Pydantic 모델 추가
- `ArtifactManager.read_json()` 이후 계약 버전과 필수 필드 검증
- 잘못된 payload용 negative fixture 추가

### 4순위: LangGraph 실패 복구 통합 테스트

- 실제 `StateGraph`에 mock Node를 등록한 정상 흐름은 검증 완료
- Node 실패 재시도, timeout, checkpoint 복구를 추가 검증
- 이번 테스트의 시간 측정 wrapper를 실제 Graph callback 또는 tracing에 연결

### 5순위: 팀원 간 원격 파일 공유

현재 `workspace`는 Git에서 제외된 로컬 저장소다. 서로 다른 컴퓨터의 팀원이 동일 참조를 읽으려면 공유 backend가 필요하다.

- S3, Google Drive, NAS 등의 backend interface 추가
- `ArtifactReference`에 backend와 URI 필드 추가
- 로컬/원격 구현이 같은 checksum 및 manifest 규약을 사용하도록 유지

## 9. 재실행 기준

코드 또는 계약 변경 후 다음 명령을 실행한다.

```powershell
uv run --offline python -m unittest discover -s tests -v
```

성공 기준:

- 모든 테스트 통과
- 최종 상태 `passed`
- artifact 15개 및 category별 개수 일치
- 생성/검증 작업이 각각 둘 이상의 worker에서 실행
- 생성 병렬 구간이 개별 시간 합의 70% 미만
- 검증 병렬 구간이 개별 시간 합의 80% 미만
- 전체 추정 병렬 가속 1.5배 초과

## 10. Docker 재검증 결과

- 재검증 일자: 2026-09-26
- Docker Desktop: 4.92.0
- Docker Engine/CLI: 29.8.0, Linux/amd64 (`desktop-linux`)
- Docker Compose: v5.5.1
- 빌드 명령: `docker compose build --pull`
- 테스트 명령: `docker compose --profile test run --rm test`
- 실행 명령: `docker compose run --rm mainflow`

컨테이너 이미지는 잠금 파일을 사용해 정상 빌드됐고, `langgraph==1.2.12`를 포함한 의존성이 설치됐다. 컨테이너 안에서 unittest 6개가 모두 통과했으며 실제 LangGraph `StateGraph.compile().invoke()` 통합 테스트도 통과했다.

| 측정 항목 | Docker 결과 |
|---|---:|
| 전체 workflow 시간 | 596.715ms |
| Node 시간의 순차 합 | 944.325ms |
| 추정 병렬 가속 | 1.583배 |
| 생성 병렬 구간 | 221.242ms / 개별 합 501.938ms |
| 검증 병렬 구간 | 123.342ms / 개별 합 193.007ms |

프로덕션 서비스도 GUI 없이 끝까지 실행됐고 호스트의 `workspace/20260926_03`에 파일 12개를 생성했다. 이 중 매니페스트에 등록된 artifact는 11개이며 누락된 참조는 0개다. 프로덕션 최종 검증 상태가 `pending`인 것은 Docker 오류가 아니라 실제 Agent Node가 아직 TODO placeholder이기 때문이다. Mock Graph의 최종 검증 상태는 계속 `passed`다.
