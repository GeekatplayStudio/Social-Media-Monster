import os
import json
import hmac
import hashlib
import time
from unittest.mock import patch, MagicMock
import pytest

from src.core.autoagent_publisher import AutoAgentPublisher
from src.core.platforms import PlatformCredentialStore, PLATFORM_SPECS
from src.core.channel_clients import autoagent_test, autoagent_publish, CHANNELS


BASE_URL = "https://www.vladimirchopine.com/ai-news/api"
SECRET_KEY = "test_secret_key_123"


@pytest.fixture(autouse=True)
def clean_db():
    from src.core.db import init_db, engine
    from src.core.models import SystemSetting
    from src.core.platforms import SETTING_KEY
    from sqlmodel import Session, select
    init_db()
    with Session(engine) as session:
        row = session.exec(select(SystemSetting).where(SystemSetting.key_name == SETTING_KEY)).first()
        if row:
            session.delete(row)
        session.commit()
    yield


def test_code_block_formatting():
    publisher = AutoAgentPublisher(BASE_URL, SECRET_KEY)
    code = 'def test():\n    if a > b and c < d:\n        print("Hello & World")'
    formatted = publisher.format_code_block(code, language="python")

    assert formatted.startswith('<pre><code class="language-python">')
    assert formatted.endswith('</code></pre>')
    
    # Check inner code body escapes
    inner_code = formatted[len('<pre><code class="language-python">'):-len('</code></pre>')]
    assert '&gt;' in inner_code
    assert '&lt;' in inner_code
    assert '&amp;' in inner_code
    assert '>' not in inner_code
    assert '<' not in inner_code


def test_hmac_signature_calculation():
    publisher = AutoAgentPublisher(BASE_URL, SECRET_KEY)

    # Payload HMAC test
    payload = {"title": "Test Title", "content": "<p>Content</p>", "timestamp": 1715421234}
    json_bytes = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

    expected_hmac = hmac.new(SECRET_KEY.encode('utf-8'), json_bytes, hashlib.sha256).hexdigest()
    computed_hmac = publisher.compute_payload_signature(json_bytes)

    assert computed_hmac == expected_hmac

    # Upload HMAC test
    timestamp = "1715421234"
    filename = "test_image.png"
    upload_msg = f"{timestamp}:{filename}".encode('utf-8')
    expected_upload_hmac = hmac.new(SECRET_KEY.encode('utf-8'), upload_msg, hashlib.sha256).hexdigest()
    computed_upload_hmac = publisher.compute_upload_signature(timestamp, filename)

    assert computed_upload_hmac == expected_upload_hmac


@patch("urllib.request.urlopen")
def test_publish_article_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "status": "success",
        "message": "Post published securely!",
        "post_id": 42,
        "title": "Test Title"
    }).encode('utf-8')
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    publisher = AutoAgentPublisher(BASE_URL, SECRET_KEY)
    res = publisher.publish_article(title="Test Title", content="<p>Test Content</p>")

    assert res["status"] == "success"
    assert res["post_id"] == 42
    assert mock_urlopen.called


@patch("urllib.request.urlopen")
def test_upload_media_success(mock_urlopen, tmp_path):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "status": "success",
        "url": "https://www.vladimirchopine.com/ai-news/api/uploads/media_123.png",
        "filename": "media_123.png"
    }).encode('utf-8')
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    test_file = tmp_path / "diagram.png"
    test_file.write_bytes(b"dummy image bytes")

    publisher = AutoAgentPublisher(BASE_URL, SECRET_KEY)
    img_url = publisher.upload_media(str(test_file))

    assert img_url == "https://www.vladimirchopine.com/ai-news/api/uploads/media_123.png"


def test_platform_specs_registration():
    assert "autoagent" in PLATFORM_SPECS
    spec = PLATFORM_SPECS["autoagent"]
    assert spec["can_post"] is True
    field_names = [f["name"] for f in spec["fields"]]
    assert "base_url" in field_names
    assert "secret_key" in field_names


def test_channel_clients_registration():
    assert "autoagent" in CHANNELS
    assert CHANNELS["autoagent"]["test"] == autoagent_test
    assert CHANNELS["autoagent"]["publish"] == autoagent_publish


def test_autoagent_test_handler_reports_missing_fields():
    res = autoagent_test({})
    assert not res.ok
    assert "Missing required field" in res.message


# The handler now performs a real signed request, so the transport is stubbed: the suite
# must not depend on the live site being up, and a green result must mean the endpoint
# actually answered rather than that both fields were merely non-empty.
CREDS = {"base_url": BASE_URL, "secret_key": SECRET_KEY}


