"""Tests for the few-shot serializer/builder in apps.llm.prompt_builder.

Pure unit tests against hand-built stand-ins for Edge/FewShotExample — no DB
needed, mirroring tests/llm/test_prompt_builder.py's style.
"""

import json
from types import SimpleNamespace

from apps.llm.prompt_builder import build_few_shot_messages, serialize_example


def _fake_edge(
    source_text: str = "Wolves reduce deer.", **edge_data
) -> SimpleNamespace:
    subject = SimpleNamespace(name="Wolves", data={"entity_type": "biotic"})
    obj = SimpleNamespace(name="Deer", data={"entity_type": "biotic"})
    data = {"predicate": "reduces", "original_sentence": source_text, **edge_data}
    return SimpleNamespace(subject=subject, object=obj, data=data)


def _fake_example(edge) -> SimpleNamespace:
    return SimpleNamespace(edge=edge)


class TestSerializeExample:
    def test_serialize_example_shape(self):
        edge = _fake_edge()

        result = serialize_example(edge)

        assert set(result.keys()) == {"subject", "object", "edge", "source_text"}
        assert result["subject"]["name"] == "Wolves"
        assert result["subject"]["entity_type"] == "biotic"
        assert result["object"]["name"] == "Deer"
        assert result["edge"]["predicate"] == "reduces"
        assert result["source_text"] == "Wolves reduce deer."


class TestBuildFewShotMessages:
    def test_build_few_shot_messages_count(self):
        examples = [_fake_example(_fake_edge(f"Sentence {i}.")) for i in range(3)]

        messages = build_few_shot_messages(examples)

        assert len(messages) == 6

    def test_build_few_shot_messages_alternating_roles(self):
        examples = [_fake_example(_fake_edge(f"Sentence {i}.")) for i in range(3)]

        messages = build_few_shot_messages(examples)

        roles = [m["role"] for m in messages]
        assert roles == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ]

    def test_build_few_shot_messages_content(self):
        edge = _fake_edge("Nitrogen increases plant growth.")
        messages = build_few_shot_messages([_fake_example(edge)])

        assert messages[0]["content"] == (
            "Extract claims from: Nitrogen increases plant growth."
        )
        assert json.loads(messages[1]["content"]) == serialize_example(edge)
