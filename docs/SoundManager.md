# Sound Generation Manager

`generate_sound` Node는 사용자 입력에서 만들어진 사운드 요청서(`game/asset_requests/sound_asset_request.json`)를 읽어, 요청된 에셋마다 WAV 파일을 하나씩 생성한다. 구현은 `sound_pipeline/` 패키지에 있다.

## 1. 입력이 사운드로 바뀌는 과정

```text
웹/CLI 입력 (이미지 스타일 · 분위기 · 장르 · 시점 · 조건)
  → parse_input / analysis / design_game_logic
  → sound_asset_request.json  (asset_id, purpose, description, suggested_filename …)
  → sound_pipeline.plan_sound_assets   : 에셋별 종류·길이·루프·프롬프트 결정
  → provider.generate                  : ElevenLabs 또는 절차적 합성
  → generated/sounds/<asset>.wav + sound_draft.json (ArtifactManager로 등록)
```

| 입력 | 반영 위치 |
|---|---|
| 분위기 스타일 (`mood_style`) | 프롬프트의 음색 설명. 절차적 합성에서는 음계·템포·파형 |
| 장르 | 프롬프트의 게임 종류·에너지. 절차적 합성에서는 드럼 강도 |
| 이미지 스타일 | 프롬프트 힌트 (예: Pixel Art → "retro 8-bit chiptune flavor") |
| 시점 | 효과음 프롬프트의 시점 정보 |
| 조건 (한 문장) | BGM 프롬프트의 Gameplay 설명 |
| 요청서의 `purpose`/`description` | BGM/효과음 구분, 효과음 종류(UI·타격·폭발·환경음·일반 동작), 루프 여부 |

`asset_id` 문자열로는 종류를 추론하지 않는다(ContractRule). 엔딩·승리·패배 음악은 루프하지 않고, 환경음과 일반 BGM은 루프 가능하게 만든다.

## 2. 생성 Provider

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `SOUND_PROVIDER` | `auto` | `auto`: `ELEVENLABS_API_KEY`가 있으면 ElevenLabs, 없으면 절차적 합성 / `elevenlabs` / `procedural` |
| `ELEVENLABS_API_KEY` | (없음) | ElevenLabs API 키. 이미지·workspace·manifest에 저장하지 않는다 |
| `SOUND_FALLBACK` | `procedural` | ElevenLabs 실패 시 절차적 합성으로 대체. `none`이면 대체하지 않고 실패 기록 |
| `SOUND_BGM_SECONDS` | `30` | BGM 길이(초). Music API 범위인 3–600초로 맞춘다 |
| `ELEVENLABS_OUTPUT_FORMAT` | `pcm_44100` | 무손실 PCM을 받아 WAV로 감싸 저장한다. `pcm_44100`은 ElevenLabs **Pro 요금제 이상**이 필요하다. 요금제가 이를 거절하면(401/403, 오류 메시지에 output format 포함) 그 실행은 무료 요금제 최고 PCM인 `pcm_24000`으로 바꿔 다시 요청한다(무압축, 단 12 kHz 이상 고음은 없음). PCM 채널 수는 문서에 없어 받은 크기로 mono/stereo를 판단한다(실측: Sound Effects는 stereo). 형식은 크레딧에 영향이 없다. `mp3_*`를 지정하면 MP3를 그대로 저장하며 검증에 ffmpeg가 필요하다 |
| `ELEVENLABS_SFX_MODEL` | (비움) | 비우면 `model_id`를 보내지 않아 Sound Effects 엔드포인트의 기본 모델을 쓴다. 특정 모델을 고정할 때만 ID를 넣는다 |
| `ELEVENLABS_MUSIC_MODEL` | (비움) | 비우면 Music API의 기본 모델을 쓴다 |
| `SOUND_TIMEOUT_SECONDS` | `90` | API 요청 제한 시간. 긴 BGM을 Music API로 만들 때 시간이 모자라면 늘린다 |

