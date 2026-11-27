from __future__ import annotations

from types import SimpleNamespace

from game_pipeline.feature_evidence_audit import audit_feature_evidence


class FakeRunner:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        results = (
            self.results.pop(0)
            if self.results and isinstance(self.results[0], list)
            else self.results
        )
        return SimpleNamespace(final_response={"results": results})


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
        audit_root=tmp_path / "second-audit",
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


def test_unverifiable_positive_citation_is_retried_and_labeled_as_evidence_error(tmp_path):
    source = tmp_path / "Assets" / "Runtime" / "Game.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public void StartGame() {}", encoding="utf-8")
    row = {
        "criterion_id": "logic-feature-1",
        "satisfied": True,
        "evidence": [{"path": "Assets/Runtime/Game.cs", "quote": "missing source quote"}],
        "reason": "Implemented",
    }
    runner = FakeRunner([row])
    result = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=[{"criterion_id": "logic-feature-1"}],
        features=[{"feature_id": "feature-1"}],
        runner=runner,
    )
    assert len(runner.calls) == 2
    assert result["logic-feature-1"]["verification_status"] == "evidence_invalid"
    assert not result["logic-feature-1"]["satisfied"]


def test_bad_citation_retries_only_its_criterion(tmp_path):
    source = tmp_path / "Assets" / "Runtime" / "Game.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public void StartGame() {}", encoding="utf-8")

    def row(index, quote):
        return {
            "criterion_id": f"logic-feature-{index}",
            "satisfied": True,
            "evidence": [{"path": "Assets/Runtime/Game.cs", "quote": quote}],
            "reason": "Implemented",
        }

    runner = FakeRunner(
        [
            [
                row(index, "missing source quote" if index == 3 else "public void StartGame()")
                for index in range(8)
            ],
            [row(3, "public void StartGame()")],
        ]
    )
    result = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=[{"criterion_id": f"logic-feature-{index}"} for index in range(8)],
        features=[{"feature_id": f"feature-{index}"} for index in range(8)],
        runner=runner,
    )
    assert len(runner.calls) == 2
    assert runner.calls[1]["schema"]["properties"]["results"]["minItems"] == 1
    assert "logic-feature-3" in runner.calls[1]["prompt"]
    assert all(item["verification_status"] == "verified" for item in result.values())


def test_bad_citation_does_not_invalidate_verified_batchmates(tmp_path):
    source = tmp_path / "Assets" / "Runtime" / "Game.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public void StartGame() {}", encoding="utf-8")

    def row(index, quote):
        return {
            "criterion_id": f"logic-feature-{index}",
            "satisfied": True,
            "evidence": [{"path": "Assets/Runtime/Game.cs", "quote": quote}],
            "reason": "Implemented",
        }

    criteria = [{"criterion_id": f"logic-feature-{index}"} for index in range(8)]
    features = [{"feature_id": f"feature-{index}"} for index in range(8)]
    runner = FakeRunner(
        [
            [
                row(index, "missing source quote" if index == 3 else "public void StartGame()")
                for index in range(8)
            ],
            [row(3, "still missing source quote")],
        ]
    )
    result = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=criteria,
        features=features,
        runner=runner,
    )
    assert result["logic-feature-3"]["verification_status"] == "evidence_invalid"
    assert all(
        result[f"logic-feature-{index}"]["verification_status"] == "verified"
        for index in range(8)
        if index != 3
    )

    resumed = FakeRunner([row(3, "public void StartGame()")])
    recovered = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=criteria,
        features=features,
        runner=resumed,
    )
    assert len(resumed.calls) == 1
    assert all(item["verification_status"] == "verified" for item in recovered.values())


def test_negative_audit_verdict_remains_repairable_even_with_source_citation(tmp_path):
    source = tmp_path / "Assets" / "Runtime" / "Game.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public void StartGame() {}", encoding="utf-8")
    runner = FakeRunner(
        [
            {
                "criterion_id": "logic-feature-1",
                "satisfied": False,
                "evidence": [
                    {"path": "Assets/Runtime/Game.cs", "quote": "public void StartGame() {}"}
                ],
                "reason": "The requested action is missing.",
            }
        ]
    )
    result = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=[{"criterion_id": "logic-feature-1"}],
        features=[{"feature_id": "feature-1"}],
        runner=runner,
    )
    assert result["logic-feature-1"]["verification_status"] == "unsatisfied"


def test_audit_retries_omitted_criteria_without_claiming_success(tmp_path):
    runner = FakeRunner([])
    result = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=[{"criterion_id": "logic-user-feature-01"}],
        features=[{"feature_id": "user-feature-01"}],
        runner=runner,
    )
    assert len(runner.calls) == 2
    assert not result["logic-user-feature-01"]["satisfied"]
    assert "omitted" in result["logic-user-feature-01"]["reason"]


def test_audit_preserves_completed_batches_after_malformed_response(tmp_path):
    source = tmp_path / "Assets" / "Runtime" / "Game.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public void UpdateGame() { score++; }", encoding="utf-8")
    criteria = [{"criterion_id": f"logic-feature-{index}"} for index in range(9)]
    features = [{"feature_id": f"feature-{index}"} for index in range(9)]

    def row(index):
        return {
            "criterion_id": f"logic-feature-{index}",
            "satisfied": True,
            "evidence": [{"path": "Assets/Runtime/Game.cs", "quote": "public void UpdateGame()"}],
            "reason": "Implemented",
        }

    runner = FakeRunner([[row(index) for index in range(8)], [row(7)], [row(7)]])
    first = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=criteria,
        features=features,
        runner=runner,
    )
    assert len(runner.calls) == 3
    assert all(first[f"logic-feature-{index}"]["satisfied"] for index in range(8))
    assert not first["logic-feature-8"]["satisfied"]
    assert (tmp_path / "audit" / "progress.json").is_file()

    resumed = FakeRunner([row(8)])
    second = audit_feature_evidence(
        builder="codex_cli",
        project_root=tmp_path,
        audit_root=tmp_path / "audit",
        criteria=criteria,
        features=features,
        runner=resumed,
    )
    assert len(resumed.calls) == 1
    assert all(item["satisfied"] for item in second.values())
