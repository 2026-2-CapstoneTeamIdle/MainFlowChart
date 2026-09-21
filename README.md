Game Development Agent - LangGraph Skeleton

사용자의 이미지 스타일·게임 장르·퀄리티 입력을 바탕으로 이미지 생성, 게임 로직 설계, 사운드 생성을 병렬 처리하고 검증·에셋 적용·최종 검증으로 이어지는 LangGraph 기반 게임 제작 파이프라인의 초기 뼈대입니다.
현재 단계에서는 실제 AI/API/게임 엔진 처리를 수행하지 않고, Node·State·Edge 흐름과 임시 GUI 및 진행 로그만 구현합니다.

TODO

AdviserAI/LLM을 연결해 사용자 입력을 실제 GameSpec 및 검증 기준으로 파싱

이미지 생성 Agent와 이미지 결과 저장·관리 기능 구현

사운드 생성 Agent와 사운드 결과 저장·관리 기능 구현

Unity 연동 및 임시 에셋 기반 게임 로직 생성·실행 기능 구현

게임 검증 결과를 기반으로 이미지·사운드 검증서를 생성하고 각 에셋 Validator 구현

검증 완료 에셋을 게임에 적용한 뒤 최초 최종 검증서를 기준으로 최종 Validator 구현

LangGraph 시각화

컴파일된 LangGraph는 get_graph()를 통해 그래프 구조를 가져온 뒤 Mermaid 또는 PNG로 출력할 수 있습니다.

app = build_graph()

# Mermaid 문법 출력
print(app.get_graph().draw_mermaid())

PNG 파일로 저장하려면 다음과 같이 사용할 수 있습니다.

app = build_graph()

png_data = app.get_graph().draw_mermaid_png()

with open("langgraph_flow.png", "wb") as f:
    f.write(png_data)

그래프 구조를 터미널에서 간단히 확인하려면 ASCII 출력도 가능합니다.

app.get_graph().print_ascii()

현재 흐름의 개략적인 구조:

flowchart TD
    START --> UserInput[유저 입력 GUI]
    UserInput --> Parse[입력 파싱]
    Parse --> FinalSpec[최초 최종 검증서 생성]

    FinalSpec --> ImageGen[이미지 생성]
    FinalSpec --> GameDesign[게임 로직 설계]
    FinalSpec --> SoundGen[사운드 생성]

    GameDesign --> GameValidate[게임 검증]
    GameValidate --> AssetSpec[이미지/사운드 검증서 생성]

    ImageGen --> ImageValidate[이미지 검증]
    AssetSpec --> ImageValidate

    SoundGen --> SoundValidate[사운드 검증]
    AssetSpec --> SoundValidate

    ImageValidate --> ApplyAssets[검증 에셋 게임 적용]
    SoundValidate --> ApplyAssets

    ApplyAssets --> FinalValidate[최종 검증]
    FinalValidate --> END