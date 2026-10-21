"""Oversized system prompts must not go on the CLI command line (128 KiB per-argument cap)."""
from services.claude_code_chat import _MAX_SYSTEM_ARG_BYTES, _fit_system


def test_small_system_prompt_stays_a_system_prompt():
    assert _fit_system("You are helpful.", "Hi") == ("You are helpful.", "Hi")


def test_large_system_prompt_moves_into_the_message():
    system = "context " * (_MAX_SYSTEM_ARG_BYTES // 4)
    new_system, new_prompt = _fit_system(system, "What do these papers say?")
    assert len(new_system.encode()) < 1000
    assert new_prompt.startswith("<instructions>\n" + system)
    assert new_prompt.endswith("</instructions>\n\nWhat do these papers say?")


def test_limit_counts_bytes_not_characters():
    system = "ä" * (_MAX_SYSTEM_ARG_BYTES // 2 + 10)  # under the limit in chars, over it in UTF-8 bytes
    assert _fit_system(system, "q")[0] != system