- **ElevenLabs**: 효과음은 `POST /v1/sound-generation`(Sound Effects), BGM은 `POST /v1/music`(`music_length_ms`)을 호출한다. 기본은 무손실 PCM(`pcm_44100`)으로 받아 WAV로 저장한다. 무료 요금제는 Music API를 쓸 수 없으므로(HTTP 402 `paid_plan_required`) BGM은 절차적 합성으로 대체된다.
- **실패 처리**: 연결 실패(DNS·연결 거부), HTTP 401/403(키·권한), 할당량 초과(`detail.status` = `quota_exceeded`), 효과음 엔드포인트의 응답 타임아웃·연결 끊김이 한 번 나면 그 실행의 남은 에셋은 ElevenLabs를 다시 호출하지 않고 바로 대체(fallback)한다.
  - Music API(`/v1/music`)의 타임아웃·오류(402 포함)는 그 에셋만 실패로 보고, BGM은 절차적 합성으로 대체한다. BGM을 Sound Effects 엔드포인트(최대 30초)로 만들지 않는다.
  - 할당량 초과가 아닌 429(동시 요청·속도 제한)는 `Retry-After`(최대 30초)만큼 기다렸다가 한 번 재시도한다.
- **절차적 합성(procedural)**: 외부 의존성 없이 표준 라이브러리로 합성하는 오프라인 대체 음원이다. API 키가 없어도 Workflow와 Unity 연결을 끝까지 테스트할 수 있지만 품질은 임시용이다.

## 3. 결과물

```text
workspace/{project_id}/generated/sounds/
├─ <asset>.wav                  # 기본 WAV. ELEVENLABS_OUTPUT_FORMAT=mp3_*이면 <asset>.mp3
└─ sound_draft.json             # SoundDraft
```

`SoundDraft`:
- `status`: 필수 에셋이 모두 생성되면 `generated`, 하나라도 실패하면 `failed`
- `assets[]`: `asset_id`, `artifact`(ArtifactReference, `audio/mpeg` 또는 `audio/wav`), `file_format`, `duration_seconds`(파일에서 실측), `prompt`, `provider`
- 파일 확장자는 `artifact`가 기준이다. 요청서의 `suggested_filename`은 `.wav`로 고정이라 `mp3_*` 형식을 쓰면 실제 파일(`.mp3`)과 다르다
- `notes`: provider, 엔드포인트, 모델, 형식, 요청 길이와 실제 길이, 요청 ID, 종류·루프 여부, 대체(fallback) 사유

## 4. 실행

```powershell
# 로컬 웹 (생성된 사운드는 파일 목록에서 바로 재생 가능)
$env:ELEVENLABS_API_KEY = "sk_..."      # 없으면 절차적 합성
docker compose -f "CI/CD/LocalWeb/compose.yaml" up --build

# CLI
uv run --locked python -m mainflow.run_flow --image-style "Pixel Art" --mood-style Horror `
  --genre "비주얼 노벨" --viewpoint "고정 화면" --condition "선택지에 따라 엔딩이 달라지는 게임"

# 테스트 (API 호출은 mock)
uv run --locked python -m unittest tests.test_sound_generation tests.test_sound_validation -v
```

## 5. 현재 한계

- `validate_sound`는 `sound_pipeline/SoundValidationPlan.md`의 G1(기술 QC)·G2(DSP 보정)·중복 검사·판정까지 구현돼 있다 (`sound_pipeline/validation.py`). 결과는 `validation/sound_validation_result.json`·`validation/sound_profile.json`, 보정본은 `generated/sounds/processed/<asset>.wav`에 저장한다. `mp3_*` 형식을 쓸 때만 MP3 디코딩에 ffmpeg가 필요하다(기본 PCM/WAV는 필요 없음). Docker 이미지에는 포함돼 있지만 Windows에서 `uv run`으로 실행하면 직접 설치해 PATH에 넣어야 한다 (예: `winget install Gyan.FFmpeg`). ffmpeg가 없으면 MP3 에셋은 결함으로 보지 않고 `sound-validator-unavailable` issue와 함께 REVIEW로 둔다.
- G3(내용 적합성 모델)·후보 선택·G5 믹스 테스트·라우드니스 위계는 아직 없다. `apply_assets_to_game`도 아직 검증 결과와 보정본을 반영하지 않는다.
- 프롬프트에는 요청서의 한국어 설명과 조건이 그대로 들어간다. 영어 번역 단계를 추가하면 ElevenLabs 결과가 더 안정적일 수 있다.
- 비용 기록과 재생성 루프는 없다. 평가 가이드라인(PASS / REGENERATE / REVIEW)을 연결할 때 함께 추가한다.
- ElevenLabs 음악 API의 `model_id`와 `output_format` 세부 값은 최신 API 문서로 확인한 뒤 환경변수로 지정한다.
