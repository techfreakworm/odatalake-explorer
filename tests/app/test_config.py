"""Settings come only from env (contract I4 plus ASK_TIMEOUT_S, DEBUG, GIT_SHA, LOG_LEVEL)."""

import pytest

from app.config import ConfigError, Settings


def test_defaults_follow_appendix_c():
    s = Settings.from_env({})
    assert s.providers == ()
    assert str(s.index_dir) == "data/index"
    assert s.embed_model == "BAAI/bge-small-en-v1.5"
    assert s.retrieval_mode == "hybrid"
    assert s.rerank == "off"
    assert s.gate_signal == "dense"
    assert s.abstain_threshold == 0.69
    assert s.source_url_style == "branch"
    assert s.blog is False
    assert s.onnx_threads == 1
    assert s.max_tokens == 600
    assert s.llm_timeout_s == 25
    assert s.ask_timeout_s == 30
    assert s.queue_wait_s == 20
    assert s.max_concurrency == 8
    assert s.rate_limit_per_min == 120
    assert s.rate_limit_burst == 200
    assert s.daily_token_budget == 5_000_000
    assert s.refresh_interval_min == 0
    assert s.log_level == "INFO"
    assert s.debug is False
    assert s.git_sha == "unknown"


def test_generated_canary_is_16_hex_and_not_in_repr():
    s = Settings.from_env({})
    assert len(s.canary) == 16
    int(s.canary, 16)
    assert s.canary not in repr(s)


def test_canary_from_env():
    s = Settings.from_env({"CANARY": "00112233aabbccdd"})
    assert s.canary == "00112233aabbccdd"


def test_short_canary_is_replaced():
    # a short canary could appear in normal text and block real answers
    s = Settings.from_env({"CANARY": "abc"})
    assert len(s.canary) == 16 and s.canary != "abc"


def test_provider_chain_in_order_and_incomplete_ones_skipped():
    env = {
        "LLM_BASE_URL": "http://primary/v1", "LLM_API_KEY": "k1", "LLM_MODEL": "m1",
        "LLM_REASONING_EFFORT": "none",
        "LLM_FALLBACK_BASE_URL": "http://fallback/v1", "LLM_FALLBACK_MODEL": "m2",  # no key: skipped
        "LLM_FALLBACK2_BASE_URL": "http://fallback2/v1", "LLM_FALLBACK2_API_KEY": "k3", "LLM_FALLBACK2_MODEL": "m3",
    }
    s = Settings.from_env(env)
    assert [p.name for p in s.providers] == ["primary", "fallback2"]
    assert s.providers[0].reasoning_effort == "none"
    assert s.providers[1].reasoning_effort is None
    assert any("fallback" in w and "LLM_FALLBACK_API_KEY" in w for w in s.warnings)
    # keys never show up in a repr (and so never in a log line that prints settings)
    assert "k1" not in repr(s) and "k3" not in repr(s)


def test_empty_strings_mean_unset():
    s = Settings.from_env({"LLM_REASONING_EFFORT": "", "RETRIEVAL_MODE": "", "ABSTAIN_THRESHOLD": "",
                           "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": ""})
    assert s.retrieval_mode == "hybrid"
    assert s.abstain_threshold == 0.69
    assert s.providers == ()
    assert s.warnings == ()


def test_overrides():
    s = Settings.from_env({
        "INDEX_DIR": "/srv/index", "RETRIEVAL_MODE": "bm25", "RERANK": "tinybert", "GATE_SIGNAL": "off",
        "ABSTAIN_THRESHOLD": "0.71", "SOURCE_URL_STYLE": "sha", "BLOG": "on", "ONNX_THREADS": "2",
        "MAX_TOKENS": "400", "LLM_TIMEOUT_S": "12.5", "ASK_TIMEOUT_S": "300", "QUEUE_WAIT_S": "5",
        "MAX_CONCURRENCY": "3", "RATE_LIMIT_PER_MIN": "60", "RATE_LIMIT_BURST": "500",
        "DAILY_TOKEN_BUDGET": "1000", "REFRESH_INTERVAL_MIN": "10", "LOG_LEVEL": "debug", "DEBUG": "1",
        "GIT_SHA": "abc1234", "PUBLIC_BASE_URL": "https://ask.example.com",
    })
    assert str(s.index_dir) == "/srv/index"
    assert (s.retrieval_mode, s.rerank, s.gate_signal, s.source_url_style) == ("bm25", "tinybert", "off", "sha")
    assert s.blog is True and s.debug is True
    assert s.abstain_threshold == 0.71 and s.llm_timeout_s == 12.5 and s.ask_timeout_s == 300
    assert (s.onnx_threads, s.max_tokens, s.max_concurrency) == (2, 400, 3)
    assert (s.rate_limit_per_min, s.rate_limit_burst, s.daily_token_budget) == (60, 500, 1000)
    assert s.refresh_interval_min == 10 and s.log_level == "DEBUG" and s.git_sha == "abc1234"
    assert s.public_base_url == "https://ask.example.com"


@pytest.mark.parametrize("key,value", [
    ("RETRIEVAL_MODE", "dense"), ("RERANK", "minilm"), ("GATE_SIGNAL", "rerank"), ("SOURCE_URL_STYLE", "tag"),
    ("BLOG", "maybe"), ("MAX_TOKENS", "lots"), ("MAX_CONCURRENCY", "0"), ("ABSTAIN_THRESHOLD", "high"),
])
def test_invalid_values_fail_fast(key, value):
    with pytest.raises(ConfigError) as e:
        Settings.from_env({key: value})
    assert key in str(e.value)


def test_non_standard_canary_is_kept_but_warned_about_without_its_value():
    s = Settings.from_env({"CANARY": "my-own-canary-value-xyz"})
    assert s.canary == "my-own-canary-value-xyz"
    assert any("CANARY" in w for w in s.warnings)
    assert all("my-own-canary-value-xyz" not in w for w in s.warnings)
    assert Settings.from_env({"CANARY": "00112233aabbccdd"}).warnings == ()
