import pytest
from src.core.models import TrendItem, VerifiedNews, PostDraft, PersonaProfile, SystemLog, SystemSetting

def test_models_creation():
    item = TrendItem(title="Test AI News", url="https://example.com", source="RSS", summary="Summary text")
    assert item.title == "Test AI News"
    
    setting = SystemSetting(key_name="search_topics", value="Generative AI, Local LLMs")
    assert "Local LLMs" in setting.value
