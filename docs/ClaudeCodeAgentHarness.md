# Claude Code Agent Harness

`claude_code` 모드는 프로젝트 API 키 대신 현재 Windows 사용자로 로그인된 Claude Code CLI를
사용한다. Claude Code가 생성된 Unity 프로젝트의 전체 문맥과 `CLAUDE.md`를 읽고 구현한 뒤,
기존과 동일한 Unity Batch Mode·Play Mode 검증 및 제한된 수정 반복을 수행한다.

Codex 하네스와 동일하게 공통 Unity 인프라만 호환성 스캐폴드로 취급한다. 기존 장르 모듈,
Prototype 씬 동작, 배치 좌표, UI와 밸런스는 완성품으로 인정하지 않고 사용자 요청에 맞게
Claude Code가 검토·수정하거나 교체한다.

## 준비

```powershell
npm install -g @anthropic-ai/claude-code
claude --version
claude
```

마지막 `claude` 명령으로 최초 로그인과 프로젝트 신뢰 설정을 마친다. MainFlow는 사용자의
로그인 세션을 사용하며 `ANTHROPIC_API_KEY`를 Claude Code 하위 프로세스에 전달하지 않는다.

## 실행

Web UI의 **게임 구현 방식**에서 **설치된 Claude Code Agent Harness**를 선택하거나 CLI에서
다음처럼 지정한다.

```powershell
uv run --locked python -m mainflow.run_flow `
  --game-builder claude-code `
  --image-style "Pixel Art" `
  --mood-style "Fantasy" `
  --genre "플랫포머" `
  --viewpoint "사이드뷰" `
  --condition "플레이 가능한 플랫포머 게임"
```

기본 모델은 Claude Code의 `sonnet` 별칭이다. 필요하면 `.env`에서 아래 값을 조정한다.

```dotenv
MAINFLOW_CLAUDE_MODEL=sonnet
MAINFLOW_CLAUDE_PERMISSION_MODE=acceptEdits
MAINFLOW_CLAUDE_MAX_TURNS=80
MAINFLOW_CLAUDE_TIMEOUT_SECONDS=1800
MAINFLOW_CLAUDE_TOTAL_TIMEOUT_SECONDS=7200
MAINFLOW_CLAUDE_MAX_REPAIRS=6
MAINFLOW_AGENT_HARD_MAX_REPAIRS=8
MAINFLOW_AGENT_REPAIR_EXTENSION=2
MAINFLOW_AGENT_VALIDATION_BUDGET_SECONDS=1800
MAINFLOW_AGENT_FINAL_VALIDATION_BUDGET_SECONDS=1500
MAINFLOW_FEATURE_EVIDENCE_AUDIT_BUDGET_SECONDS=600
MAINFLOW_FEATURE_EVIDENCE_AUDIT_BATCH_TIMEOUT_SECONDS=180
MAINFLOW_AGENT_POST_VALIDATION_REPAIRS=3
MAINFLOW_FEATURE_CHECKLIST_AGENT_REPAIRS=1
```

최초 구현 이후 `validate_game`과 에셋 적용 후 최종 Unity 검증에서 실패해도 Claude Code에
실패 로그가 다시 전달된다. 단계별 후속 수정은 기본 3회이며, 적용된 이미지·사운드와 바인딩
계약을 보존하고 더 심한 회귀가 발생하면 해당 수정을 롤백한다.
완료 보고에는 호스트 Unity 검증 대기 여부와 실제 구현 장애를 별도 필드로 기록하며,
호스트 검증만 남았다면 Unity 검증 단계로 진행한다.
Feature 체크리스트 실패도 동일하게 Claude Code에 다시 전달하고 수정 후 체크리스트를
재실행한다. 기본 재시도는 1회이며 `MAINFLOW_FEATURE_CHECKLIST_AGENT_REPAIRS`로 0~3회까지
조정할 수 있다.
최초 구현, `validate_game`, 최종 Unity 검증 중 복구 가능한 오류가 순차적으로 나타나면
새로운 근본 오류가 나타날 때만 2회씩 자동 연장해 안전 상한 8회까지 계속한다. 실제 C#
소스가 바뀌어도 같은 근본 오류가 세 번 확인되면 중단한다. 일반 검증은 기본 30분,
최종 검증은 기본 25분의 시간 예산이 Unity와 Claude Code 프로세스에 적용된다. Unity 실행
전 설정·모듈·시작 씬 사전 검사를 거치고, 최종 기능 증거 감사는 묶음별 저장·재시도를 사용한다.
모듈 선택 목록은 초기화 의존 순서로 정렬하며, CLI가 이 순서를 바꾸면 Unity 실행 전
사전 검사에서 요구 서비스와 소비 모듈 ID를 표시해 수정 루프로 전달한다.

회전 검처럼 공격 전달 방식을 명시한 요청에서는 일반 투사체 모듈과 정적 투사체
체크리스트를 적용하지 않는다. 요청된 검의 회전·피격 규칙은 에셋 적용 전에 소스
증거로 확인하며, 누락 시 CLI에 수정 요청을 보낸다. 필수 사운드의 파형·길이·피크
검증이 실패하면 해당 사운드만 기본 2회 재생성한다
(`MAINFLOW_SOUND_VALIDATION_REGENERATIONS=0~3`). 역상 스테레오 효과음은 에너지가
큰 채널로 모노 보정 후 재검증한다. 최종 Feature 증거 감사에서 실제 동작 누락이
확인되면 CLI 수정과 Unity 재검증을 기본 2회 시도한다
(`MAINFLOW_FINAL_FEATURE_AUDIT_REPAIRS=0~3`). 확인 불가능한 근거는 동작 누락과
구분해 기록한다.

실행 증거는 각 프로젝트의 `validation/claude_code/`에 저장된다. CLI 경로 자동 탐색이
실패하면 `MAINFLOW_CLAUDE_CLI_PATH`에 `claude.cmd`의 절대 경로를 지정한다.

## UI 생성 기준

Claude Code도 `presentation_plan.json`의 팔레트, HUD 영역, 상태 화면과 필수 요소를 실제 Unity
uGUI로 구현해야 한다. 체력·목표·진행도와 버튼은 런타임 시스템에 연결하고, 이미지 생성 API가
없을 때도 기본 폰트와 uGUI 도형으로 읽을 수 있는 화면을 만든다. 기존 IMGUI 디버그 패널은
완성 UI로 인정되지 않으며 Play Mode의 `runtime.ui_quality` 검사를 통과해야 한다.
패널은 실제 화면 안에 있어야 하고 글자·게이지는 프레임의 안전 영역에 배치해야 한다.
안전 영역 침범이 개선되는 동안에는 반복 오류로 조기 중단하지 않되 총 수리 상한은 유지한다.
