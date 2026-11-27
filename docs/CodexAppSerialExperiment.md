# Codex App Server 직렬 게임 생성 실험

이 실험은 기존 MainFlow 파이프라인과 `codex exec` 일회성 실행을 사용하지 않습니다. Codex의 공식 `app-server` 프로토콜로 각 요청마다 새 대화를 만들고, 한 요청의 Unity 빌드 검증이 끝난 후 다음 요청을 시작합니다. **데스크톱 앱의 GUI를 클릭하는 실험은 아니므로** 앱 화면에서 직접 요청하는 경험과 완전히 동일하다고 주장하지 않습니다. 비교 보고서에는 실행 표면을 `codex-app-server`로 표기합니다.

## 실행

PowerShell에서 저장소 루트로 이동한 뒤 실행합니다.

```powershell
cd C:\Users\leedo\Documents\CapstonDesignII\feat-agent-harness

$workbook = 'C:\Users\leedo\Documents\카카오톡 받은 파일\Test2_Feature별_동적Validator_비교결과.xlsx'
$output = 'workspace\codex_app_serial_20261123_prompt_v2'
$editor = 'C:\Program Files\Unity\Hub\Editor\6000.2.8f1\Editor\Unity.exe'

node tools\run_codex_app_serial_experiment.mjs --workbook $workbook --output-dir $output --dry-run
node tools\run_codex_app_serial_experiment.mjs --workbook $workbook --output-dir $output --preview-prompt P01
node tools\run_codex_app_serial_experiment.mjs --workbook $workbook --output-dir $output --unity-editor $editor --probe
node tools\run_codex_app_serial_experiment.mjs --workbook $workbook --output-dir $output --unity-editor $editor --model gpt-5.6-luna --effort medium --max-repairs 2
```

엑셀의 마지막 시나리오부터 역순으로 실행하려면 본 실험 명령에 `--reverse`를 추가합니다. 현재 10개 입력에서는 `S03, S02, S01, T03, T02, T01, P04, P03, P02, P01` 순서입니다. 재개할 때도 같은 `--reverse` 옵션을 유지해야 합니다.

`--dry-run`은 10개 ID만 보여주고 `--preview-prompt P01`은 엑셀 P01 입력으로 만들어진 실제 최초 요청을 보여줍니다. `--probe`는 모델 호출로 명령 실행과 임시 파일 쓰기를 확인하며 소량의 모델 사용량이 발생합니다. `passed`가 `true`일 때만 본 실험을 진행하세요. 본 실험 명령도 첫 시도 전에 같은 도구 점검을 자동 실행하며, 실패하면 10개 게임 생성으로 넘어가지 않습니다. 마지막 명령이 실제 생성과 Unity 빌드를 시작합니다. 중단 뒤에는 동일한 명령에 `--resume`을 덧붙입니다. 이미 `result.json`이 있는 실행은 건너뛰고, 중간에 끊긴 실행은 새 `-attemptNN` 폴더에서 시작합니다.

기존 출력 폴더를 재개할 때 설정이 같은지 먼저 확인하려면 실행 명령 끝에 `--resume --check-resume`을 붙입니다. 이 검사는 게임을 시작하지 않습니다. 확인 후 `--check-resume`만 빼고 다시 실행합니다.

## 수행·측정 방식

1. 엑셀 `입력과실험조건` 시트의 장르·시점·Condition만 사용해 `Unity에서 실행할 수 있는 게임을 만들어줘. {장르} 장르의 {시점} 시점으로 {Condition} 하는 게임을 만들어줘.` 형식의 최초 요청을 만듭니다. 이미지 스타일과 분위기 열은 이 실험의 요청에 넣지 않습니다.
2. 요청별로 독립적인 빈 Unity 프로젝트를 생성하고 새 App Server 대화를 시작합니다. 모델 기본값은 GPT-5.6 Luna, 추론 수준은 medium입니다.
3. Codex 작업이 끝나면 별도 Windows Player 빌드를 수행합니다. 실패하면 Unity 오류를 같은 대화에 보내 최대 2회 수정합니다. 빌드가 통과하거나 수정 한도에 도달하면 다음 요청으로 넘어갑니다.
4. 대화와 같은 세션의 하위 에이전트 기록에서 마지막 누적 `token_usage_record.thread_token_usage`를 각각 읽습니다. `token_threads`에 기록을 찾은 대화 수를 남깁니다. 누락된 기록이 있으면 `token_status=partial`로 표시합니다. 캐시 입력은 입력 토큰에 포함되고, 추론 출력은 출력 토큰에 포함되므로 각각 다시 더하지 않습니다.
5. Unity 프로젝트 생성, Codex 처리, 빌드 검증, 전체 시간을 별도 기록합니다.

각 실행의 원본 프로젝트·프롬프트·로그·결과는 `trials/<ID>/`에 남습니다. 집계는 `results.csv`, `summary.json`, `summary.md`에 갱신됩니다. `build_status=passed`는 **Windows 실행 파일이 생성됐다는 뜻**이며, 실제 플레이 흐름은 이 실험에서 검증하지 않습니다. `runtime_status=not_tested`를 별도로 기록합니다. 토큰 수는 로컬 세션 기록을 바탕으로 한 최선의 집계이며 결제액이나 주간 사용 한도 퍼센트와 동일하지 않습니다.

스크립트는 전체 10개 생성 실험을 자동으로 실행하므로, 먼저 `--dry-run`과 `--probe`로 설정을 확인하세요. 서로 다른 출력 폴더를 사용하면 기존 결과를 보존할 수 있습니다.
