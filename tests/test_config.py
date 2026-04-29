from summarizer.config import PipelineConfig

def test_config_defaults():
    cfg = PipelineConfig(
        input_path="data.json",
        format="json",
        schema_hint="",
        user_prompt="find problems",
        output_schema={"type": "object"},
        map_prompt_template="map {user_prompt}",
        reduce_prompt_template="reduce {user_prompt}",
        compress_prompt_template="compress",
        model="test-model",
        api_base="http://localhost:8000",
        api_key="sk-test",
        output_path=None,
    )
    assert cfg.map_concurrency == 5
    assert cfg.context_tokens == 32000
    assert cfg.token_budget == 32000 // 2   # auto-derived from context_tokens
    assert cfg.compression_target_pct == 30
    assert cfg.max_reduce_rounds == 20