@patch("src.core.channel_clients._request")
def test_autoagent_test_accepts_an_authenticated_endpoint(mock_request):
    mock_request.return_value = (400, {"error": "unknown action"}, "bad request")
    res = autoagent_test(CREDS)
    assert res.ok, "a non-auth 4xx means the signature was accepted"
    assert BASE_URL in res.message


@patch("src.core.channel_clients._request")
def test_autoagent_test_rejects_a_bad_secret(mock_request):
    mock_request.return_value = (401, {"error": "bad signature"}, "unauthorized")
    res = autoagent_test(CREDS)
    assert not res.ok
    assert "shared secret" in res.message


@patch("src.core.channel_clients._request")
def test_autoagent_test_reports_a_wrong_url(mock_request):
    mock_request.return_value = (404, "", "not found")
    res = autoagent_test(CREDS)
    assert not res.ok
    assert "Base API URL" in res.message


@patch("src.core.channel_clients._request")
def test_autoagent_test_does_not_call_a_server_error_a_success(mock_request):
    mock_request.return_value = (500, {"error": "Server misconfigured: signing key unavailable"}, "server error")
    res = autoagent_test(CREDS)
    assert not res.ok, "a 500 is not proof of a working integration"
    assert "signing key unavailable" in res.message


@patch("src.core.channel_clients._request")
def test_autoagent_test_reports_an_unreachable_host(mock_request):
    mock_request.return_value = (0, None, "Could not reach the service (timed out).")
    res = autoagent_test(CREDS)
    assert not res.ok
    assert "Cannot reach" in res.message


@patch("src.core.autoagent_publisher.AutoAgentPublisher.publish_code_article")
def test_autoagent_publish_handler(mock_publish):
    mock_publish.return_value = {
        "status": "success",
        "message": "Post published securely!",
        "post_id": 99,
        "title": "Sample Article"
    }

    creds = {"base_url": BASE_URL, "secret_key": SECRET_KEY}
    post = {"headline": "Sample Article", "content": "Summary text", "image_path": ""}

    res = autoagent_publish(creds, post)
    assert res.ok
    assert res.external_id == "99"
    assert "Posted to Output Node" in res.message


def test_platform_credential_store_autoagent():
    store = PlatformCredentialStore()
    creds_input = {
        "base_url": BASE_URL,
        "secret_key": SECRET_KEY,
    }
    summary = store.save_credentials("autoagent", creds_input)
    assert summary["configured"] is True

    decrypted = store.get_credentials("autoagent")
    assert decrypted["base_url"] == BASE_URL
    assert decrypted["secret_key"] == SECRET_KEY


# --------------------------------------------------------------- published HTML quality

def test_markdown_body_is_rendered_not_escaped():
    """
    The body was HTML-escaped wholesale, so a post published with a literal
    "# Heading" and "**bold**" visible on the page.
    """
    html_out = AutoAgentPublisher.markdown_to_html("**Nvidia warns of tight supply.**")
    assert "<strong>Nvidia warns of tight supply.</strong>" in html_out
    assert "**" not in html_out


def test_duplicate_title_heading_is_dropped():
    title = "Nvidia signals a prolonged shortage"
    out = AutoAgentPublisher.markdown_to_html(f"# {title}\n\nSupply stays tight.", drop_title=title)
    assert title not in out, "the site stores the title separately; repeating it reads as duplication"
    assert "Supply stays tight." in out


def test_list_markers_become_real_list_items():
    out = AutoAgentPublisher.markdown_to_html("- Memory is the bottleneck\n- Budget cards feel it first")
    assert out.startswith("<ul>")
    assert "<li>Memory is the bottleneck</li>" in out
    assert "- Memory" not in out, "the bullet marker must not survive into the item text"

    ordered = AutoAgentPublisher.markdown_to_html("1. First\n2. Second")
    assert ordered.startswith("<ol>")


def test_video_is_embedded_as_a_player_not_an_image():
    """A generated .mp4 was emitted inside <img>, which cannot play."""
    assert AutoAgentPublisher.media_embed("api/uploads/clip.mp4").startswith("<video")
    assert "controls" in AutoAgentPublisher.media_embed("api/uploads/clip.mp4")
    assert AutoAgentPublisher.media_embed("api/uploads/art.png").startswith("<img")


def test_author_markup_cannot_be_injected():
    out = AutoAgentPublisher.markdown_to_html('<script>alert(1)</script> and **bold**')
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<strong>bold</strong>" in out
