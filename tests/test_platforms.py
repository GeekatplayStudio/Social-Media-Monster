"""Per-channel credential storage, connection testing and publishing gates."""
import json
import pytest
from sqlmodel import Session, select, delete

from src.core.db import init_db, engine
from src.core.models import SystemSetting, PostDraft, VerifiedNews
from src.core.platforms import PlatformCredentialStore, PLATFORM_SPECS, PLATFORM_ORDER, SETTING_KEY
from src.core import channel_clients
from src.core.channel_clients import ChannelResult, _oauth1_header, _http_reason
from src.agents.publisher_agent import PublisherAgent


@pytest.fixture(autouse=True)
def clean_connections():
    # Drafts are cleared too: publisher assertions count sends, and drafts left over from
    # the dev database or an earlier test would be picked up by the same run.
    init_db()
    with Session(engine) as session:
        row = session.exec(select(SystemSetting).where(SystemSetting.key_name == SETTING_KEY)).first()
        if row:
            session.delete(row)
        session.exec(delete(PostDraft))
        session.exec(delete(VerifiedNews))
        session.commit()
    yield


@pytest.fixture
def store():
    return PlatformCredentialStore()


# --------------------------------------------------------------------- spec integrity

def test_every_ordered_platform_has_a_spec():
    assert set(PLATFORM_ORDER) == set(PLATFORM_SPECS)


def test_every_spec_is_complete():
    for name, spec in PLATFORM_SPECS.items():
        assert spec["label"] and spec["portal"].startswith("http"), name
        assert spec["fields"], f"{name} declares no credential fields"
        for f in spec["fields"]:
            assert f["name"] and f["label"], name


def test_every_postable_platform_has_a_transport():
    for name, spec in PLATFORM_SPECS.items():
        assert name in channel_clients.CHANNELS, f"{name} has no client"
        assert callable(channel_clients.CHANNELS[name]["test"])
        assert callable(channel_clients.CHANNELS[name]["publish"])


# --------------------------------------------------------------------- storage

def test_secrets_are_encrypted_at_rest_and_never_returned(store):
    secret = "123456:SUPER-SECRET-BOT-TOKEN"
    summary = store.save_credentials("telegram", {"bot_token": secret, "chat_id": "@mychan"})

    # Nothing secret comes back to the caller.
    for f in summary["fields"]:
        if f["secret"]:
            assert f["value"] == ""
            assert f["is_set"] is True

    with Session(engine) as session:
        raw = session.exec(select(SystemSetting).where(SystemSetting.key_name == SETTING_KEY)).first().value
    assert secret not in raw, "credential was written to SQLite in clear text"
    assert "ENC:" in raw

    # But the publisher can still read it.
    assert store.get_credentials("telegram")["bot_token"] == secret


def test_blank_secret_preserves_the_stored_value(store):
    store.save_credentials("telegram", {"bot_token": "keep-me", "chat_id": "@one"})
    store.save_credentials("telegram", {"bot_token": "", "chat_id": "@two"})

    creds = store.get_credentials("telegram")
    assert creds["bot_token"] == "keep-me", "blank submission wiped the stored secret"
    assert creds["chat_id"] == "@two", "non-secret field should update"


def test_non_secret_fields_round_trip_for_the_form(store):
    summary = store.save_credentials("wordpress", {
        "site_url": "https://blog.example.com", "username": "admin",
        "application_password": "abcd efgh", "post_status": "draft",
    })
    values = {f["name"]: f["value"] for f in summary["fields"]}
    assert values["site_url"] == "https://blog.example.com"
    assert values["application_password"] == ""


def test_configured_requires_all_required_fields(store):
    store.save_credentials("telegram", {"bot_token": "abc"})
    assert store.is_configured("telegram") is False
    store.save_credentials("telegram", {"chat_id": "@chan"})
    assert store.is_configured("telegram") is True


def test_placeholder_values_do_not_count_as_configured(store):
    store.save_credentials("telegram", {"bot_token": "YOUR_TELEGRAM_BOT_TOKEN", "chat_id": "@chan"})
    assert store.is_configured("telegram") is False


