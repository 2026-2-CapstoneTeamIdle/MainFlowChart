# Sound Generation Manager

`generate_sound` Node는 사용자 입력에서 만들어진 사운드 요청서(`game/asset_requests/sound_asset_request.json`)를 읽어, 요청된 에셋마다 WAV 파일을 하나씩 생성한다. 구현은 `sound_pipeline/` 패키지에 있다.

## 1. 입력이 사운드로 바뀌는 과정

```text
웹/CLI 입력 (이미지 스타일 · 분위기 · 장르 · 시점 · 조건)
  → parse_input / analysis / design_game_logic
  → sound_asset_request.json  (asset_id, purpose, description, suggested_filename, unity_binding_key, generation_spec …)
  → sound_pipeline.plan_sound_assets   : 에셋별 종류·길이·루프·프롬프트 결정
  → provider.generate                  : ElevenLabs 또는 절차적 합성
  → generated/sounds/<stem>.wav + sound_draft.json (ArtifactManager로 등록, stem = suggested_filename)
  → validate_sound → apply_assets_to_game → Unity GeneratedAssetBinder
```

요청서 항목은 세 곳에서 온다.
- GameSpec의 사운드 에셋 요구사항
- 연출 계획의 `feedback_cues`마다 하나씩 추가되는 `<cue>_sfx` (`game_pipeline/presentation_sound_assets.py`, required)
- 구현 에이전트가 보고한 `sound_events` (`game_pipeline/agent_sound_assets.py`, 선택 에셋, 최대 64개, 에이전트가 정한 `cue_id`를 `audio_cue`로 사용)

모든 항목에는 `generation_spec`(`game_pipeline/asset_specs.py::build_sound_generation_spec`)이 붙고, 생성 단계는 이것을 **기준**으로 kind·길이·루프·mixer를 정한다. `purpose`/`description` 키워드 분류는 `generation_spec`이 없을 때의 대체 경로다.

| kind | 길이 | loop | mixer |
|---|---|---|---|
| bgm | 90 s | ✓ | Music |
| ambience | 60 s → 생성은 30 s (효과음 엔드포인트 상한) | ✓ | Ambience |
| voice | 5 s | ✗ | Voice |
| ui | 0.5 s | ✗ | UI |
| sfx | 1.0 s | ✗ | SFX |

| 입력 | 반영 위치 |
|---|---|
| 분위기 스타일 (`mood_style`) | 프롬프트의 음색 설명. 절차적 합성에서는 음계·템포·파형 |
| 장르 | 프롬프트의 게임 종류·에너지. 절차적 합성에서는 드럼 강도 |
| 이미지 스타일 | 프롬프트 힌트 (예: Pixel Art → "retro 8-bit chiptune flavor") |
| 시점 | 효과음 프롬프트의 시점 정보 |
| 조건 (한 문장) | BGM 프롬프트의 Gameplay 설명 |
| 요청서의 `purpose`/`description` | 프롬프트의 Event/Scene 설명, 효과음 세부 종류(타격·폭발·일반 동작 → onset 기준). `generation_spec`이 없을 때만 BGM/효과음 구분과 루프 여부도 결정 |

`asset_id` 문자열로는 종류를 추론하지 않는다(ContractRule). 키워드 대체 경로에서는 엔딩·승리·패배 음악은 루프하지 않고, 환경음과 일반 BGM은 루프 가능하게 만든다.

