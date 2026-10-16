# Sound Validation 기획서 — AI 생성 사운드의 Slop 방지

> 대상 브랜치: `feat/Sound-test` (기준 `main` `403079f`)
> 대상 노드: `create_asset_validation_spec` → `validate_sound` → (재생성 루프) → `apply_assets_to_game`
> 상태: 기획 단계. 이 문서의 수치는 **초기값**이며 실측과 사람 리뷰로 보정한다.

---

## 1. 배경

### 1.1 현재 상태
| 항목 | 상태 |
|---|---|
| `generate_sound` | ElevenLabs(효과음 `/v1/sound-generation`, BGM `/v1/music` → 402 시 효과음 엔드포인트) 또는 절차적 합성으로 생성 |
| `validate_sound` | placeholder. 항상 `status: "pending"`, `checks: []` |
| `asset_validation_spec.sound_criteria` | `[]` |
| 재생성 루프 | 없음 |

즉 **생성된 사운드를 아무도 검사하지 않고** 첫 결과가 그대로 게임에 들어간다.

### 1.2 기본 관점
현업에서 AI 생성은 "녹음" 단계에 해당한다. 녹음본을 그대로 쓰는 스튜디오는 없다.

```text
현업: 녹음(여러 테이크) → 테이크 선택 → 편집·마스터링 → 세트 단위 정리 → 인게임 믹스 → 오디오 리드 리뷰
본 기획: 생성(후보 N개) → 자동 QC → DSP 보정 → 내용 평가 → 후보 선택 → 세트 검사 → 믹스 테스트 → 판정 → (사람 리뷰)
```

Slop은 대부분 이 과정을 건너뛰고 **첫 생성물을 바로 쓰는 데서** 나온다. 그래서 validation은 합격/불합격 판정기가 아니라 **이 과정을 자동화한 파이프라인**으로 설계한다.

---

## 2. AI 사운드의 Slop 유형

| 유형 | 증상 예시 | 담당 게이트 |
|---|---|---|
| 기술 결함 | 앞뒤 무음 패딩, 클리핑, 루프 이음매 클릭, 꼬리가 뚝 잘림, DC offset, 코덱 특유의 쇳소리·스월링 | G1, G2 |
| 요구사항 불일치 | 효과음에 음악·목소리 섞임, BGM에 보컬, 길이 무시, 루프 요청인데 끝맺음이 있음 | G1, G3 |
| 정체성 부족 | 무엇을 표현한 소리인지 모호함, 밋밋한 "스톡" 사운드 | G3, 후보 선택 |
| 세트 불일치 | 에셋마다 음량·질감 제각각, 장르·분위기와 어긋남, 서로 다른 이벤트가 비슷하게 들림 | G4 |
| 실사용 결함 | BGM에 묻혀 효과음이 안 들림, 자주 나는 소리가 단조로워 피로감 | G5 |

---

## 3. 파이프라인 개요

```text
                        ┌──────────────── REGENERATE (프롬프트 수정, 재시도 예산 내) ───────────────┐
                        ▼                                                                         │
generate_sound ─▶ 후보 N개 ─▶ G1 기술 QC ─▶ G2 DSP 보정 ─▶ G3 내용 적합성 ─▶ 후보 선택 ─┐            │
                                 ▲  실패          │                                     │            │
                                 └──── 재검사 ────┘                                     ▼            │
                                                                     G4 세트 일관성 ─▶ G5 믹스 테스트 ─▶ 판정
                                                                                                    │
                                                         PASS ─▶ apply_assets_to_game ◀─────────────┤
                                                         REVIEW ─▶ G6 사람 리뷰 ─────────────────────┘
```

