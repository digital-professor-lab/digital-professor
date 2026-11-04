"""Reviewer ask: JSON extraction from model responses."""
import json

import pytest

from course_context_pipeline.llm import extract_json_text


def test_plain_object():
    assert json.loads(extract_json_text('{"a": 1}')) == {"a": 1}


def test_json_code_fence():
    t = 'Here you go:\n```json\n{"a": 2}\n```\nthanks'
    assert json.loads(extract_json_text(t)) == {"a": 2}


def test_think_preamble_stripped():
    t = '<think>let me reason about this</think>\n{"a": 3}'
    assert json.loads(extract_json_text(t)) == {"a": 3}


def test_chatty_text_around_object():
    t = 'Sure! Here it is: {"a": {"b": 4}} — hope that helps'
    assert json.loads(extract_json_text(t)) == {"a": {"b": 4}}


def test_braces_inside_strings_are_ignored():
    t = '{"s": "has } and { braces"}'
    assert json.loads(extract_json_text(t)) == {"s": "has } and { braces"}


def test_no_object_raises():
    with pytest.raises(ValueError):
        extract_json_text("there is no JSON here")
