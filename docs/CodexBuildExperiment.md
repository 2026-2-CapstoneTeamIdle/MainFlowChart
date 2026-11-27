# Codex 단일 요청 게임 생성 실험

이 실험은 MainFlowChart의 LangGraph, Feature 분석, 설계, 에셋 생성,
검증·수리 파이프라인을 실행하지 않는다. 엑셀의 입력과실험조건 시트에서
P01–P04, T01–T03, S01–S03의 다섯 입력값을 읽고, 각 시행에 대해
새 빈 Unity 프로젝트를 만든 다음 **Codex CLI에 한 번만** 요청한다.

Codex에 전달하는 프롬프트는 다음 형식이다. 다섯 입력값은 엑셀 셀의
앞뒤 공백만 제거한 후 그대로 넣는다.

```text
다음 입력을 바탕으로 이 빈 Unity 프로젝트 안에 플레이 가능한 2D 게임을 만들어줘.
게임을 실행할 수 있는 시작 씬을 만들고 Unity 빌드 씬 목록에 등록해줘.

장르: <엑셀 값>
시점: <엑셀 값>
이미지 스타일: <엑셀 값>
분위기: <엑셀 값>
Condition:
<엑셀 원문>
```

PowerShell에서 저장소 루트로 이동한 다음 실행한다.

```powershell
uv run --locked python -m tools.run_codex_workbook_experiment `
  --workbook "C:\Users\leedo\Documents\카카오톡 받은 파일\Test2_Feature별_동적Validator_비교결과.xlsx" `
  --output-dir "workspace\codex_direct_experiment_20261122" `
  --repeats 1
```

--dry-run은 10개 실험 ID만 출력하고 생성하지 않는다. 중단 후 같은
명령에 --resume을 추가하면 기록된 시행을 건너뛴다. 출력 폴더를 바꾸면
새 실험이다. 기본 모델은 gpt-5.6-luna, 추론 수준은 medium이고 빠른 모드는
꺼져 있다. 필요하면 --fast-mode를 지정한다.

## 측정 정의

- setup_seconds: Codex 이전의 빈 Unity 프로젝트 생성 시간
- generation_seconds: 단일 Codex CLI 호출의 실제 경과 시간
- build_seconds: Codex 호출 이후 별도로 수행한 Windows Player 빌드 시간
- build_success_rate: Codex CLI가 정상 종료했고 Unity Windows 실행 파일이
  실제로 생성된 시행의 비율
- input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens,
  total_tokens: Codex CLI의 turn.completed 사용량. 캐시 입력은 입력 토큰에
  포함되므로 총량에 다시 더하지 않는다. 사용량 기록이 불완전하면
  token_usage_status에 partial 또는 missing을 남긴다.

이 실험은 플레이 품질이나 요구사항 충족률을 판정하지 않는다. 빌드 성공은
실행 파일 생성만 의미한다. 출력에는 시행별 results.csv와 전체·프롬프트별
집계 CSV, summary.json, 실제 전달 프롬프트와 원본 Codex 이벤트,
Unity 프로젝트, Unity 생성·빌드 로그가 포함된다.