| 게이트 | 성격 | 비용 | 실행 단위 |
|---|---|---|---|
| G1 기술 QC | 결정적 신호 분석 | 0 | 후보 |
| G2 DSP 보정 | 결정적 편집 | 0 | 후보 |
| G3 내용 적합성 | 모델 기반 (로컬) | 낮음 | 후보 |
| 후보 선택 | 점수 순위 | 0 | 에셋 |
| G4 세트 일관성 | 통계·임베딩 | 낮음 | 게임 전체 |
| G5 믹스 테스트 | 신호 합성·분석 | 0 | BGM × 효과음 |
| G6 사람 리뷰 | 청취 | 사람 시간 | REVIEW만 |

---

## 4. 게이트 상세

### G1. 기술 QC (자동, 결정적)

| criterion_id | 검사 | 기준 (초기값) | 근거 |
|---|---|---|---|
| `sound-file-valid` | 디코딩 가능, 형식·샘플레이트·채널 확인 | MP3/WAV 디코딩 성공 | 계약, 엔진 import |
| `sound-duration-match` | 실측 길이 vs 요청 길이 | ±20% 이내 (BGM은 마디 단위 허용) | 요구사항 |
| `sound-true-peak` | True peak, 클리핑 샘플 수 | ≤ -1 dBTP, 클리핑 0 | 마스터링 표준 |
| `sound-onset-latency` | 첫 유효 소리까지 시간 | 효과음 ≤ 10 ms, UI ≤ 5 ms | 입력 반응성 (앞 무음 = 체감 지연) |
| `sound-tail-decay` | 비루프 에셋의 마지막 구간 | -60 dBFS까지 감쇠, 마지막 샘플 불연속 없음 | 잘림·클릭 방지 |
| `sound-dc-offset` | 평균 샘플값, 20 Hz 이하 에너지 | DC ≈ 0, 초저역 비율 제한 | 헤드룸 낭비 방지 |
| `sound-loop-seam` | 끝→처음 연결부의 샘플 불연속, 에너지·스펙트럼 급변 | 이음매 novelty가 본문 평균 대비 임계값 이하 | 루프 클릭·튐 |
| `sound-loop-bar-aligned` | BGM 루프 길이 vs 검출 BPM | 길이 = 정수 마디 ± 소량 | 박자 어긋남 |
| `sound-channel-layout` | 채널 수, mono 합산 시 위상 상쇄 | 3D 위치 효과음 mono / UI·BGM·환경음 stereo, 상관계수 > 0 | Unity 3D 사운드, mono 호환 |

### G2. DSP 자동 보정 (재생성보다 먼저)

현업의 편집·마스터링 단계. **API 비용 0**이므로 재생성보다 항상 먼저 시도한다.

| 증상 (G1 실패) | 보정 |
|---|---|
| 앞뒤 무음 | 임계값 기준 trim (앞은 수 ms 여유 유지) |
| 꼬리 잘림·끝 클릭 | 짧은 fade-out (5–30 ms) |
| DC offset, 초저역 | DC 제거, 고역통과 필터 (20–30 Hz) |
| 피크 초과·음량 불일치 | 카테고리별 라우드니스 정규화 + true peak 리미팅 |
| 루프 이음매 | 이음매 크로스페이드, 제로크로싱 정렬 |
| BGM 마디 불일치 | 검출 BPM 기준 마디 경계에서 자르기 |

- 보정 내역은 모두 기록한다 (`applied_fixes`).
- 보정 후 G1을 다시 실행한다. 그래도 실패하면 REGENERATE로 보낸다.
- **원본은 보존**한다. 보정본만 게임에 적용한다.

### G3. 내용 적합성 (모델 기반)

| criterion_id | 검사 | 방법 |
|---|---|---|
| `sound-prompt-match` | 프롬프트와 소리의 일치 | CLAP 계열 text-audio 임베딩 유사도. **절대 임계값이 아니라 같은 에셋 후보끼리 순위**에 사용 |
| `sound-no-music-in-sfx` | 효과음에 음악 섞임 | 오디오 분류기 (AudioSet 계열) `Music` 확률 |
| `sound-no-speech` | 효과음·BGM에 말소리, BGM에 보컬 | 분류기 `Speech`, `Singing` 확률 |
| `sound-category-profile` | 카테고리 특성 일치 | 아래 표의 신호 특징 |
| `sound-bgm-mood` | BGM과 분위기 일치 | 템포·밝기(스펙트럼 중심)·조성 경향을 분위기 프로필과 비교 |
| `sound-bgm-structure` | BGM 단조로움·산만함 | 구간별 self-similarity. 너무 같아도, 너무 달라도 감점 |

