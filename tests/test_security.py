import pytest
from src.core.security import SecurityManager

def test_security_manager_encryption_decryption():
    sec = SecurityManager()
    plain = "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz"
    encrypted = sec.encrypt_credential(plain)
    assert encrypted != plain
    assert encrypted.startswith("ENC:")
    decrypted = sec.decrypt_credential(encrypted)
    assert decrypted == plain

def test_security_manager_input_sanitization():
    sec = SecurityManager()
    malicious = "<script>alert('hack')</script>Key Technical Insights: Hello world"
    clean = sec.sanitize_input_payload(malicious)
    assert "<script>" not in clean
    assert "Key Technical Insights:" not in clean
    assert "Hello world" in clean

def test_security_manager_output_redaction():
    sec = SecurityManager()
    output_text = "Here is an OpenAI key sk-1234567890abcdefghijklmnopqrstuvwxyz and Gemini key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P"
    redacted = sec.sanitize_output_payload(output_text)
    assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "AIzaSy" not in redacted
    assert "[REDACTED_GEMINI_KEY]" in redacted