## 2. 생성 Provider

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `SOUND_PROVIDER` | `auto` | `auto`: `ELEVENLABS_API_KEY`가 있으면 ElevenLabs, 없으면 절차적 합성 / `elevenlabs` / `procedural` |
| `ELEVENLABS_API_KEY` | (없음) | ElevenLabs API 키. 이미지·workspace·manifest에 저장하지 않는다 |
| `SOUND_FALLBACK` | `procedural` | ElevenLabs 실패 시 절차적 합성으로 대체. `none`이면 대체하지 않고 실패 기록 |
| `SOUND_BGM_SECONDS` | `30` | `generation_spec`이 없는 BGM의 길이(초). Music API 범위인 3–600초로 맞춘다. 일반 파이프라인은 `generation_spec`의 90초를 쓰므로 이 값은 쓰이지 않는다 |
| `ELEVENLABS_OUTPUT_FORMAT` | `pcm_44100` | 무손실 PCM을 받아 WAV로 감싸 저장한다. `pcm_44100`은 ElevenLabs **Pro 요금제 이상**이 필요하다. 401/403이 오면 오류 문구와 상관없이 그 실행은 무료 요금제 최고 PCM인 `pcm_24000`으로 바꿔 한 번 다시 요청하고, 그래도 401/403이면 키·권한 오류로 본다(무압축, 단 12 kHz 이상 고음은 없음). PCM 채널 수는 문서에 없어 엔드포인트별 고정값(`PCM_CHANNELS`)을 쓴다. Sound Effects는 실측 stereo, Music은 MP3 기준 stereo로 두었고 PCM 실측이 필요하다. 형식은 크레딧에 영향이 없다. `mp3_*`를 지정하면 MP3를 그대로 저장하며 검증에 ffmpeg가 필요하다 |
| `ELEVENLABS_SFX_MODEL` | (비움) | 비우면 `model_id`를 보내지 않아 Sound Effects 엔드포인트의 기본 모델을 쓴다. 특정 모델을 고정할 때만 ID를 넣는다 |
| `ELEVENLABS_MUSIC_MODEL` | (비움) | 비우면 Music API의 기본 모델을 쓴다 |
| `SOUND_TIMEOUT_SECONDS` | `90` | API 요청 제한 시간. 긴 BGM을 Music API로 만들 때 시간이 모자라면 늘린다 |

- **ElevenLabs**: BGM이 아닌 모든 에셋(sfx·ui·voice·ambience)은 `POST /v1/sound-generation`(Sound Effects, 0.5–30초), BGM은 `POST /v1/music`(`music_length_ms`)을 호출한다. 기본은 무손실 PCM(`pcm_44100`)으로 받아 WAV로 저장한다. 무료 요금제는 Music API를 쓸 수 없으므로(HTTP 402 `paid_plan_required`) BGM은 절차적 합성으로 대체된다.
- **실패 처리**: 연결 실패(DNS·연결 거부), HTTP 401/403(키·권한), 할당량 초과(`detail.status` = `quota_exceeded`), 효과음 엔드포인트의 응답 타임아웃·연결 끊김이 한 번 나면 그 실행의 남은 에셋은 ElevenLabs를 다시 호출하지 않고 바로 대체(fallback)한다.
  - Music API(`/v1/music`)의 타임아웃·오류(402 포함)는 그 에셋만 실패로 보고, BGM은 절차적 합성으로 대체한다. BGM을 Sound Effects 엔드포인트(최대 30초)로 만들지 않는다.
  - 할당량 초과가 아닌 429(동시 요청·속도 제한)는 `Retry-After`(최대 30초)만큼 기다렸다가 한 번 재시도한다.
- **기술 QC 재생성**: ElevenLabs가 오디오를 돌려주면 `validate_sound`와 같은 G1·G2 검사(`sound_pipeline.validation.check_asset`)를 바로 실행한다. 보정으로 못 고치는 필수 기준 실패(무음·디코딩 실패, 길이 불일치, 클리핑 등)면 같은 요청으로 **한 번** 다시 생성하고, 그래도 실패하면 절차적 합성으로 대체한다. `SOUND_FALLBACK=none`이면 두 번째 결과를 그대로 저장해 `validate_sound`가 판정한다. 재생성·대체 사유는 `notes`에 남는다. 에셋당 API 호출은 최대 2회다(429·요금제 PCM 재시도 제외).
- **절차적 합성(procedural)**: 외부 의존성 없이 표준 라이브러리로 합성하는 오프라인 대체 음원이다. API 키가 없어도 Workflow와 Unity 연결을 끝까지 테스트할 수 있지만 품질은 임시용이다.

## 3. 결과물

```text
workspace/{project_id}/generated/sounds/
├─ <stem>.wav                   # 기본 WAV. ELEVENLABS_OUTPUT_FORMAT=mp3_*이면 <stem>.mp3
├─ processed/<stem>.wav         # validate_sound의 G2 보정본 (보정이 있을 때만)
└─ sound_draft.json             # SoundDraft
```

