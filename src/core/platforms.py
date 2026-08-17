"""
Per-channel connection credentials.

One declarative spec drives everything: the dashboard form, the encrypted store, the
connection test and the publisher. Adding a channel means adding a spec entry, not
touching four files.

Secrets are encrypted with SecurityManager before they touch SQLite and are never sent
back to the browser - the API reports only whether a field is populated.
"""
import json
from datetime import datetime
from sqlmodel import Session, select

from src.core.db import engine, log_event
from src.core.models import SystemSetting
from src.core.security import SecurityManager

SETTING_KEY = "platform_connections"


def field(name, label, kind="text", secret=False, required=True, placeholder="", help_text=""):
    return {
        "name": name,
        "label": label,
        "kind": kind,              # text | password | textarea | url
        "secret": secret,          # encrypted at rest, never returned to the client
        "required": required,
        "placeholder": placeholder,
        "help": help_text,
    }


# ---------------------------------------------------------------------------- specs
PLATFORM_SPECS = {
    "twitter": {
        "label": "X (Twitter)",
        "icon": "𝕏",
        "can_post": True,
        "auth": "OAuth 1.0a user context",
        "portal": "https://developer.x.com/en/portal/dashboard",
        "setup": "Create a project + app, enable Read and Write permissions, then generate "
                 "Access Token and Secret for YOUR account (not the app owner's).",
        "fields": [
            field("api_key", "API Key (Consumer Key)", "password", secret=True, placeholder="25 chars"),
            field("api_secret", "API Key Secret", "password", secret=True, placeholder="50 chars"),
            field("access_token", "Access Token", "password", secret=True, placeholder="user-context token"),
            field("access_token_secret", "Access Token Secret", "password", secret=True),
        ],
    },
    "linkedin": {
        "label": "LinkedIn",
        "icon": "in",
        "can_post": True,
        "auth": "OAuth 2.0 bearer token",
        "portal": "https://developer.linkedin.com/",
        "setup": "Request the 'Share on LinkedIn' (w_member_social) product, run the OAuth "
                 "flow, then paste the access token. Author URN looks like urn:li:person:XXXX.",
        "fields": [
            field("access_token", "OAuth 2.0 Access Token", "password", secret=True, placeholder="AQV..."),
            field("author_urn", "Author URN", "text", placeholder="urn:li:person:abc123",
                  help_text="Use urn:li:organization:12345678 to post as a company page."),
        ],
    },
    "reddit": {
        "label": "Reddit",
        "icon": "r/",
        "can_post": True,
        "auth": "OAuth 2.0 password grant (script app)",
        "portal": "https://www.reddit.com/prefs/apps",
        "setup": "Create an app of type 'script'. The client id sits under the app name; "
                 "username/password are the account that will post.",
        "fields": [
            field("client_id", "Client ID", "password", secret=True),
            field("client_secret", "Client Secret", "password", secret=True),
            field("username", "Reddit Username", "text", placeholder="your_account"),
            field("password", "Reddit Password", "password", secret=True),
            field("subreddit", "Target Subreddit", "text", placeholder="r/LocalLLaMA",
                  help_text="Where posts are submitted. Respect each subreddit's self-promotion rules."),
            field("user_agent", "User Agent", "text", required=False,
                  placeholder="SocialMediaMonster/1.0 by u/yourname"),
        ],
    },
    "telegram": {
        "label": "Telegram",
        "icon": "✈",
        "can_post": True,
        "auth": "Bot token",
        "portal": "https://core.telegram.org/bots#botfather",
        "setup": "Talk to @BotFather to create a bot, then add the bot to your channel as an "
                 "administrator with permission to post.",
        "fields": [
            field("bot_token", "Bot Token", "password", secret=True, placeholder="123456:ABC-DEF..."),
            field("chat_id", "Channel / Chat ID", "text", placeholder="@YourChannel or -1001234567890"),
        ],
    },
    "discord": {
        "label": "Discord",
        "icon": "◈",
        "can_post": True,
        "auth": "Incoming webhook",
        "portal": "https://discord.com/developers/applications",
        "setup": "In your server: Channel Settings > Integrations > Webhooks > New Webhook, "
                 "then copy the webhook URL. No bot token required.",
        "fields": [
            field("webhook_url", "Webhook URL", "password", secret=True,
                  placeholder="https://discord.com/api/webhooks/..."),
            field("username_override", "Post As (display name)", "text", required=False,
                  placeholder="SocialMediaMonster"),
        ],
    },
    "wordpress": {
        "label": "WordPress Blog",
        "icon": "W",
        "can_post": True,
        "auth": "Application password (HTTP Basic)",
        "portal": "https://wordpress.org/documentation/article/application-passwords/",
        "setup": "In WP Admin: Users > Profile > Application Passwords. Use the generated "
                 "password here, not your login password.",
        "fields": [
            field("site_url", "Site URL", "url", placeholder="https://yourblog.com"),
            field("username", "WordPress Username", "text"),
            field("application_password", "Application Password", "password", secret=True,
                  placeholder="xxxx xxxx xxxx xxxx"),
            field("post_status", "Publish As", "text", required=False, placeholder="draft or publish",
                  help_text="Defaults to 'draft' so nothing goes live unreviewed."),
        ],
    },
    "facebook": {
        "label": "Facebook Page",
        "icon": "f",
        "can_post": True,
        "auth": "Graph API page access token",
        "portal": "https://developers.facebook.com/apps/",
        "setup": "Create an app, add the Pages API, then exchange for a long-lived PAGE "
                 "access token with pages_manage_posts permission.",
        "fields": [
            field("page_id", "Page ID", "text"),
            field("page_access_token", "Page Access Token", "password", secret=True),
        ],
    },
    "instagram": {
        "label": "Instagram Business",
        "icon": "◎",
        "can_post": True,
        "auth": "Graph API (Instagram Business account)",
        "portal": "https://developers.facebook.com/docs/instagram-api/",
        "setup": "Requires an Instagram Business/Creator account linked to a Facebook Page. "
                 "Instagram will not accept a post without an image reachable at a PUBLIC URL.",
        "fields": [
            field("account_id", "Instagram Business Account ID", "text"),
            field("access_token", "Access Token", "password", secret=True),
            field("public_image_base_url", "Public Image Base URL", "url", required=False,
                  placeholder="https://cdn.yoursite.com/images",
                  help_text="Instagram fetches the image itself, so localhost paths cannot work."),
        ],
    },
    "youtube": {
        "label": "YouTube Community",
        "icon": "▶",
        "can_post": False,
        "auth": "OAuth 2.0 (read-only)",
        "portal": "https://console.cloud.google.com/apis/credentials",
        "setup": "Google exposes no public API for creating Community posts. Credentials here "
                 "are used to verify the channel only; posts must be published manually.",
        "fields": [
            field("api_key", "YouTube Data API Key", "password", secret=True, required=False),
            field("channel_id", "Channel ID", "text", required=False, placeholder="UCxxxxxxxx"),
        ],
    },
    "autoagent": {
        "label": "The Output Node (AutoAgent)",
        "icon": "🤖",
        "can_post": True,
        "auth": "HMAC-SHA256 REST API",
        "portal": "https://www.vladimirchopine.com/ai-news/api",
        "setup": "Configure the base API URL and shared secret key matching your server's api/config.php.",
        "fields": [
            field("base_url", "Base API URL", "url", placeholder="https://www.vladimirchopine.com/ai-news/api"),
            field("secret_key", "Secret Key", "password", secret=True, placeholder="shared_hmac_secret_key"),
        ],
    },
}

