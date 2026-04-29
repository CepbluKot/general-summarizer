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
    # context=32000: output_reserve=min(6400,32000)=6400, data=32000-6400-3000=22600
    assert cfg.token_budget == 22600
    assert cfg.max_output_tokens == 6400
    assert cfg.max_reduce_rounds == 20
