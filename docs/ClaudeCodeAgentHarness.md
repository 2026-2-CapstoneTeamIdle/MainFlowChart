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
MAINFLOW_AGENT_POST_VALIDATION_REPAIRS=3
```

최초 구현 이후 `validate_game`과 에셋 적용 후 최종 Unity 검증에서 실패해도 Claude Code에
실패 로그가 다시 전달된다. 단계별 후속 수정은 기본 3회이며, 적용된 이미지·사운드와 바인딩
계약을 보존하고 더 심한 회귀가 발생하면 해당 수정을 롤백한다.

실행 증거는 각 프로젝트의 `validation/claude_code/`에 저장된다. CLI 경로 자동 탐색이
실패하면 `MAINFLOW_CLAUDE_CLI_PATH`에 `claude.cmd`의 절대 경로를 지정한다.

## UI 생성 기준

Claude Code도 `presentation_plan.json`의 팔레트, HUD 영역, 상태 화면과 필수 요소를 실제 Unity
uGUI로 구현해야 한다. 체력·목표·진행도와 버튼은 런타임 시스템에 연결하고, 이미지 생성 API가
없을 때도 기본 폰트와 uGUI 도형으로 읽을 수 있는 화면을 만든다. 기존 IMGUI 디버그 패널은
완성 UI로 인정되지 않으며 Play Mode의 `runtime.ui_quality` 검사를 통과해야 한다.
