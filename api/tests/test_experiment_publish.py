"""Publish an Experiment without calling LangSmith from the regular check."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.evaluation import (
    DATASET_NAME,
    LANGSMITH_PROJECT,
    local_command,
    main,
    publish_experiment,
    run_experiment,
    run_local_experiment,
    scripted_judge,
    scripted_turn,
)

_CASE_ORDER = (
    "pin-wins",
    "ambiguous-reply",
    "revision",
    "identified-reply",
    "research",
)


class _Client:
    def __init__(self):
        self.dataset = None
        self.examples = []
        self.projects = []
        self.runs = []
        self.feedback = []
        self.updates = []
        self.updated_runs = []

    def has_dataset(self, *, dataset_name):
        return self.dataset is not None and self.dataset.name == dataset_name

    def read_dataset(self, *, dataset_name):
        if self.dataset is None or self.dataset.name != dataset_name:
            raise AssertionError(f"missing dataset {dataset_name}")
        return self.dataset

    def create_dataset(self, *, dataset_name, description=None):
        self.dataset = SimpleNamespace(id="dataset-1", name=dataset_name, description=description)
        return self.dataset

    def list_examples(self, *, dataset_id):
        return [example for example in self.examples if example.dataset_id == dataset_id]

    def create_example(self, *, inputs, dataset_id, metadata):
        example = SimpleNamespace(
            id=f"example-{metadata['case_id']}",
            dataset_id=dataset_id,
            inputs=inputs,
            metadata=dict(metadata),
        )
        self.examples.append(example)
        return example

    def update_example(self, example_id, *, inputs, metadata):
        self.updates.append(example_id)
        for example in self.examples:
            if example.id == example_id:
                example.inputs = inputs
                example.metadata = dict(metadata)
                return example
        raise AssertionError(f"missing example {example_id}")

    def create_project(self, *, project_name, reference_dataset_id, description=None, metadata=None):
        project = SimpleNamespace(
            id=f"project-{len(self.projects) + 1}",
            name=project_name,
            reference_dataset_id=reference_dataset_id,
            description=description,
            metadata=metadata,
        )
        self.projects.append(project)
        return project

    def create_run(self, name, inputs, run_type, **kwargs):
        self.runs.append({"name": name, "inputs": inputs, "run_type": run_type, **kwargs})

    def create_feedback(self, run_id, key, **kwargs):
        self.feedback.append({"run_id": run_id, "key": key, **kwargs})

    def update_run(self, run_id, *, outputs=None, **kwargs):
        self.updated_runs.append({"run_id": run_id, "outputs": outputs, **kwargs})


def _blob(client):
    payload = {
        "examples": [example.inputs for example in client.examples],
        "runs": client.runs,
    }
    return json.dumps(payload, default=str)


def test_publish_upserts_the_five_cases_and_opens_a_new_experiment(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "private-inbox@gmail.com")
    experiment = run_experiment(scripted_turn, scripted_judge)
    client = _Client()

    first = publish_experiment(experiment, client)
    second = publish_experiment(experiment, client)

    assert client.dataset.name == DATASET_NAME
    assert [example.metadata["case_id"] for example in client.examples] == list(_CASE_ORDER)
    assert len(client.updates) == 5
    assert first != second
    assert first.startswith(f"{LANGSMITH_PROJECT}-")
    assert second.startswith(f"{LANGSMITH_PROJECT}-")
    assert [project.reference_dataset_id for project in client.projects] == [
        "dataset-1",
        "dataset-1",
    ]
    assert [project.metadata["langsmith_project"] for project in client.projects] == [
        LANGSMITH_PROJECT,
        LANGSMITH_PROJECT,
    ]
    assert [run["name"] for run in client.runs if run["project_name"] == first] == list(
        _CASE_ORDER
    )
    pin = next(run for run in client.runs if run["name"] == "pin-wins" and run["project_name"] == first)
    assert pin["inputs"]["chat_message"].startswith("Manda um email")
    assert pin["inputs"]["default_inbox"] == "inbox@example.com"
    assert pin["outputs"]["turn_accuracy"] == 1
    assert pin["outputs"]["failed_checks"] == []
    assert pin["outputs"]["latency"] == 0.2
    assert pin["outputs"]["cost"] == 0.01
    assert pin["outputs"]["drafts"][0]["recipient"] == "ana@example.com"
    assert pin["reference_example_id"] == "example-pin-wins"
    marina = next(example for example in client.examples if example.metadata["case_id"] == "identified-reply")
    assert marina.inputs["inbound_emails"][0]["address"] == "marina@example.com"
    blob = _blob(client)
    assert "private-inbox@gmail.com" not in blob
    assert "Judge one email assistant turn" not in blob
    accuracy = [
        item["score"]
        for item in client.feedback
        if item["key"] == "turn_accuracy" and item["run_id"] == pin["id"]
    ]
    assert accuracy == [1]


def test_a_failed_case_is_still_published(monkeypatch):
    def turn(context):
        if context.case_id == "revision":
            raise RuntimeError("turn failed")
        return scripted_turn(context)

    experiment = run_experiment(turn, scripted_judge)
    client = _Client()
    publish_experiment(experiment, client)

    revision = next(run for run in client.runs if run["name"] == "revision")
    assert revision["outputs"]["turn_accuracy"] == 0
    assert revision["outputs"]["failed_checks"] == ["turn"]
    assert revision["outputs"]["latency"] == 0
    assert revision["outputs"]["cost"] == 0
    assert len(client.runs) == 5


def test_local_experiment_uses_the_chat_turn_and_the_model_judge(monkeypatch, capsys):
    seen = []

    def turn(context):
        seen.append("turn")
        return scripted_turn(context)

    def judge_factory():
        seen.append("judge")
        return scripted_judge

    monkeypatch.setattr("api.evaluation.chat_turn", turn)
    monkeypatch.setattr("api.evaluation.model_judge", judge_factory)
    client = _Client()

    assert run_local_experiment(client_factory=lambda: client) == 0
    assert seen[0] == "judge"
    assert seen[1:] == ["turn"] * 5
    assert len(client.projects) == 1
    captured = capsys.readouterr().out
    assert "pin-wins" in captured


def test_local_command_publishes_after_printing(capsys):
    client = _Client()

    code = run_local_experiment(
        scripted_turn,
        scripted_judge,
        client_factory=lambda: client,
    )

    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == list(_CASE_ORDER)
    assert len(client.projects) == 1
    assert len(client.runs) == 5


def test_missing_langsmith_key_prints_the_cases_and_fails(monkeypatch, capsys):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    with pytest.raises(NotImplementedError, match="LANGSMITH_API_KEY"):
        run_local_experiment(scripted_turn, scripted_judge)

    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == list(_CASE_ORDER)


def test_scripted_judge_command_skips_langsmith_and_the_model(monkeypatch, capsys):
    calls = []

    def turn(context):
        calls.append(context.case_id)
        return scripted_turn(context)

    def boom(*_args, **_kwargs):
        raise AssertionError("langsmith or the model judge was called")

    monkeypatch.setattr("api.evaluation.chat_turn", turn)
    monkeypatch.setattr("api.evaluation.langsmith_client", boom)
    monkeypatch.setattr("api.evaluation.model_judge", boom)

    assert local_command(["--scripted-judge"]) == 0
    assert calls == list(_CASE_ORDER)
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines] == ["1", "1", "1", "1", "1"]


def test_regular_check_does_not_call_langsmith_or_the_chat_turn(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise AssertionError("regular check left the scripted path")

    monkeypatch.setattr("api.evaluation.langsmith_client", boom)
    monkeypatch.setattr("api.evaluation.chat_turn", boom)
    monkeypatch.setattr("api.evaluation.model_judge", boom)

    assert main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines] == ["1", "1", "1", "1", "1"]


def test_the_chat_turn_is_traced_outside_the_judge(monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_ADDRESS", "private-inbox@gmail.com")
    monkeypatch.setenv("LANGSMITH_PROJECT", "email-assistant")
    opened = []

    class _Run:
        def __init__(self):
            self.id = uuid.uuid4()
            self.outputs = None

        def end(self, *, outputs=None, **kwargs):
            self.outputs = outputs

    class _Trace:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.run = _Run()
            opened.append(self)

        def __enter__(self):
            return self.run

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr("langsmith.trace", _Trace)

    class _Graph:
        def invoke(self, data, config=None):
            return {
                "messages": [
                    SimpleNamespace(
                        content="O rascunho está pronto para ana@example.com.",
                        tool_calls=[],
                        usage_metadata=None,
                        response_metadata={},
                    )
                ]
            }

    monkeypatch.setattr("api.evaluation._default_supervisor", lambda: _Graph())
    monkeypatch.setattr("api.evaluation.model_judge", lambda: scripted_judge)
    client = _Client()

    run_local_experiment(client_factory=lambda: client)

    assert [item.args[0] for item in opened] == list(_CASE_ORDER)
    pin = opened[0]
    assert pin.kwargs["project_name"].startswith("email-assistant-")
    assert pin.kwargs["reference_example_id"] == "example-pin-wins"
    assert "private-inbox@gmail.com" not in json.dumps(pin.kwargs["inputs"])
    assert "Manda um email" in pin.kwargs["inputs"]["chat_message"]
    assert "turn_accuracy" not in pin.run.outputs
    assert pin.run.outputs["latency"] >= 0
    assert client.runs == []
    assert client.updated_runs[0]["outputs"]["turn_accuracy"] == 0
    assert any(item["key"] == "turn_accuracy" for item in client.feedback)
    assert "Judge one email assistant turn" not in json.dumps(
        pin.kwargs["inputs"], default=str
    )
    captured = capsys.readouterr().out
    assert "pin-wins" in captured


def test_example_environment_names_langsmith_and_leaves_tracing_off(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    example = (root / ".env.example").read_text(encoding="utf-8")
    assert "LANGSMITH_API_KEY=" in example
    assert "LANGSMITH_PROJECT=email-assistant" in example
    active = [
        line.strip()
        for line in example.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any(line.startswith("LANGSMITH_TRACING") for line in active)
    assert not any(line.startswith("LANGCHAIN_TRACING") for line in active)
    for name in ("compose.yaml", "api/src/main.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "LANGSMITH_TRACING" not in text
        assert "LANGCHAIN_TRACING_V2" not in text

    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_PROJECT", "email-assistant")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING_V2", raising=False)
    from langsmith.utils import tracing_is_enabled

    assert tracing_is_enabled() is False