def test_all_optional_platform_is_not_configured_when_empty(store):
    """YouTube's fields are all optional; empty must not read as connected."""
    assert store.is_configured("youtube") is False
    store.save_credentials("youtube", {"api_key": "AIza-test", "channel_id": "UC123"})
    assert store.is_configured("youtube") is True


def test_saving_resets_a_previous_test_result(store):
    store.save_credentials("telegram", {"bot_token": "a", "chat_id": "@c"})
    store.record_test_result("telegram", True, "ok", "@bot")
    assert store.describe("telegram")["status"] == "connected"
    store.save_credentials("telegram", {"bot_token": "different"})
    assert store.describe("telegram")["status"] == "untested", "stale verification survived a credential change"


def test_disconnect_clears_everything(store):
    store.save_credentials("telegram", {"bot_token": "a", "chat_id": "@c"})
    store.disconnect("telegram")
    assert store.is_configured("telegram") is False
    assert store.get_credentials("telegram")["bot_token"] == ""


def test_unknown_platform_raises(store):
    with pytest.raises(KeyError):
        store.save_credentials("myspace", {})


# --------------------------------------------------------------------- transports

def test_missing_fields_are_reported_before_any_network_call(monkeypatch):
    called = []
    monkeypatch.setattr(channel_clients, "_request", lambda *a, **k: called.append(1))
    result = channel_clients.telegram_publish({"bot_token": ""}, {"headline": "h", "content": "c"})
    assert result.ok is False
    assert "Missing required field" in result.message
    assert not called, "a request was made despite missing credentials"


def test_http_reasons_are_actionable():
    assert "Authentication failed" in _http_reason(401, {"description": "Unauthorized"})
    assert "not permitted" in _http_reason(403, {})
    assert "Rate limited" in _http_reason(429, {})


def test_oauth1_header_is_well_formed():
    header = _oauth1_header("POST", "https://api.twitter.com/2/tweets",
                            "ckey", "csecret", "atoken", "asecret")
    assert header.startswith("OAuth ")
    for part in ("oauth_consumer_key", "oauth_nonce", "oauth_signature",
                 "oauth_signature_method", "oauth_timestamp", "oauth_token", "oauth_version"):
        assert part in header
    assert 'oauth_signature_method="HMAC-SHA1"' in header


def test_oauth1_nonce_differs_between_calls():
    a = _oauth1_header("GET", "https://x.test/a", "k", "s", "t", "ts")
    b = _oauth1_header("GET", "https://x.test/a", "k", "s", "t", "ts")
    assert a != b


def test_youtube_publish_is_honest_about_having_no_api():
    result = channel_clients.publish_to_channel("youtube", {}, {"headline": "h", "content": "c"})
    assert result.ok is False
    assert "no public API" in result.message


def test_reddit_reports_errors_hidden_in_a_200_response(monkeypatch):
    monkeypatch.setattr(channel_clients, "_reddit_token", lambda creds: ("tok", "ua", None))
    monkeypatch.setattr(channel_clients, "_request", lambda *a, **k: (
        200, {"json": {"errors": [["SUBREDDIT_NOTALLOWED", "you aren't allowed to post there"]]}}, None))
    result = channel_clients.reddit_publish(
        {"client_id": "a", "client_secret": "b", "username": "c", "password": "d", "subreddit": "r/test"},
        {"headline": "h", "content": "c"},
    )
    assert result.ok is False, "Reddit returns 200 with the failure in the body"
    assert "allowed to post" in result.message


def test_instagram_refuses_without_a_public_image_url():
    result = channel_clients.instagram_publish(
        {"account_id": "1", "access_token": "t"},
        {"headline": "h", "content": "c", "public_image_url": ""},
    )
    assert result.ok is False
    assert "public URL" in result.message


def test_unknown_channel_is_rejected():
    assert channel_clients.publish_to_channel("myspace", {}, {}).ok is False
    assert channel_clients.test_channel("myspace", {}).ok is False