`SoundDraft`:
- `status`: 필수 에셋이 모두 생성되면 `generated`, 하나라도 실패하면 `failed` (`missing_required_asset_ids`에 기록)
- `assets[]`: `asset_id`, `name`, `kind`, `unity_binding_key`, `artifact`(ArtifactReference, `audio/mpeg` 또는 `audio/wav`), `file_format`, `duration_seconds`(파일에서 실측), `loop`, `mixer_group`, `prompt`, `provider`
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
uv run --locked python -m unittest tests.test_sound_generation tests.test_sound_validation `
  tests.test_agent_sound_assets tests.test_presentation_sound_assets -v
```

## 5. Unity 재생 연결

`apply_assets_to_game`은 `validate_sound`가 `validated_assets`에 올린 에셋(PASS·FIX, 보정본이 있으면 보정본)만 Unity 프로젝트에 복사한다. REVIEW·REGENERATE 에셋은 적용하지 않는다. 각 사운드의 `audio_cue`는 `generation_spec.audio_cue`(에이전트가 지정한 cue)가 있으면 그것을, 없으면 `purpose`/`description` 키워드(`game_pipeline/asset_specs.py`의 `SOUND_CUE_KEYWORDS`)로 정해 `AssetBindingManifest.json`에 기록한다. Unity 빌드 시 `GeneratedAssetBinder`가 `GeneratedGame/Audio`에 `GeneratedAudioCuePlayer`를 붙이고, 게임플레이 코드가 `GameAudioCues.Raise(...)`로 큐를 발생시키면 해당 사운드를 재생한다.

| 큐 | 발생 지점 |
|---|---|
| `scene_start` | 씬 시작 (일반 BGM·환경음) |
| `game_clear` / `game_over` | 골 도달 / 플레이어 사망·기지 파괴 (엔딩·승리·패배 음악은 이때 기존 BGM을 멈추고 재생) |
| `player_hit` / `enemy_hit` | `Player` 태그 오브젝트의 체력 감소 / 그 외 오브젝트의 체력 감소 |
| `jump`, `attack`, `pickup`, `level_up`, `checkpoint` | 점프, 투사체 발사, 아이템·경험치 획득, 레벨업, 체크포인트 |
| `card_play`, `ui`, `activity` | 카드 사용, 선택지·업그레이드 선택, 육성 행동 완료 |
| `tower_built`, `tower_upgraded`, `enemy_defeated`, `base_damaged` | 타워 건설·업그레이드 성공, 적 처치, 적의 기지 도달 |
| `wave_started`, `boss_arrived`, `boss_spawn` | 웨이브 시작, 보스 웨이브 시작, 보스 생성 |

전체 목록은 `unity_template/Assets/GameTemplate/Runtime/Core/GameAudioCues.cs`가 기준이며 `SOUND_CUE_KEYWORDS`와 맞춰야 한다.

맞는 큐가 없는 효과음은 재생되지 않고 매니페스트 `warnings`에 남는다.

### 믹서 그룹

종류별 믹서 그룹은 Unity `AudioMixer` 에셋이 아니라 코드(`Runtime/Core/GameAudioMixer.cs`)로 구현한다.
- `AudioMixer` 에셋과 그룹은 Unity Editor의 Audio Mixer 창에서만 만들 수 있다(공개 API 없음). 자동 생성 파이프라인에서는 사람이 이 작업을 할 수 없다.
- Web(WebGL) 빌드는 `AudioMixer`에서 그룹 볼륨만 지원하고 이펙트는 지원하지 않는다. 그래서 코드로 만든 그룹 볼륨 표와 기능 차이가 없다.

| 사운드 kind | 그룹 (`generation_spec.mixer_group`) |
|---|---|
| bgm | `Music` |
| sfx | `SFX` |
| ui | `UI` |
| voice | `Voice` |
| ambience | `Ambience` |

