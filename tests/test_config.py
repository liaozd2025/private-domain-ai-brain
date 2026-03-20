"""配置默认值测试"""

from src.config import LLMProvider, Settings


def test_settings_defaults_use_minimax_primary_model(monkeypatch):
    """默认主模型应切到 MiniMax M2.5。"""
    for key in [
        "PRIMARY_LLM",
        "PRIMARY_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.primary_llm == LLMProvider.OPENAI
    assert settings.primary_model == "Pro/MiniMaxAI/MiniMax-M2.5"