카테고리 신호 특징 (예시):
| 카테고리 | 기대 특징 |
|---|---|
| UI | 짧은 에너지 포락선, 1–6 kHz 대역 중심, 짧은 꼬리 |
| 타격·피격 | 강한 transient (crest factor 높음), 빠른 감쇠 |
| 폭발·스킬 | 저역 에너지 비중 높음, 자연스러운 긴 감쇠 |
| 환경음 | 낮은 crest factor, 튀는 개별 이벤트 적음, 정상(stationary) 신호 |
| BGM | 안정된 템포, 넓은 대역, 루프 시 끝맺음 없음 |

분위기 프로필 (예시, `MoodStyle` 기준):
| 분위기 | 템포 경향 | 밝기 | 기타 |
|---|---|---|---|
| Horror | 느림·불규칙 | 어두움 | 불협·저역 드론 |
| Cozy | 느림–중간 | 따뜻함 | 어쿠스틱, 낮은 다이내믹 |
| Cyberpunk | 중간–빠름 | 밝음·날카로움 | 강한 저역 펄스 |
| Fantasy | 중간 | 중간 | 오케스트라 질감 |
| Medieval | 중간 | 중간 | 어쿠스틱 타악 |
| Modern | 중간–빠름 | 밝음 | 깔끔한 전자음 |

### 후보 선택 (Take Selection)

Slop을 가장 확실하게 줄이는 단계.

- 중요 에셋은 후보 2–4개를 생성하고, G1–G3 점수로 최고 후보를 고른다.
- 후보 수 정책:

| 에셋 | 후보 수 |
|---|---|
| BGM, `required` 핵심 피드백 효과음 (공격·피격·획득) | 3 |
| 기타 `required` 효과음 | 2 |
| 선택 에셋, 환경음 | 1 |

- 탈락 후보도 점수와 함께 기록한다 (리뷰·보정 데이터).
- 비용 증가분은 4.8의 재시도 예산과 합산해 관리한다.

### G4. 세트 일관성 (게임 전체 단위)

| criterion_id | 검사 | 기준 |
|---|---|---|
| `sound-set-loudness-hierarchy` | 카테고리별 라우드니스 순서와 범위 | 핵심 피드백 효과음 > UI > 환경음, 효과음이 BGM보다 잘 들림 (5장 표) |
| `sound-set-cohesion` | 효과음 간 질감 차이 (스펙트럼 중심, 잔향 정도, 임베딩 거리) | 세트 평균에서 지나치게 먼 에셋 경고 (예: Pixel Art 게임에 실사 폭발음 하나) |
| `sound-set-distinct` | 서로 다른 이벤트 간 유사도 | 임베딩 유사도 임계값 초과 시 경고 (예: 코인 획득음 ≈ 피격음) |
| `sound-set-duplicate` | 중복 결과물 | 해시·임베딩 거의 동일 시 실패 |

### G5. 믹스 테스트 (인게임 상황 시뮬레이션)

| criterion_id | 검사 | 방법 |
|---|---|---|
| `sound-mix-masking` | 효과음이 BGM에 가려지는지 | 효과음을 BGM 위에 겹쳐, 효과음의 주요 대역에서 효과음/BGM 에너지 비가 기준 이상인지 |
| `sound-repetition-fatigue` | 반복 피로 | 사용 빈도가 높은 이벤트(발소리·기본 공격 등)는 변주 필요 여부를 메타데이터로 표시 → Unity 단계에서 round-robin(3–5개) 또는 pitch/volume 랜덤화 |

### G6. 사람 리뷰 (REVIEW 판정만)

