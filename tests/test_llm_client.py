import pytest
from src.core.llm_client import LLMClient

def test_llm_client_fallback_and_clean_prompt():
    client = LLMClient()
    result = client.generate("Original Text:\nKey Technical Insights:\nTest LLM prompt", system_prompt="You are an editor.")
    assert isinstance(result, str)
    assert not result.startswith("Original Text:\nKey Technical Insights:")
