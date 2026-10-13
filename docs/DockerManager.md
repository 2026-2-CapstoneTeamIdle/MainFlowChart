# Docker Manager

Docker는 Python 3.11, uv, LangGraph 의존성을 동일하게 고정해 팀원이 별도 임시 환경 구성 없이
MainFlow를 실행하도록 한다. 호스트의 `workspace/`는 컨테이너 `/app/workspace`에 연결된다.

## 기본 실행

저장소 루트에서 실행한다.

```powershell
docker compose build
docker compose run --rm mainflow
```

기본 요청은 다음과 같다.

```text
image_style = Pixel Art
mood_style  = Fantasy
genre       = 플랫포머
viewpoint   = 사이드뷰
condition   = 공격과 8방향 이동이 가능한 게임
```

입력값을 바꾸려면 다음처럼 명령을 덮어쓴다.

```powershell
docker compose run --rm mainflow `
  /app/.venv/bin/python -m mainflow.run_flow `
  --image-style Anime `
  --mood-style Cyberpunk `
  --genre "뱀서류" `
  --viewpoint "탑다운" `
  --condition "자동 공격과 성장 기능이 있는 게임"
```

Custom 참고 이미지는 저장소 안의 읽기 가능한 파일을 컨테이너 경로로 지정한다.

```powershell
docker compose run --rm mainflow `
  /app/.venv/bin/python -m mainflow.run_flow `
  --image-style Custom `
  --custom-image /app/examples/reference.png `
  --mood-style Medieval `
  --genre "타워 디펜스" `
  --viewpoint "탑다운" `
  --condition "타워를 배치해 적을 막는 게임"
```

## 테스트

```powershell
docker compose --profile test run --rm test
```

## Local Web

```powershell
docker compose -f "CI/CD/LocalWeb/compose.yaml" up --build
```

브라우저에서 `http://localhost:8000`에 접속한다. 현재 Local Web은 입력 화면과 health API를
제공하는 골격이며 Workflow 실행 API는 아직 연결하지 않았다.

## 문제 해결

- Docker Desktop이 실행 중인지 확인한다.
- `docker version`과 `docker compose version`으로 설치 상태를 확인한다.
- 8000 포트 충돌 시 Local Web compose의 호스트 포트를 변경한다.
- 실행 산출물은 컨테이너 삭제 후에도 호스트 `workspace/`에 남는다.