- 리뷰 화면: 판정 근거(점수, 파형·스펙트럼, 실패 항목) + 후보 A/B 청취 + BGM 위 믹스 청취.
- 체크 항목 (1–5점):
  1. **인식성**: 이 이벤트의 소리로 바로 들리는가
  2. **톤 적합성**: 게임의 스타일·분위기와 맞는가
  3. **반복 내성**: 20번 연속 들어도 거슬리지 않는가
  4. **품질**: 잡음·인공적인 결함이 들리는가
- 결과: `approve` / `regenerate(사유)` / `replace(수동 에셋)`.
- 사람의 판정은 **자동 점수 임계값 보정 데이터**로 축적한다 (사람과 자동 판정의 불일치율 추적).

---

## 5. 카테고리별 기준표 (초기값)

| 카테고리 | 길이 | onset | 루프 | 채널 | 라우드니스 기준 | 핵심 검사 |
|---|---|---|---|---|---|---|
| UI | 0.05–0.4 s | ≤ 5 ms | ✗ | stereo/mono | peak 기준, BGM 대비 상대 레벨 | 짧은 꼬리, 밝은 대역, 피로감 |
| 타격·피격 | 0.2–0.8 s | ≤ 10 ms | ✗ | mono | peak 기준 | 강한 transient, 음악 섞임 없음 |
| 폭발·스킬 | 1–3 s | ≤ 20 ms | ✗ | mono/stereo | short-term LUFS | 저역 에너지, 자연스러운 감쇠 |
| 일반 동작 | 0.3–1.0 s | ≤ 10 ms | ✗ | mono | peak 기준 | 인식성 |
| 환경음 | 10–30 s | — | ✓ | stereo | integrated LUFS, BGM보다 낮게 | 이음매, 반복 인식되는 튀는 이벤트 없음 |
| BGM | 30 s~ | — | ✓ | stereo | integrated LUFS | 마디 단위 길이, 보컬 없음, 분위기 일치 |
| 엔딩·징글 | 2–8 s | — | ✗ | stereo | integrated LUFS | 명확한 끝맺음 |

라우드니스 목표:
- 플랫폼 기준을 따른다. 참고: Sony ASWG-R001 권장값은 콘솔(홈) -24 LUFS, 모바일·휴대 -18 LUFS. PC·웹 인디 게임은 BGM을 -16 ~ -18 LUFS로 맞추는 경우가 많다.
- 짧은 효과음은 integrated LUFS가 의미가 없으므로 **peak 또는 short-term 기준**으로 두고, BGM 대비 상대 레벨로 관리한다.
- 프로젝트 목표 플랫폼이 정해지면 `SOUND_TARGET_PLATFORM` 같은 설정으로 표를 전환한다.

---

## 6. 판정과 재시도 정책

### 6.1 판정
| 판정 | 조건 | 처리 |
|---|---|---|
| **PASS** | 필수 criterion 모두 통과 | 보정본을 게임에 적용 |
| **FIX** | G1 실패를 G2로 해결 | 보정 후 재검사 → PASS 또는 다른 판정 (비용 0) |
| **REGENERATE** | 내용 불일치, 금지 요소 포함, 보정 불가 결함 | 실패 증상에 맞게 **프롬프트·파라미터를 수정**해 재생성 |
| **REVIEW** | 점수가 경계 구간, 세트 일관성 경고, 재시도 예산 소진, 대체(절차적) 결과물 | 사람 리뷰 |

### 6.2 증상 → 수정 매핑 (REGENERATE)
같은 프롬프트로 다시 돌리지 않는다. 증상에 따라 수정한다.

