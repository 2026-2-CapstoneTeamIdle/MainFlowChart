# Team IDLE Unity 2D Template

게임 생성 파이프라인이 프로젝트별 Unity 작업 공간을 만들 때 복사하는 최소 템플릿이다. 장르별 기능을 직접 포함하지 않고, 공통 부트스트랩과 모듈 연결 규칙만 제공한다.

## 기준 환경

- Unity `6000.0.71f1` (Unity 6 LTS)
- Built-in Render Pipeline
- 2D Sprite, Tilemap, Physics 2D 패키지
- 시작 씬: `Assets/Scenes/Bootstrap.unity`

## 런타임 구조

- `GameTemplateConfig`: 계약 버전, 게임 이름, 장르, 시작 씬, 선택 모듈 ID를 보관한다.
- `GameBootstrap`: 자식 오브젝트의 `IGameModule` 구현을 찾아 초기화하고 종료한다.
- `IGameModule`: 모든 공통·장르 모듈이 따르는 생명주기 계약이다.
- `GameContext`: 설정과 검증 수집기를 모듈에 전달한다.
- `ValidationProbe`: 자동 검증에서 읽을 수 있는 구조화된 실행 이벤트를 수집한다.

## 제공 기능 모듈

- 공통: 상태 저장소, 이벤트 규칙, 입력, 저장, 씬 전환, 에셋·오디오·UI, 체력·투사체·재화
- 플랫포머: 좌우 이동·점프, 수집물, 스테이지 목표
- 타워 디펜스: 웨이브 생성, 경로 이동, 타워 자동 공격, 기지 체력
- 카드: 덱·손패·버림패, 턴, 카드 자원, 카드 효과 실행
- 비주얼 노벨: 대화 진행, 플래그, 선택지 분기, 엔딩 판정
- 육성 시뮬레이션: 능력치, 날짜·턴, 활동, 일정 이벤트, 결과 엔딩
- 뱀서류: 8방향 이동, 적 생성·추적, 자동 투사체 공격, 경험치, 등급별 3개 강화 선택지

`game_logic_design.json`의 `selected_modules` ID는
`Editor/ModuleComponentCatalog.cs`에서 실제 `MonoBehaviour` 타입으로 변환된다. 프로젝트 생성기는
게임별 프리팹·수치·에셋 참조를 주입하고, 공통 구현은 이 템플릿에서 재사용한다.

## 자동 생성 프로젝트

`UnityProjectGenerator`는 이 템플릿을 `workspace/{project_id}/game/unity_project`로 복사하고
`GameTemplateConfig.asset`, `GameLogicDesign.json`, `GameBlueprint.json`, `GenerationManifest.json`을 생성한다. 생성된
프로젝트에는 `GenerationRequest.json`이 포함되며, Unity에서 처음 열면
`TemplateProjectBuilder`가 요청을 감지한다. 이어서 `PrefabSceneAssembler`가 선택된 모듈을
Bootstrap 씬에 배치하고 장르별 Environment, Entities, UI 계층과 테스트용 prefab을 생성한다.
이미지 Agent의 최종 에셋을 적용하기 전에는 자동 생성된 단색 placeholder sprite가 사용된다.
검증된 에셋이 적용되면 `GeneratedAssetBinder`가 `AssetBindingManifest.json`을 읽어 Texture/Audio
Importer 설정, AssetRegistry 등록, 장르별 씬 Sprite 및 AudioSource 연결을 수행한다. 타일셋 분할은
Sprite Editor data provider가 프레임 생성 capability를 제공할 때만 실행하며, 제공하지 않는 Unity
버전에서는 단일 Sprite로 안전하게 유지한다. 사운드의 요청 mixer group은 report에 기록하지만
기존 AudioMixer 구성이 확인되지 않은 상태에서는 자동 생성하거나 임의로 라우팅하지 않는다.

Play 모드의 왼쪽 테스트 HUD에서는 장르에 따라 이동·점프, 웨이브 시작, 카드 사용, 대화 진행,
육성 행동, 경험치 및 강화 선택을 확인할 수 있다. 생성 결과와 prefab 목록은
`Assets/GameTemplate/Generated/SceneAssemblyReport.json`에 기록된다.

이미지·사운드 담당 Flow가 읽을 요청 목록은 다음 파일에도 포함된다.

- `Assets/GameTemplate/Generated/AssetRequests/image_asset_request.json`
- `Assets/GameTemplate/Generated/AssetRequests/sound_asset_request.json`

각 결과물은 요청의 `asset_id`와 `unity_binding_key`를 유지해야 후속 에셋 적용 단계에서 동일한
씬 슬롯을 찾을 수 있다.

## 사용 방법

1. Unity Hub에서 이 디렉터리를 프로젝트로 추가한다.
2. Unity `6000.0.71f1`로 연다.
3. 필요하면 `Tools > Team IDLE > Rebuild Bootstrap Scene`을 실행한다.
4. Play를 눌러 Console의 `UNITY_TEMPLATE_READY` 메시지를 확인한다.

파이프라인의 `validate_game`은 Unity 버전을 `ProjectVersion.txt`에서 읽고 같은 버전의 Editor를
찾아 `TemplateProjectBuilder.BuildForBatch`를 실행한다. 배치 검증은 모든 모듈이 실제 컴포넌트로
부착되는지, 장르별 씬 구조가 생성되는지 확인하고 `UNITY_MODULE_CATALOG_OK`,
`UNITY_SCENE_ASSEMBLY_OK`, `UNITY_TEMPLATE_BUILD_OK` 로그를 모두 요구한다.

`Library`, `Temp`, `Logs`, 빌드 결과는 생성 파일이므로 Git에 포함하지 않는다. 파이프라인 생성기는 이 템플릿을 복사한 후 `GameTemplateConfig`와 모듈 프리팹을 요구사항에 맞게 구성한다.
