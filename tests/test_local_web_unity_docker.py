from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_WEB_ROOT = REPOSITORY_ROOT / "CI" / "CD" / "LocalWeb"


def _unity_editor_version() -> str:
    project_version = (
        REPOSITORY_ROOT / "unity_template" / "ProjectSettings" / "ProjectVersion.txt"
    ).read_text(encoding="utf-8")
    for line in project_version.splitlines():
        if line.startswith("m_EditorVersion: "):
            return line.removeprefix("m_EditorVersion: ").strip()
    raise AssertionError("Unity project version is missing")


def test_local_web_image_contains_matching_unity_webgl_editor() -> None:
    version = _unity_editor_version()
    dockerfile = (LOCAL_WEB_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert f"unityci/editor:ubuntu-{version}-webgl-3" in dockerfile
    assert "test -x /opt/unity/Editor/Unity" in dockerfile
    assert "PlaybackEngines/WebGLSupport" in dockerfile
    assert 'ENTRYPOINT ["/app/CI/CD/LocalWeb/docker-entrypoint.sh"]' in dockerfile


def test_local_web_compose_persists_unity_license_and_sets_editor() -> None:
    compose = (LOCAL_WEB_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "UNITY_EDITOR_PATH: /opt/unity/Editor/Unity" in compose
    assert "DISPLAY: :99" in compose
    assert "target: /home/mainflow/.local/share/unity3d" in compose
    assert "target: /home/mainflow/.config" in compose
