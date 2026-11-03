# Visual Validation Manager

버전: 1.1.0

## 목적과 순서

시각 검증 모드는 운영 그래프에서는 에셋이 Unity 프로젝트에 적용된 뒤 실행된다. 별도
`--game-test` 그래프에서는 이미지·사운드 생성 및 적용 Node를 전혀 등록하지 않고 게임 모듈과
임시 에셋만으로 실행한다.

1. 기존 Unity 검증과 기능 체크리스트를 통과시킨다.
2. 검증 전용 `run_node_llm(output="image")` 호출로 16:9 목표 게임 화면을 만든다.
3. 그래픽이 활성화된 Unity Play Mode에서 실제 게임 화면을 캡처한다.
4. Qwen3-VL-4B-Instruct Q4_K_M이 두 이미지와 `Visual Checklist.md`, 프로젝트 파일 목록을 비교한다.
5. 실패 finding을 기존 공통 LLM provider와 체크리스트 수정기를 통해 생성 프로젝트 파일에 반영한다.
6. Unity 컴파일·Play Mode·기능 체크리스트를 다시 통과한 경우에만 재캡처한다.
7. 최초 비교를 포함해 최대 3회 실행한 뒤 최종 검증이 프로젝트를 다시 검사하고 ZIP을 만든다.

컴파일 또는 기능 검증을 깨뜨린 수정은 해당 파일을 원본 내용으로 되돌린다. 테스트, 패키지,
ProjectSettings는 수정 대상이 아니다.

## 실행 모드

기존 실행과 비용을 보호하기 위해 기본값은 비활성이다.

```powershell
# VLM 검증 포함
uv run --locked python -m mainflow.run_flow `
  --visual-validation `
  --image-style "Pixel Art" --mood-style "Fantasy" `
  --genre "플랫포머" --viewpoint "사이드뷰" `
  --condition "플레이어가 보석을 모아 목적지에 도달한다."

# 환경 변수로 켜져 있어도 이번 실행만 생략
uv run --locked python -m mainflow.run_flow `
  --skip-visual-validation `
  --image-style "Pixel Art" --mood-style "Fantasy" `
  --genre "플랫포머" --viewpoint "사이드뷰" `
  --condition "플레이어가 보석을 모아 목적지에 도달한다."
```

환경 변수 방식은 `MAINFLOW_VISUAL_VALIDATION=1`이며,
`MAINFLOW_VISUAL_VALIDATION_ATTEMPTS`는 1~3만 허용한다.

### 이미지·사운드 없는 게임 테스트

다음 모드는 운영 그래프의 Edge를 변경하지 않는 별도 그래프다.

```powershell
uv run --locked python -m mainflow.run_flow `
  --game-test `
  --image-style "Pixel Art" --mood-style "Fantasy" `
  --genre "플랫포머" --viewpoint "사이드뷰" `
  --condition "플레이어가 보석을 모아 목적지에 도달한다."
```

실행 순서는 `모듈 합성 → Unity 컴파일 → 기능 체크리스트 → 시각 체크리스트`다.
`generate_image`, `generate_sound`, 이미지·사운드 검증, `apply_assets_to_game`은 등록되지 않는다.
시각 검증이 필수이므로 `--game-test`와 `--skip-visual-validation`은 함께 사용할 수 없다.

## 모델과 검증 전용 목표 이미지 생성기

- 기본 VLM API 이름: `qwen3-vl-4b-instruct-q4-k-m`
- provider: `LLM_VISUAL_VALIDATION_PROVIDER=local`
- 출력 상한: `LLM_VISUAL_VALIDATION_MAX_TOKENS=768` (허용 범위 256~2048)
- 응답 형식 재시도: `LLM_VISUAL_VALIDATION_RESPONSE_ATTEMPTS=2` (허용 범위 1~3)
- 교체: `LLM_VISUAL_VALIDATION_MODEL`과 provider를 바꾼다. 현재 이미지 content block은
  `local` 또는 `openai` provider를 지원한다.
