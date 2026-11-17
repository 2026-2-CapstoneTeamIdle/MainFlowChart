from __future__ import annotations

from types import SimpleNamespace

import pytest

from game_pipeline.feature_evidence_audit import audit_feature_evidence


class FakeRunner:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(final_response={"results": self.results})


def test_audit_accepts_only_exact_unity_source_citations(tmp_path):
    source = tmp_path / "Assets" / "Runtime" / "PlayerHealth.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public void Damage(int amount) { health -= amount; }", encoding="utf-8")
    criteria = [
        {
            "criterion_id": "logic-user-feature-01",
            "description": "Damage reduces health",
        }
    ]
    features = [
        {"feature_id": "user-feature-01", "name": "Damage", "description": "Health changes"}
    ]
    response = [
        {
            "criterion_id": "logic-user-feature-01",
            "satisfied": True,
            "evidence": [{"path": "Assets/Runtime/PlayerHealth.cs", "quote": "health -= amount;"}],
            "reason": "The damage method changes health.",
        }
    ]
    runner = FakeRunner(response)
    result = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=criteria,
        features=features,
        runner=runner,
    )
    assert result["logic-user-feature-01"]["satisfied"]
    assert runner.calls[0]["sandbox"] == "read-only"

    response[0]["evidence"][0]["quote"] = "health += amount;"
    assert not audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=criteria,
        features=features,
        runner=runner,
    )["logic-user-feature-01"]["satisfied"]


def test_audit_rejects_omitted_criteria(tmp_path):
    with pytest.raises(ValueError, match="omitted"):
        audit_feature_evidence(
            builder="codex_cli",
            project_root=tmp_path,
            audit_root=tmp_path / "audit",
            criteria=[{"criterion_id": "logic-user-feature-01"}],
            features=[{"feature_id": "user-feature-01"}],
            runner=FakeRunner([]),
        )