| 실패 criterion | 프롬프트·파라미터 수정 |
|---|---|
| `sound-no-music-in-sfx` | "no music, no melody, no rhythm" 강화, `prompt_influence` 상향 |
| `sound-no-speech` | "no voice, no vocals, no speech, instrumental only" 강화 |
| `sound-duration-match` | `duration_seconds` 명시 재확인, 길이 표현을 프롬프트에 추가 ("short, under 0.5 seconds") |
| `sound-category-profile` (타격 transient 약함) | "sharp, punchy attack, tight" 추가 |
| `sound-category-profile` (환경음에 튀는 이벤트) | "steady, continuous, no distinct events" 추가 |
| `sound-bgm-mood` | 분위기 설명어 교체·구체화 (악기, 템포 BPM 명시) |
| `sound-loop-seam` (보정 실패) | `loop: true` 확인, "seamless loop" 강조, BGM은 길이를 마디 단위로 재요청 |
| `sound-set-distinct` | 비슷한 두 에셋 중 하나에 대비되는 특징 추가 (음높이·재질·길이) |
| `sound-set-cohesion` | 세트 공통 팔레트 문구(스타일 힌트)를 강제 포함 |

### 6.3 재시도 예산
- 에셋당 재생성 최대 **2회** (후보 생성과 별도), 실행당 **비용 상한** 설정 (`SOUND_MAX_CREDITS_PER_RUN`).
- 예산 소진 시 최고 점수 후보를 **REVIEW**로 넘긴다 (조용히 PASS 처리하지 않음).
- 비용은 `sound_profile.json`에 에셋별·실행별로 기록한다.

### 6.4 대체(절차적 합성) 결과물
- ElevenLabs 실패로 절차적 합성이 사용된 에셋은 **PASS가 아니라 `placeholder` 표시 + REVIEW**.
- 이유: 이미지 PR #11에서 확인된 "placeholder가 검증을 `passed`로 통과" 문제를 사운드에서 반복하지 않기 위함.

---

## 7. 프로젝트 반영 방법

### 7.1 노드별 변경
| 노드 | 변경 |
|---|---|
| `create_asset_validation_spec` | `sound_criteria`를 4장의 `criterion_id`로 채움. 카테고리별 `required` 지정 |
| `generate_sound` | 후보 N개 생성, 후보별 결과를 별도 파일로 저장. REGENERATE 시 수정된 프롬프트·파라미터 수용 |
| `validate_sound` | G1–G5 실행, 판정, 보정본 저장, `SoundValidationResult` + `sound_profile.json` 작성 |
| 그래프 | `validate_sound` → REGENERATE일 때 `generate_sound`로 돌아가는 조건부 edge. 재시도 횟수는 State |
| `apply_assets_to_game` | PASS 에셋의 보정본만 적용, REVIEW 에셋은 적용하되 표시 (또는 정책에 따라 보류) |

### 7.2 계약 원칙 (이미지 PR #11 교훈)
- `validate_sound` 입력 State에 **`sound_asset_request`를 추가**한다. 카테고리·루프·필수 여부는 `plan_sound_assets()`로 **같은 함수로 다시 계산**한다.
- **draft `notes` 문자열을 파싱하지 않는다.** notes는 사람이 읽는 로그로만 쓴다.
- 요청된 `asset_id` 집합과 draft를 대조한다. 필수 누락은 error, 선택 누락은 warning issue.
- 테스트는 생성 쪽 상수를 import하지 않고 기대값을 리터럴로 적는다.

### 7.3 산출물
```text
workspace/{project_id}/
├─ generated/sounds/
│  ├─ <asset>.mp3                 # 선택된 원본
│  ├─ candidates/<asset>_c1.mp3 …  # 후보 (탈락 포함)
│  └─ sound_draft.json
├─ validation/
│  ├─ sound_validation_result.json # 계약 SoundValidationResult (checks, issues, validated_asset_ids)
│  ├─ sound_profile.json           # 측정값·판정·보정 내역·비용 (아래 예시)
│  └─ sound_report.html            # 사람 리뷰용 시각화 리포트
└─ processed/sounds/<asset>.wav    # G2 보정본 (게임 적용 대상)
```

