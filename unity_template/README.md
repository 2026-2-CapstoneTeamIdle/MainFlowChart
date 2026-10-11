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

## 사용 방법

1. Unity Hub에서 이 디렉터리를 프로젝트로 추가한다.
2. Unity `6000.0.71f1`로 연다.
3. 필요하면 `Tools > Team IDLE > Rebuild Bootstrap Scene`을 실행한다.
4. Play를 눌러 Console의 `UNITY_TEMPLATE_READY` 메시지를 확인한다.

`Library`, `Temp`, `Logs`, 빌드 결과는 생성 파일이므로 Git에 포함하지 않는다. 파이프라인 생성기는 이 템플릿을 복사한 후 `GameTemplateConfig`와 모듈 프리팹을 요구사항에 맞게 구성한다.
