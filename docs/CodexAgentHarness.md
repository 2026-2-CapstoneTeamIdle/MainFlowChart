# Codex CLI Agent Harness

`codex_cli` 게임 구현 모드는 LocalAI 또는 프로젝트의 API 키로 기능별 C# 응답을 받는 대신,
현재 Windows 사용자로 로그인된 Codex CLI가 생성된 Unity 프로젝트 전체를 읽고 수정하게 한다.

하네스 모드에서는 미리 존재하는 장르별 기능 모듈도 완성된 기능으로 간주하지 않는다. 공통
부트스트랩·검증·에셋 바인딩은 호환성 스캐폴드로 재사용하지만, 장르 모듈과 Prototype 코드는
사용자 요구사항별 검토·수정 대상으로 Codex에 전달한다. 따라서 기존 모듈이 있는 기능도 실제
요청, 씬 진행, UI, 카메라, 밸런스와 연결되지 않으면 구현 완료로 처리하지 않는다.

## 사전 조건

```powershell
codex --version
codex login status
```

두 명령이 모두 성공해야 한다. Local Web과 CLI 파이프라인은 Codex에 로그인한 동일한 OS 사용자로
실행해야 한다. 이 모드는 API 키를 요구하지 않지만 사용자의 Codex 계정 사용량을 소비한다.

## 실행

```powershell
uv run --locked python -m mainflow.run_flow `
  --game-builder codex-cli `
  --game-test `
  --image-style "Pixel Art" `
  --mood-style "Fantasy" `
  --genre "플랫포머" `
  --viewpoint "사이드뷰" `
  --condition "플레이어가 이동하고 점프하며 보석을 모은 뒤 목적지에 도달한다."