PLATFORM_ORDER = [
    "twitter", "linkedin", "reddit", "telegram", "discord",
    "wordpress", "facebook", "instagram", "youtube", "autoagent",
]


class PlatformCredentialStore:
    """Encrypted read/write access to per-channel connection settings."""

    def __init__(self):
        self.security = SecurityManager()

    # ------------------------------------------------------------------ storage
    def _read_raw(self) -> dict:
        with Session(engine) as session:
            row = session.exec(select(SystemSetting).where(SystemSetting.key_name == SETTING_KEY)).first()
            if row and row.value:
                try:
                    return json.loads(row.value)
                except json.JSONDecodeError:
                    log_event("PlatformStore", "Stored connection blob was corrupt; starting fresh.", level="ERROR")
        return {}

    def _write_raw(self, data: dict):
        with Session(engine) as session:
            row = session.exec(select(SystemSetting).where(SystemSetting.key_name == SETTING_KEY)).first()
            payload = json.dumps(data)
            if row:
                row.value = payload
            else:
                row = SystemSetting(key_name=SETTING_KEY, value=payload)
            session.add(row)
            session.commit()

    @staticmethod
    def _spec(platform: str) -> dict:
        spec = PLATFORM_SPECS.get(platform)
        if not spec:
            raise KeyError(f"Unknown platform '{platform}'")
        return spec

    # ------------------------------------------------------------------ public API
    def get_credentials(self, platform: str) -> dict:
        """Decrypted values for use by the publisher. Never expose this over HTTP."""
        spec = self._spec(platform)
        stored = self._read_raw().get(platform, {}).get("fields", {})
        out = {}
        for f in spec["fields"]:
            value = stored.get(f["name"], "")
            out[f["name"]] = self.security.decrypt_credential(value) if f["secret"] and value else value
        return out

    def save_credentials(self, platform: str, submitted: dict) -> dict:
        """
        Persists submitted values. A blank secret keeps whatever is already stored, so the
        UI can show a masked placeholder without the user re-typing every key.
        """
        spec = self._spec(platform)
        data = self._read_raw()
        entry = data.get(platform, {})
        fields = entry.get("fields", {})

        for f in spec["fields"]:
            name = f["name"]
            raw = submitted.get(name)
            if raw is None:
                continue
            raw = str(raw).strip()
            if f["secret"]:
                if raw:
                    fields[name] = self.security.encrypt_credential(raw)
                # blank submission -> keep the stored secret
            else:
                fields[name] = raw

        entry["fields"] = fields
        entry["updated_at"] = datetime.now().isoformat()
        # Credentials changed, so any previous verification result is no longer meaningful.
        entry["status"] = "untested"
        entry.pop("last_error", None)
        entry.setdefault("enabled", True)
        data[platform] = entry
        self._write_raw(data)

        log_event("PlatformStore", f"Saved encrypted credentials for {spec['label']}.", level="SUCCESS")
        return self.describe(platform)

    def disconnect(self, platform: str) -> dict:
        spec = self._spec(platform)
        data = self._read_raw()
        if platform in data:
            data.pop(platform)
            self._write_raw(data)
            log_event("PlatformStore", f"Disconnected {spec['label']} and cleared its credentials.", level="WARNING")
        return self.describe(platform)

    def set_enabled(self, platform: str, enabled: bool) -> dict:
        self._spec(platform)
        data = self._read_raw()
        entry = data.setdefault(platform, {"fields": {}})
        entry["enabled"] = bool(enabled)
        data[platform] = entry
        self._write_raw(data)
        return self.describe(platform)

    def record_test_result(self, platform: str, ok: bool, detail: str = "", account: str = ""):
        data = self._read_raw()
        entry = data.setdefault(platform, {"fields": {}})
        entry["status"] = "connected" if ok else "failed"
        entry["last_checked"] = datetime.now().isoformat()
        if account:
            entry["account"] = account
        if ok:
            entry.pop("last_error", None)
        else:
            entry["last_error"] = detail[:300]
        data[platform] = entry
        self._write_raw(data)

    # ------------------------------------------------------------------ presentation
    def is_configured(self, platform: str) -> bool:
        """
        True when every required field holds a real value AND something was actually
        entered. Without the second condition a channel whose fields are all optional
        (YouTube) would report itself connected while holding nothing at all.
        """
        try:
            spec = self._spec(platform)
        except KeyError:
            return False

        creds = self.get_credentials(platform)
        has_any_value = False
        for f in spec["fields"]:
            value = str(creds.get(f["name"], "")).strip()
            placeholder = value.upper().startswith("YOUR_")
            if value and not placeholder:
                has_any_value = True
            if f["required"] and (not value or placeholder):
                return False
        return has_any_value

    def describe(self, platform: str) -> dict:
        """Safe summary for the dashboard. Contains no secret values."""
        spec = self._spec(platform)
        entry = self._read_raw().get(platform, {})
        stored = entry.get("fields", {})

        fields = []
        for f in spec["fields"]:
            value = stored.get(f["name"], "")
            fields.append({
                **{k: v for k, v in f.items()},
                # Non-secret values round-trip so the form repopulates; secrets never do.
                "value": "" if f["secret"] else value,
                "is_set": bool(value),
            })

        # Surface where this channel actually posts. A generic label like
        # "The Output Node (AutoAgent)" is impossible to match to your own site by eye.
        target = ""
        for f in spec["fields"]:
            if f["secret"]:
                continue
            value = str(stored.get(f["name"], "")).strip()
            if not value:
                continue
            if f["kind"] == "url" or value.startswith("http"):
                target = value.split("//")[-1].rstrip("/")
                break
            if f["name"] in ("chat_id", "subreddit", "page_id", "account_id", "author_urn", "channel_id"):
                target = value
                break

        return {
            "platform": platform,
            "label": spec["label"],
            "icon": spec["icon"],
            "target": target,
            "can_post": spec["can_post"],
            "auth": spec["auth"],
            "portal": spec["portal"],
            "setup": spec["setup"],
            "fields": fields,
            "configured": self.is_configured(platform),
            "enabled": entry.get("enabled", True),
            "status": entry.get("status", "untested"),
            "account": entry.get("account", ""),
            "last_checked": entry.get("last_checked", ""),
            "last_error": entry.get("last_error", ""),
            "updated_at": entry.get("updated_at", ""),
        }

    def describe_all(self) -> list:
        return [self.describe(p) for p in PLATFORM_ORDER]