- 전송 형식: 기존 `LLMSettings`와 OpenAI-compatible provider의 multimodal content block을 사용한다.
- 코드 수정 LLM: 기존 `LLM_FEATURE_CHECKLIST_REPAIR_PROVIDER` 또는
  `MAINFLOW_FEATURE_PROVIDER` 설정을 그대로 사용한다.

Qwen3-VL은 이미지를 **판독**하고, 목표 화면은 `RunNodeLLMVisualTargetGenerator`가
`run_node_llm(output="image")`로 만든다. 기본 별칭은 `sd_turbo`이며 다음 값만 사용한다.

- `MAINFLOW_VISUAL_TARGET_AI=sd_turbo`
- `MAINFLOW_VISUAL_TARGET_SIZE=512x288`
- `MAINFLOW_VISUAL_TARGET_STEPS=2`

이 경로는 `MAINFLOW_IMAGE_BACKEND`, `mainflow/image_backends.py`, `image_draft`, 에셋 manifest를
읽거나 수정하지 않는다. 생성 원본과 고정 비교본은 모두 `validation` category에 기록되며 Unity
에셋 적용기의 입력으로 전달되지 않는다. 따라서 기존 게임 에셋 이미지 생성 기능과 독립적이다.

LocalAI에는 `LocalAI/preload-visual.yaml`을 선택한다. 이 구성은 코드 모델과 VLM을 모두
등록하고, 활성 backend를 한 번에 하나만 유지하여 VRAM을 공유한다.

```powershell
$env:LOCALAI_PRELOAD_MODELS_CONFIG = "/configuration/preload-visual.yaml"
docker compose -f compose.yaml -f LocalAI/compose.yaml up -d --force-recreate Local-AIModel
```

## Unity와 Docker 제한

캡처 프로세스는 `-nographics`를 사용하지 않는다. 현재 Docker mainflow 컨테이너에는 Unity
Editor와 그래픽 세션이 없으므로 실제 캡처는 `UNITY_EDITOR_PATH`가 설정된 호스트에서 실행한다.
완전한 서버 배포에서는 Unity Linux Editor 라이선스, GPU/가상 디스플레이가 있는 별도 Unity
worker로 같은 캡처 명령을 옮겨야 한다. VLM은 LocalAI Docker 안에서 계속 실행할 수 있다.

## 결과 파일

- `validation/visual_validation_result.json`: 모드, 상태, 모델, 회차별 점수/finding/수정 파일
- `validation/visual_target_source_*.png`: `run_node_llm`이 만든 검증 전용 원본
- `validation/visual/target.png`: 목표 화면
- `validation/visual/attempt_N.png`: 회차별 Unity 실제 캡처

비활성 실행도 `visual_validation_result.json`에 `mode=disabled`, `status=skipped`를 남긴다.

## 실제 통합 검증 기록

2026-10-30에 Windows Unity 6000.3.20f1과 LocalAI v4.11.0에서 다음을 확인했다.

- Qwen3-VL Q4_K_M 본체와 Q8 vision projector 다운로드 및 해시 검증 완료
- workspace PNG 두 장을 넣은 `/v1/chat/completions` vision 요청 성공
- 공통 `VisualVLMReviewer`가 압축 JSON을 계약 형식으로 확장해 VC01~VC10을 모두 반환
- Unity Play Mode에서 RenderTexture로 1280×720 화면 캡처 후 PNG 변환 성공
- 같은 Unity 캡처를 목표/현재 화면으로 비교한 결과: `passed`, 80점, finding 0개

실측 과정에서 긴 JSON의 무제한 생성이 300초를 넘는 문제가 있어 VLM 출력 상한을 추가했고,
로컬 모델의 `pass/fail/unknown/critical` 표현을 정식 계약 상태로 정규화했다. Unity
`ScreenCaptureModule` 참조 문제를 피하기 위해 캡처는 Core RenderTexture → PPM → Pillow PNG
경로를 사용한다. 통합 증거는 테스트 프로젝트의
`validation/visual/integration_test_result.json`과 ArtifactManager manifest에 기록된다.