```

기본값은 `gpt-5.6-luna`, 추론 강도 `medium`이다. 환경변수로 다른 모델을 명시할 수 있다.

```powershell
$env:MAINFLOW_CODEX_MODEL="gpt-5.6-luna"
$env:MAINFLOW_CODEX_REASONING_EFFORT="medium"
$env:MAINFLOW_CODEX_TIMEOUT_SECONDS="1800"
$env:MAINFLOW_CODEX_TOTAL_TIMEOUT_SECONDS="7200"
$env:MAINFLOW_CODEX_MAX_REPAIRS="6"
$env:MAINFLOW_AGENT_HARD_MAX_REPAIRS="8"
$env:MAINFLOW_AGENT_REPAIR_EXTENSION="2"
$env:MAINFLOW_AGENT_VALIDATION_BUDGET_SECONDS="1800"
$env:MAINFLOW_AGENT_FINAL_VALIDATION_BUDGET_SECONDS="1500"
$env:MAINFLOW_FEATURE_EVIDENCE_AUDIT_BUDGET_SECONDS="600"
$env:MAINFLOW_FEATURE_EVIDENCE_AUDIT_BATCH_TIMEOUT_SECONDS="180"
$env:MAINFLOW_AGENT_POST_VALIDATION_REPAIRS="3"
$env:MAINFLOW_GAME_QUALITY_REPAIRS="8"
$env:MAINFLOW_GAME_QUALITY_TIME_BUDGET_SECONDS="2400"
$env:MAINFLOW_GAME_QUALITY_UNITY_REPAIRS="2"
$env:MAINFLOW_FEATURE_CHECKLIST_AGENT_REPAIRS="1"
```

## 실행 경계

- Codex의 쓰기 루트는 `workspace/{project_id}/game/unity_project`로 제한된다.
- 자식 Codex 프로세스에는 프로젝트의 OpenAI, Gemini, Vast.ai, ElevenLabs 키를 전달하지 않는다.
- 구현 단계는 `workspace-write`, 최종 독립 품질 검수는 `read-only` 샌드박스를 사용한다.
- 설계 JSON과 manifest는 호스트 계약이므로 Codex가 수정하지 않도록 프로젝트 `AGENTS.md`에 명시한다.
- 복사된 장르 코드·고정 좌표·샘플 콘텐츠는 참고 구현일 뿐이며 요청별로 수정하거나 교체한다.
- 기존 모듈 선택·바인딩 작업을 Codex 실행 전에 성공 처리하지 않는다.
- Codex의 완료 보고만으로 통과시키지 않고 Unity 컴파일·Play Mode 검증 결과를 기준으로 수정한다.
- 완료 보고에는 호스트 Unity 검증 대기 여부와 실제 구현 장애를 별도 필드로 기록한다.
  소스 수정이 끝나고 호스트 검증만 남았다면 Unity 검증 단계로 진행한다.
- 동일 오류가 세 번 반복되거나 시간·재시도 예산을 소진하면 실패한다.
- 최초 구현 검증을 통과한 뒤에도 `validate_game` 또는 에셋 적용 후 최종 Unity 검증이
  실패하면 해당 로그를 Codex에 다시 전달한다. 기본 후속 수정 횟수는 단계별 3회이며
  `MAINFLOW_AGENT_POST_VALIDATION_REPAIRS`로 1~6회 사이에서 조정한다.
- Feature 체크리스트가 마지막에 실패하면 실패한 Feature, assertion과 Unity 로그를 Codex에
  다시 전달하고, 수정 후 컴파일 및 체크리스트를 다시 실행한다. 기본 1회이며
  `MAINFLOW_FEATURE_CHECKLIST_AGENT_REPAIRS`로 0~3회까지 조정한다.
- Unity 실행 전에 직렬화된 설정, 모듈 ID, 시작 씬을 사전 검사한다. Unity는 컴파일·씬 조립을
  통과한 경우에만 별도 Play Mode 프로세스를 실행한다.
- 모듈 생성 시 `OnInitialize`에서 요구하는 서비스가 먼저 초기화되도록 선택 목록을
  정렬한다. Codex가 목록을 바꿔 의존 순서가 어긋나면 Unity 실행 전에 구체적인 모듈 ID로
  실패시키고 수정 루프에 전달한다.
- 최초 구현, `validate_game`, 최종 Unity 검증의 수리 한도는 새로운 근본 오류가 나타나거나
  동일 HUD 안전 영역 침범이 실제로 줄어들 때 2회씩 연장하며 기본 안전 상한은 8회다.
  동일 근본 오류가 개선 없이 세 번 확인되면 중단한다. 단계별 기본 시간 예산은 일반 검증 30분, 최종 검증 25분이며
  Unity와 Codex 프로세스에도 남은 시간을 적용한다. 환경변수로 상한을 조정할 수 있다.
- 최종 기능 증거 감사는 8개 항목씩 저장한다. 잘못된 ID가 반환되면 해당 묶음만 한 번
  재요청하고, 이미 확인한 묶음은 동일 소스에 한해 재사용한다. 재시도에도 실패한 항목은
  증거 부족으로 남겨 두며 다른 묶음의 결과는 보존한다. 기본 전체 예산은 10분,
  묶음별 제한은 3분이다.
- 후속 수정은 적용된 이미지·사운드 파일과 바인딩 ID를 보존하며, 더 심각한 컴파일·바인딩
  오류를 만들면 변경을 롤백한다.
- 회전 검처럼 공격 전달 방식을 명시한 요청에서는 일반 투사체 모듈과 정적 투사체
  체크리스트를 적용하지 않는다. 요청된 검의 회전·피격 규칙은 에셋 적용 전에 소스
  증거로 확인하고, 누락 시 CLI에 수정 요청을 보낸다.
- 필수 사운드의 파형·길이·피크 검증이 실패하면 해당 사운드만 기본 2회 재생성한다.
  `MAINFLOW_SOUND_VALIDATION_REGENERATIONS`로 0~3회까지 조정한다.
- 역상 스테레오 효과음은 평균 시 상쇄되지 않도록 에너지가 큰 채널로 모노 보정하고
  재검증한다. 보정 후에도 채널 검증이 실패한 필수 사운드만 재생성한다.
- 최종 Feature 증거 감사에서 실제 동작 누락이 확인되면 CLI 수정과 Unity 재검증을
  기본 2회 시도한다. `MAINFLOW_FINAL_FEATURE_AUDIT_REPAIRS`로 0~3회까지 조정한다.
  근거 파일을 확인할 수 없는 감사 응답은 동작 누락과 구분해 기록한다.
- 독립 품질 검수가 실제 기능 누락을 찾으면 근거 파일과 권고를 Codex에 전달한다. 수정 후
  Unity 컴파일·Play Mode를 다시 통과해야 다음 품질 검수를 진행하며, 실패한 변경은 복원한다.
  품질 수정은 기본 8회, `MAINFLOW_GAME_QUALITY_REPAIRS`로 0~10회까지 조정할 수 있다.
  품질 수정 단계의 총 시간 예산은 기본 40분이며
  `MAINFLOW_GAME_QUALITY_TIME_BUDGET_SECONDS`로 60~7200초 사이에서 조정한다.
  검수가 통과하거나 동일 지적에 대해 소스 변경이 반복해서 없으면 일찍 종료한다.
  품질 수정에서 컴파일·런타임 오류가 생기면 변경 전체를 바로 폐기하지 않고 오류 로그를
  같은 Agent에 다시 전달한다. 이 내부 수정 횟수는
  `MAINFLOW_GAME_QUALITY_UNITY_REPAIRS`로 0~3회까지 조정한다. 내부 수정까지 실패하면
  원본으로 복원한 뒤 다음 품질 수정 시도에 실패 원인을 함께 전달한다.
  placeholder 이미지 때문에 생략한 시각 검증은 별도 한계로 기록한다.

## UI 생성 기준

`presentation_plan.json`에는 요청별 팔레트·타이포그래피·HUD 영역·상태 화면별 필수 요소가
포함된다. Codex는 이를 Unity uGUI로 구현하고 실제 체력, 목표, 진행도, 점수·재화·시간과
연결해야 한다. 이미지 API가 없어도 불투명 패널, 색상 계층, 기본 폰트와 진행 바로 읽을 수
있는 UI를 구성해야 하며, 기존 `PrototypeSceneController`의 IMGUI 디버그 패널은 비활성화하거나
교체한다.

Play Mode 검증은 하네스 프로젝트에 대해 반응형 `CanvasScaler`, 최소 UI 그래픽·텍스트·버튼,
14px 이상의 글자와 레거시 디버그 UI 제거를 확인한다. 기준을 만족하지 못하면
`runtime.ui_quality` 증거가 Codex 수정 루프로 전달된다. 화면 밖 HUD 패널은 텍스트 안전 영역보다
먼저 판정하며, `RectTransform.sizeDelta`를 끝 좌표로 오인한 경우 패널 크기부터 수정해야 한다.

## 감사 기록

각 실행의 프롬프트, JSON Schema, JSONL 이벤트, stderr, 최종 보고서는 다음 경로에 저장된다.

```text
workspace/{project_id}/validation/codex/
```

`events.jsonl`에는 Codex가 실행한 도구와 명령 이벤트가 기록되므로 실패 원인과 사용량을 추적할 수
있다.