`sound_profile.json` 예시:
```json
{
  "contract_version": "3.1.0",
  "target_platform": "pc",
  "budget": {"max_credits": 3000, "used_credits": 1840},
  "assets": [
    {
      "asset_id": "player_attack",
      "category": "impact",
      "decision": "PASS",
      "selected_candidate": "c2",
      "candidates": [
        {"id": "c1", "scores": {"prompt_match": 0.31, "music_prob": 0.42}, "failed": ["sound-no-music-in-sfx"]},
        {"id": "c2", "scores": {"prompt_match": 0.38, "music_prob": 0.03}, "failed": []}
      ],
      "metrics": {"duration_s": 0.61, "true_peak_dbtp": -1.2, "onset_ms": 4, "crest_db": 17.5},
      "applied_fixes": ["trim_leading_silence", "fade_out_10ms"],
      "regenerations": 0
    }
  ],
  "set_checks": {
    "loudness_hierarchy": "passed",
    "distinct_pairs_flagged": [["coin_pickup", "player_hit"]]
  }
}
```

### 7.4 기존 자산 재사용
로컬 `local/sound-eval` 브랜치의 `sound_eval` 패키지에 이미 아래 기능이 있다. `validate_sound`에 연결하는 것부터 시작한다.
- 라우드니스·피크·길이 측정, 루프 이음매(self-normalized novelty ratio), 템포 측정
- PASS / REGENERATE / REVIEW 판정, 증상 → 수정 매핑
- 프로파일링 HTML 리포트

---

## 8. 도입 단계

| 단계 | 내용 | 추가 의존성 | 기대 효과 |
|---|---|---|---|
| **1** | G1 + G2 + 판정 + `sound_profile.json` + 리포트, `sound_criteria` 채우기, 계약 원칙 반영 | numpy 수준 | 기술 결함 대부분 제거, 비용 0 |
| **2** | G4 라우드니스 위계·중복, G5 마스킹, 대체 결과물 REVIEW 처리 | 없음 | "제각각인 세트" 해결 |
| **3** | G3 금지 요소 분류기, 후보 선택, 재생성 루프와 증상 → 수정 매핑, 재시도 예산 | 로컬 오디오 분류 모델 | 내용 불일치 slop 제거 |
| **4** | CLAP 유사도, G4 cohesion·distinct, G6 리뷰 UI(LocalWeb), 임계값 보정 | 임베딩 모델 | 정체성·품질 향상 |

## 9. 평가 지표 (기획이 효과가 있는지 확인)

| 지표 | 정의 | 목표 방향 |
|---|---|---|
| 첫 시도 PASS율 | 재생성 없이 PASS된 에셋 비율 | 프롬프트 개선 지표 |
| FIX 비율 | DSP 보정만으로 해결된 비율 | 높을수록 비용 절감 |
| 에셋당 평균 생성 횟수 | 후보 + 재생성 | 비용 관리 |
| 사람-자동 판정 불일치율 | G6 결과 vs 자동 판정 | 낮을수록 자동 판정 신뢰 |
| 리뷰 후 교체율 | REVIEW 중 replace 비율 | 낮을수록 생성 품질 양호 |
| 실행당 비용 | 크레딧 / 실행 | 예산 내 유지 |

벤치마크: 의도적으로 결함을 넣은 샘플 세트(무음 패딩, 클리핑, 음악 섞인 효과음, 보컬 BGM, 이음매 클릭, 분위기 불일치 등)와 정상 샘플을 함께 두고, 게이트별 정밀도·재현율을 측정한다. 쉬운 사례만 있으면 100%가 나오므로 **경계 사례(사람도 판단이 갈리는 샘플)**를 반드시 포함한다.

## 10. 열린 질문 (팀 결정 필요)

1. 목표 플랫폼 (PC/웹/모바일)과 라우드니스 기준
2. REVIEW 에셋을 게임에 임시 적용할지, 보류할지
3. 실행당 비용 상한과 후보 수 정책
4. G3·G4에 쓸 로컬 모델 (Docker 이미지 크기·CPU 추론 시간 고려)
5. G6 사람 리뷰를 LocalWeb에 넣을지, 별도 도구로 둘지