# --------------------------------------------------------------------- publisher gates

def _approved_draft(platform):
    with Session(engine) as session:
        news = VerifiedNews(trend_id=1, headline="H", verified_facts="F", key_takeaways="K")
        session.add(news)
        session.commit()
        # Drafts reach the publisher with their master asset already attached: the
        # pipeline renders one image/video per story before anything is dispatched.
        draft = PostDraft(verified_news_id=news.id, platform=platform, persona_key="tech_visionary",
                          headline="Test headline", content="A body of text long enough to publish.",
                          status="approved", image_path="master_story_1.png",
                          media_path="master_story_1.png")
        session.add(draft)
        session.commit()
        return draft.id


def test_publisher_skips_unconfigured_channel(store, monkeypatch):
    _approved_draft("telegram")
    sent = []
    monkeypatch.setattr("src.agents.publisher_agent.publish_to_channel",
                        lambda *a, **k: sent.append(1) or ChannelResult(True, "sent"))
    assert PublisherAgent().run() == 0
    assert not sent, "publisher contacted a channel with no credentials"


def test_publisher_skips_disabled_channel(store, monkeypatch):
    _approved_draft("telegram")
    store.save_credentials("telegram", {"bot_token": "a", "chat_id": "@c"})
    store.set_enabled("telegram", False)
    sent = []
    monkeypatch.setattr("src.agents.publisher_agent.publish_to_channel",
                        lambda *a, **k: sent.append(1) or ChannelResult(True, "sent"))
    assert PublisherAgent().run() == 0
    assert not sent


def test_publisher_sends_when_configured_and_enabled(store, monkeypatch):
    draft_id = _approved_draft("telegram")
    store.save_credentials("telegram", {"bot_token": "a", "chat_id": "@c"})

    captured = {}

    def fake_publish(platform, creds, post):
        captured.update({"platform": platform, "creds": creds, "post": post})
        return ChannelResult(True, "sent", external_id="42")

    monkeypatch.setattr("src.agents.publisher_agent.publish_to_channel", fake_publish)
    assert PublisherAgent().run() == 1

    assert captured["platform"] == "telegram"
    assert captured["creds"]["bot_token"] == "a", "decrypted credentials must reach the transport"
    assert captured["post"]["content"]

    with Session(engine) as session:
        draft = session.get(PostDraft, draft_id)
        assert draft.status == "published"
        assert draft.external_post_id == "42"


def test_failed_publish_leaves_the_draft_approved(store, monkeypatch):
    draft_id = _approved_draft("telegram")
    store.save_credentials("telegram", {"bot_token": "a", "chat_id": "@c"})
    monkeypatch.setattr("src.agents.publisher_agent.publish_to_channel",
                        lambda *a, **k: ChannelResult(False, "channel rejected it"))
    assert PublisherAgent().run() == 0
    with Session(engine) as session:
        assert session.get(PostDraft, draft_id).status == "approved", "a failed send must be retryable"


def test_publisher_never_posts_to_youtube(store, monkeypatch):
    _approved_draft("youtube")
    store.save_credentials("youtube", {"api_key": "k", "channel_id": "UC1"})
    sent = []
    monkeypatch.setattr("src.agents.publisher_agent.publish_to_channel",
                        lambda *a, **k: sent.append(1) or ChannelResult(True, "sent"))
    assert PublisherAgent().run() == 0
    assert not sent


def test_dry_run_does_not_publish(store, monkeypatch):
    draft_id = _approved_draft("telegram")
    store.save_credentials("telegram", {"bot_token": "a", "chat_id": "@c"})
    sent = []
    monkeypatch.setattr("src.agents.publisher_agent.publish_to_channel",
                        lambda *a, **k: sent.append(1) or ChannelResult(True, "sent"))
    PublisherAgent().run(dry_run=True)
    assert not sent
    with Session(engine) as session:
        assert session.get(PostDraft, draft_id).status == "approved"
