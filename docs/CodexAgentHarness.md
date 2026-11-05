# Codex CLI Agent Harness

`codex_cli` 게임 구현 모드는 LocalAI 또는 프로젝트의 API 키로 기능별 C# 응답을 받는 대신,
현재 Windows 사용자로 로그인된 Codex CLI가 생성된 Unity 프로젝트 전체를 읽고 수정하게 한다.

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
```

## 실행 경계

- Codex의 쓰기 루트는 `workspace/{project_id}/game/unity_project`로 제한된다.
- 자식 Codex 프로세스에는 프로젝트의 OpenAI, Gemini, Vast.ai, ElevenLabs 키를 전달하지 않는다.
- 구현 단계는 `workspace-write`, 최종 독립 품질 검수는 `read-only` 샌드박스를 사용한다.
- 설계 JSON과 manifest는 호스트 계약이므로 Codex가 수정하지 않도록 프로젝트 `AGENTS.md`에 명시한다.
- Codex의 완료 보고만으로 통과시키지 않고 Unity 컴파일·Play Mode 검증 결과를 기준으로 수정한다.
- 동일 오류가 세 번 반복되거나 시간·재시도 예산을 소진하면 실패한다.

## 감사 기록

각 실행의 프롬프트, JSON Schema, JSONL 이벤트, stderr, 최종 보고서는 다음 경로에 저장된다.

```text
workspace/{project_id}/validation/codex/
```

`events.jsonl`에는 Codex가 실행한 도구와 명령 이벤트가 기록되므로 실패 원인과 사용량을 추적할 수
있다.
