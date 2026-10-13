# MainFlow 테스트 결과

## 최신 검증

- 실행일: 2026-10-12
- 계약 버전: 3.0.0
- 명령: `.venv\Scripts\python.exe -m unittest discover -s tests -v`
- 결과: 로컬 및 Docker에서 **8개 테스트 전체 통과**
- 실제 LangGraph mock 실행: 통과
- 파일 교환·checksum·경로 이탈 방지·병렬 manifest 갱신: 통과

## Workflow mock 결과

입력은 `Pixel Art`, `Fantasy`, `플랫포머`, `공격과 8방향 이동이 가능한 게임`을 사용했다.
`parse_input → analysis → logic_analysis → design_game_logic`에서 Unity 설계와 이미지·사운드
요청 JSON을 만든 뒤 이미지 생성·게임 검증·사운드 생성이 병렬로 실행됐다.

| 측정 항목 | 결과 |
|---|---:|
| 전체 wall time | 633.751ms |
| Node 순차 시간 합 | 1003.525ms |
| 추정 병렬 가속 | 1.583x |
| 생성 3개 Node 병렬 구간 | 206.184ms |
| 생성 3개 Node 순차 합 | 502.210ms |
| 이미지·사운드 검증 병렬 구간 | 131.460ms |
| 이미지·사운드 검증 순차 합 | 208.254ms |

생성 Node는 서로 다른 3개 worker thread에서 실행됐고, 이미지·사운드 검증도 서로 다른 2개
worker thread에서 실행됐다.

## 파일 결과

Mock 실행 한 건에서 총 16개 artifact를 생성하고 모두 checksum 검증 후 읽었다.

| Category | 개수 |
|---|---:|
| `data` | 3 |
| `image` | 2 |
| `sound` | 2 |
| `game` | 4 |
| `validation` | 5 |

`data`의 3개 파일은 `parsed_request.json`, `analysis.json`, `logic_analysis.json`이다. 이전
`initial_final_validation_spec.json`은 제거됐고 최종 기준은 `logic_analysis.json`에 포함된다.

Custom PNG/JPG 가져오기와 `ArtifactReference` 재읽기, 조건의 기능 추출도 별도 테스트로 검증했다.
Local Web Docker 컨테이너는 `/`에서 HTTP 200을 반환했고 `/api/health`에서
`contract_version=3.0.0`, `status=ok`를 반환했다.

## 현재 한계와 다음 수정 방향

- Analysis는 현재 규칙 기반 기능 추출기다. 향후 LLM을 연결하되 `AnalysisResult` 계약은 유지한다.
- 이미지·게임·사운드 production Node는 placeholder이므로 실제 생성기와 Unity 연동이 필요하다.
- Local Web은 계약 3.0.0 입력 UI와 health API까지만 제공하며 Workflow 실행·업로드 API는 아직 없다.
- 성능 수치는 mock delay와 로컬 파일 I/O를 측정한 값이므로 실제 외부 AI API 성능과 다르다.