- `GeneratedAssetBinder`가 각 사운드의 `mixer_group`을 `GeneratedAudioCuePlayer` 바인딩에 기록한다.
- 효과음은 재생할 때 그룹 볼륨을 적용한다(`PlayOneShot` volumeScale).
- 음악·환경음은 `GameAudioMixer.SetVolume(group, value)`가 호출되면 재생 중에도 즉시 볼륨이 바뀐다.
- `AudioManagerModule.SetMusicVolume` / `SetEffectsVolume`은 각각 `Music` / `SFX` 그룹 볼륨도 바꾼다. 전체 볼륨은 기존대로 `AudioListener.volume`이다.
- **볼륨 단위**: 그룹 볼륨은 **1–100**, 기본값 **50**이다.
  - 50은 원본 사운드다. 즉 `validate_sound`가 라우드니스 정규화한 에셋을 그대로 재생하는 레벨이다.
  - 실제 gain은 값/100이다. 50이면 0.5(−6 dB), 100이면 1.0(+6 dB)이다.
  - Unity `AudioSource.volume`은 1.0을 넘을 수 없다. 그래서 모든 소리를 기본 50에서 같은 6 dB 헤드룸을 두고 재생해야 100까지 올릴 수 있다. 소리 간 비율은 원본 그대로이고, 전체 크기는 기기 볼륨이 맞춘다.
  - 코드 API(`GameAudioMixer.SetVolume`, `AudioManagerModule.SetMusicVolume` 등)는 gain(0–1)을 받는다. 0.5가 기본이다.
- **에디터 조절**: 생성된 씬의 `GeneratedGame/Audio` 오브젝트(`GeneratedAudioCuePlayer`) 인스펙터 **Mixer Group Volume (1-100, 50 = original)**에서 그룹별 슬라이더로 조절한다.
  - Edit 모드에서 바꾸면 씬에 저장되는 시작 볼륨이 된다.
  - Play 모드에서 바꾸면 즉시 반영된다. 이 값은 Play 종료 시 Unity 규칙대로 되돌아간다.
  - 코드에서 바꾼 값(`GameAudioMixer.SetVolume`, 옵션 메뉴 등)도 슬라이더에 반영된다.
  - Play 중 Inspector에서는 **실제로 움직인 그룹만** 믹서에 적용된다. 코드로 1 미만(예: 0으로 음소거)으로 바꾼 그룹은 슬라이더에 1로 표시되지만, 그 그룹의 슬라이더를 직접 움직이기 전까지 실제 볼륨(0)이 유지된다.
  - 한 세션에서 이미 정해진 그룹 볼륨은 씬을 다시 불러와도 유지되며, 씬에 저장된 시작 볼륨보다 우선한다.
- 개별 사운드의 AudioSource **Volume**은 그룹 볼륨이 곱해지기 전의 기본값으로 유지된다. 최종 볼륨은 AudioSource Volume × (그룹 값/100) × 전체 볼륨이다.

### 원본 에셋 라우드니스

`validate_sound`는 모든 에셋을 kind별 목표 라우드니스로 정규화한 사본(`generated/sounds/processed/<stem>.wav`)을 만들고, 게임에는 항상 이 사본을 적용한다. 같은 kind의 에셋은 같은 크기로 들리고, 그룹 슬라이더가 모두 50인 기본 믹스에서도 효과음이 음악보다 앞에 들린다.

| kind | 목표 (integrated LUFS) |
|---|---|
| sfx | -14 |
| ui · voice | -16 |
| bgm | -18 |
| ambience | -22 |

- 측정은 ITU-R BS.1770 integrated loudness다. K-weighting과 400 ms 블록 게이팅을 쓴다. 0.4초보다 짧은 효과음은 클립 전체를 한 블록으로 본다.
- mono 에셋은 Unity가 양쪽 스피커로 재생하므로 stereo와 같은 기준이 되도록 +3 dB로 계산한다.
- 목표 gain을 적용한 뒤 피크가 -1.1 dBFS를 넘으면 5 ms look-ahead 리미터로 누른다.
- 리미터는 피크와 함께 라우드니스도 깎는다. 감쇠가 빠른 타격음은 에너지가 순간적인 시작음에 몰려 있어 특히 많이 깎인다. 그래서 결과가 목표보다 0.5 LU 이상 낮으면, 목표에 도달하는 make-up gain을 이분 탐색한다. 탐색 범위는 리미터 감쇠 **최대 12 dB**까지다.
- 최종 라우드니스가 목표의 **±1 LU**를 벗어나면 `sound-loudness-match`(필수) 실패로 **REGENERATE** 판정한다. 12 dB 넘게 눌러야 하는 소리는 타격감이 뭉개지므로 정규화로 억지로 맞추지 않는다.
  - `generate_sound`가 ElevenLabs로 한 번 재생성한다. 그래도 실패하면 절차적 합성으로 대체한다. 절차적 합성 결과는 모든 kind에서 목표 ±0.5 LU 안에 든다.
