"""M11 (decision 0014) -- tests for smolcode.web.keys.extract_keys.

Covers:
  * Whitelist recognition of *_API_KEY, *_APIKEY, HF_TOKEN
  * Non-key env var names dropped silently (e.g. OPENCODE_HOST, PATH)
  * Empty / None / non-string values dropped
  * Per-value length cap (4096 chars)
  * Total-entry cap (16)
  * Multi-line / CR stripping (first line only)
  * Function returns a new dict (no input mutation)
  * Non-dict input returns {}
  * Order is irrelevant -- dict invariants apply
"""

from __future__ import annotations

from smolcode.web.keys import extract_keys


class TestExtractKeysWhitelist:
    def test_openai_key_kept(self):
        out = extract_keys({"OPENAI_API_KEY": "sk-abcdef1234567890XYZ"})
        assert out == {"OPENAI_API_KEY": "sk-abcdef1234567890XYZ"}

    def test_minimax_key_kept(self):
        out = extract_keys({"MINIMAX_API_KEY": "k12345"})
        assert out == {"MINIMAX_API_KEY": "k12345"}

    def test_anthropic_key_kept(self):
        out = extract_keys({"ANTHROPIC_API_KEY": "sk-ant-abc1234xyz"})
        assert out == {"ANTHROPIC_API_KEY": "sk-ant-abc1234xyz"}

    def test_opencode_apikey_kept(self):
        # Decision 0001: OPENCODE_GO_APIKEY uses _APIKEY suffix.
        out = extract_keys({"OPENCODE_GO_APIKEY": "k12345"})
        assert out == {"OPENCODE_GO_APIKEY": "k12345"}

    def test_hf_token_kept(self):
        out = extract_keys({"HF_TOKEN": "hf_abcdef12345"})
        assert out == {"HF_TOKEN": "hf_abcdef12345"}

    def test_unknown_env_var_dropped_silently(self):
        out = extract_keys({"PATH": "/usr/bin", "OPENCODE_HOST": "https://x"})
        assert out == {}

    def test_mixed_known_and_unknown_keeps_only_known(self):
        out = extract_keys(
            {
                "OPENAI_API_KEY": "sk-abc12345",
                "PATH": "/usr/bin",
                "OPENCODE_HOST": "https://x",
                "HF_TOKEN": "hf_abcdef",
            }
        )
        assert out == {
            "OPENAI_API_KEY": "sk-abc12345",
            "HF_TOKEN": "hf_abcdef",
        }


class TestExtractKeysValueFiltering:
    def test_none_value_dropped(self):
        out = extract_keys({"OPENAI_API_KEY": None})
        assert out == {}

    def test_empty_string_dropped(self):
        out = extract_keys({"OPENAI_API_KEY": ""})
        assert out == {}

    def test_whitespace_only_value_dropped(self):
        # Trimming: a value of "   " has no non-whitespace content.
        out = extract_keys({"OPENAI_API_KEY": "   \n  \r"})
        assert out == {}

    def test_non_string_value_dropped(self):
        out = extract_keys({"OPENAI_API_KEY": 12345})
        assert out == {}

    def test_multiline_value_truncated_to_first_line(self):
        out = extract_keys({"OPENAI_API_KEY": "real-key\nINJECTED_LINE"})
        # Trailing CR stripped, then split on \n first line wins.
        assert out == {"OPENAI_API_KEY": "real-key"}

    def test_carriage_return_stripped(self):
        out = extract_keys({"OPENAI_API_KEY": "real-key\r"})
        assert out == {"OPENAI_API_KEY": "real-key"}


class TestExtractKeysCaps:
    def test_total_entry_cap(self):
        # 16 entries should pass; the 17th must be dropped.
        body = {f"VENDOR_{i}_API_KEY": f"k{i}" for i in range(20)}
        out = extract_keys(body)
        assert len(out) == 16

    def test_total_entry_cap_excludes_unknown_keys(self):
        # Unknown keys dropped BEFORE the cap is applied; known keys
        # then count toward it.
        body = {
            "PATH": "/x",
            "VENDOR_0_API_KEY": "k0",
            "VENDOR_1_API_KEY": "k1",
        }
        out = extract_keys(body)
        # PATH dropped; both known keys pass (under cap).
        assert len(out) == 2

    def test_value_length_cap_truncates(self):
        long_value = "a" * 5000
        out = extract_keys({"OPENAI_API_KEY": long_value})
        assert out == {"OPENAI_API_KEY": "a" * 4096}


class TestExtractKeysNonDict:
    def test_string_input_returns_empty(self):
        assert extract_keys("not a dict") == {}  # type: ignore[arg-type]

    def test_none_input_returns_empty(self):
        assert extract_keys(None) == {}  # type: ignore[arg-type]

    def test_list_input_returns_empty(self):
        assert extract_keys([("OPENAI_API_KEY", "x")]) == {}  # type: ignore[arg-type]


class TestExtractKeysSafety:
    def test_does_not_mutate_input(self):
        body = {"OPENAI_API_KEY": "real-key\nINJECTED", "PATH": "/x"}
        snapshot = dict(body)
        extract_keys(body)
        assert body == snapshot

    def test_non_string_key_dropped(self):
        # A numeric key would not survive JSON serialisation anyway,
        # but it must not crash either.
        out = extract_keys({42: "x"})  # type: ignore[dict-item]
        assert out == {}

    def test_empty_string_key_dropped(self):
        out = extract_keys({"": "x"})
        assert out == {}