- 키워드로 분류된 에셋(`generation_spec` 없음)은 kind가 `sfx`로 남는다. 그래서 목표는 category가 `ui`·`ambience`이면 그 값을 따른다.
- 측정값(`source_loudness_lufs`, `loudness_lufs`, `normalize_gain_db`, `limiter_reduction_db`)은 `sound_profile.json`의 `metrics`에 남는다.
- 정규화는 보정(FIX)으로 치지 않는다. 문제없는 에셋은 PASS인 채로 정규화 사본이 적용된다.
- 처리 순서는 원본 클리핑 검사 → DSP 보정(DC 제거·무음 트리밍·페이드·루프 연결) → 최종 라우드니스 정규화·리미터 → 최종 검증이다. 보정 전에는 리미터를 적용하지 않으므로 감쇠가 누적되지 않는다. 정규화 후 피크·꼬리·루프 연결부도 다시 검사한다.
- 그룹 이름은 `game_pipeline/asset_specs.py`의 `mixer_group`과 `GameAudioMixer` 상수가 같아야 하며 `tests/test_unity_template.py`가 검사한다.
- 덕킹, 리버브 같은 그룹 이펙트는 없다.

같은 큐에 사운드가 여러 개 연결되면 음악은 첫 번째 트랙 하나만 재생하고(다른 음악은 모두 정지), 효과음은 매번 하나를 무작위로 골라 재생한다.

큐 분류는 키워드 매칭이다. 영문 키워드는 단어 단위로만 맞추고(`ui`가 `guitar`·`build`에 걸리지 않음), `피해`·`사망`·`clear`처럼 뜻이 여러 개인 단어는 `피해를 입`·`플레이어 사망`·`stage clear` 같은 구문으로만 맞춘다.

## 6. 현재 한계

- `validate_sound`는 `sound_pipeline/SoundValidationPlan.md`의 G1(기술 QC)·G2(DSP 보정)·중복 검사·판정까지 구현돼 있다 (`sound_pipeline/validation.py`). 결과는 `validation/sound_validation_result.json`·`validation/sound_profile.json`, 라우드니스 정규화·보정본은 `generated/sounds/processed/<asset>.wav`에 저장하며 게임에는 이 파일을 적용한다. `mp3_*` 형식을 쓸 때만 MP3 디코딩에 ffmpeg가 필요하다(기본 PCM/WAV는 필요 없음). Docker 이미지에는 포함돼 있지만 Windows에서 `uv run`으로 실행하면 직접 설치해 PATH에 넣어야 한다 (예: `winget install Gyan.FFmpeg`). ffmpeg가 없으면 MP3 에셋은 결함으로 보지 않고 `sound-validator-unavailable` issue와 함께 REVIEW로 둔다.
- 절차적 합성 대체물도 결정적 검사를 통과하면 PASS/FIX로 적용되고, `sound_validation_result.json`의 `fallback_asset_ids`에 표시된다.
- G3(내용 적합성 모델)·후보 선택·G5 믹스 테스트·라우드니스 위계는 아직 없다. 재생성은 `generate_sound` 안의 1회뿐이므로, `validate_sound`에서 REGENERATE가 나오면(예: 중복, binding key 불일치) 그 에셋은 빠진 채로 적용되고 최종 검증은 실패한다.
- 프롬프트에는 요청서의 한국어 설명과 조건이 그대로 들어간다. 영어 번역 단계를 추가하면 ElevenLabs 결과가 더 안정적일 수 있다.
- 비용 기록, 실행당 비용 상한, 실패 증상에 맞춘 프롬프트 수정은 없다. G3(내용 적합성)를 도입할 때 함께 추가한다.
- ElevenLabs 음악 API의 `model_id`와 `output_format` 세부 값은 최신 API 문서로 확인한 뒤 환경변수로 지정한다.
