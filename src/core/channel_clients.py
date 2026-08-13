"""
Live channel transports: connection verification and real publishing.

Each channel exposes two operations:
    test(creds)            -> ChannelResult   verify the credentials actually work
    publish(creds, post)   -> ChannelResult   send the post to the channel

Everything is built on urllib so the project keeps its stdlib-only HTTP approach.
Failures return a ChannelResult with ok=False and a human-readable reason rather than
raising, because the publisher must be able to report per-channel outcomes.
"""
import os
import json
import time
import hmac
import base64
import hashlib
import mimetypes
import urllib.parse
import urllib.request
import urllib.error

from src.core.db import log_event

USER_AGENT = "SocialMediaMonster/1.1"
DEFAULT_TIMEOUT = 30


class ChannelResult:
    def __init__(self, ok: bool, message: str, account: str = "", external_id: str = "", url: str = ""):
        self.ok = ok
        self.message = message
        self.account = account
        self.external_id = external_id
        self.url = url

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "message": self.message, "account": self.account,
            "external_id": self.external_id, "url": self.url,
        }

    def __repr__(self):
        return f"<ChannelResult ok={self.ok} {self.message[:60]!r}>"


# ---------------------------------------------------------------------------- HTTP
def _request(url, method="GET", headers=None, data=None, json_body=None,
             form_body=None, timeout=DEFAULT_TIMEOUT):
    """Returns (status, parsed_or_text, error_message)."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)

    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), None
            except json.JSONDecodeError:
                return resp.status, raw, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return e.code, parsed, _http_reason(e.code, parsed)
    except urllib.error.URLError as e:
        return 0, None, f"Could not reach the service ({e.reason})."
    except Exception as e:
        return 0, None, f"Request failed: {e}"


def _http_reason(code, body) -> str:
    detail = ""
    if isinstance(body, dict):
        for key in ("error_description", "error", "message", "detail", "description"):
            v = body.get(key)
            if isinstance(v, str) and v:
                detail = v
                break
            if isinstance(v, dict):
                detail = v.get("message") or json.dumps(v)[:160]
                break
        if not detail and "errors" in body:
            errs = body["errors"]
            if isinstance(errs, list) and errs:
                first = errs[0]
                detail = first.get("message", json.dumps(first)[:160]) if isinstance(first, dict) else str(first)
    elif isinstance(body, str):
        detail = body[:200]

    friendly = {
        400: "Rejected as a bad request",
        401: "Authentication failed - the credential is wrong, expired or revoked",
        403: "Authenticated but not permitted - the token is missing a required scope",
        404: "Endpoint or target not found - check IDs and URLs",
        422: "The service rejected the content",
        429: "Rate limited - try again later",
    }.get(code, f"HTTP {code}")
    return f"{friendly}. {detail}".strip()


# ---------------------------------------------------------------------------- OAuth 1.0a
def _percent(value) -> str:
    return urllib.parse.quote(str(value), safe="~")


def _oauth1_header(method, url, consumer_key, consumer_secret, token, token_secret, query=None):
    """
    RFC 5849 signing. Twitter v2 posts a JSON body, which is excluded from the signature
    base string; only OAuth parameters and query parameters are signed.
    """
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": base64.urlsafe_b64encode(os.urandom(24)).decode().strip("="),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    signing_params = {**oauth, **(query or {})}
    encoded = "&".join(
        f"{_percent(k)}={_percent(v)}" for k, v in sorted(signing_params.items())
    )
    base_string = "&".join([method.upper(), _percent(url), _percent(encoded)])
    signing_key = f"{_percent(consumer_secret)}&{_percent(token_secret)}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()

    oauth["oauth_signature"] = signature
    return "OAuth " + ", ".join(f'{_percent(k)}="{_percent(v)}"' for k, v in sorted(oauth.items()))


def _missing(creds, *names):
    absent = [n for n in names if not str(creds.get(n, "")).strip()]
    return f"Missing required field(s): {', '.join(absent)}." if absent else ""


# ============================================================================ Telegram
def telegram_test(creds):
    err = _missing(creds, "bot_token")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(f"https://api.telegram.org/bot{creds['bot_token']}/getMe")
    if error or not isinstance(body, dict) or not body.get("ok"):
        return ChannelResult(False, error or "Telegram rejected the bot token.")
    name = body["result"].get("username", "")
    return ChannelResult(True, f"Connected as @{name}", account=f"@{name}")


def telegram_publish(creds, post):
    err = _missing(creds, "bot_token", "chat_id")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(
        f"https://api.telegram.org/bot{creds['bot_token']}/sendMessage",
        method="POST",
        json_body={
            "chat_id": creds["chat_id"],
            "text": post["content"][:4096],
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
    )
    if error or not isinstance(body, dict) or not body.get("ok"):
        return ChannelResult(False, error or "Telegram refused the message.")
    msg_id = str(body["result"].get("message_id", ""))
    return ChannelResult(True, "Posted to Telegram", external_id=msg_id)


# ============================================================================ Discord
def discord_test(creds):
    err = _missing(creds, "webhook_url")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(creds["webhook_url"])
    if error or not isinstance(body, dict):
        return ChannelResult(False, error or "Discord did not recognise that webhook URL.")
    return ChannelResult(True, f"Webhook valid for #{body.get('channel_id', '')}",
                         account=body.get("name", "webhook"))


def discord_publish(creds, post):
    err = _missing(creds, "webhook_url")
    if err:
        return ChannelResult(False, err)
    payload = {"content": post["content"][:2000]}
    if creds.get("username_override"):
        payload["username"] = creds["username_override"]

    status, body, error = _request(f"{creds['webhook_url']}?wait=true", method="POST", json_body=payload)
    if error:
        return ChannelResult(False, error)
    external = body.get("id", "") if isinstance(body, dict) else ""
    return ChannelResult(True, "Posted to Discord", external_id=str(external))


# ============================================================================ WordPress
def _wp_auth(creds):
    token = base64.b64encode(
        f"{creds['username']}:{creds['application_password']}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def wordpress_test(creds):
    err = _missing(creds, "site_url", "username", "application_password")
    if err:
        return ChannelResult(False, err)
    base = creds["site_url"].rstrip("/")
    status, body, error = _request(f"{base}/wp-json/wp/v2/users/me", headers=_wp_auth(creds))
    if error or not isinstance(body, dict):
        return ChannelResult(False, error or "WordPress did not return an account.")
    return ChannelResult(True, f"Connected as {body.get('name', '')}", account=body.get("name", ""))


def wordpress_publish(creds, post):
    err = _missing(creds, "site_url", "username", "application_password")
    if err:
        return ChannelResult(False, err)
    base = creds["site_url"].rstrip("/")
    # Default to draft: publishing straight to a live blog without review is not a
    # sensible default for automated content.
    wanted = (creds.get("post_status") or "draft").strip().lower()
    post_status = wanted if wanted in ("draft", "publish", "pending", "private") else "draft"

    status, body, error = _request(
        f"{base}/wp-json/wp/v2/posts",
        method="POST",
        headers=_wp_auth(creds),
        json_body={
            "title": post["headline"][:200],
            "content": post["content"],
            "status": post_status,
        },
    )
    if error or not isinstance(body, dict) or not body.get("id"):
        return ChannelResult(False, error or "WordPress did not create the post.")
    return ChannelResult(True, f"Created WordPress post ({post_status})",
                         external_id=str(body["id"]), url=body.get("link", ""))


# ============================================================================ Reddit
def _reddit_token(creds):
    auth = base64.b64encode(f"{creds['client_id']}:{creds['client_secret']}".encode()).decode()
    ua = creds.get("user_agent") or f"{USER_AGENT} by u/{creds.get('username', 'unknown')}"
    status, body, error = _request(
        "https://www.reddit.com/api/v1/access_token",
        method="POST",
        headers={"Authorization": f"Basic {auth}", "User-Agent": ua},
        form_body={
            "grant_type": "password",
            "username": creds["username"],
            "password": creds["password"],
        },
    )
    if error or not isinstance(body, dict) or not body.get("access_token"):
        hint = ""
        if isinstance(body, dict) and body.get("error") == "invalid_grant":
            hint = " Check the username/password, and note that accounts with 2FA enabled need an app password."
        return None, ua, (error or "Reddit refused the credentials.") + hint
    return body["access_token"], ua, None


def reddit_test(creds):
    err = _missing(creds, "client_id", "client_secret", "username", "password")
    if err:
        return ChannelResult(False, err)
    token, ua, error = _reddit_token(creds)
    if error:
        return ChannelResult(False, error)
    status, body, error = _request(
        "https://oauth.reddit.com/api/v1/me",
        headers={"Authorization": f"Bearer {token}", "User-Agent": ua},
    )
    if error or not isinstance(body, dict):
        return ChannelResult(False, error or "Could not read the Reddit account.")
    name = body.get("name", "")
    return ChannelResult(True, f"Connected as u/{name}", account=f"u/{name}")


def reddit_publish(creds, post):
    err = _missing(creds, "client_id", "client_secret", "username", "password", "subreddit")
    if err:
        return ChannelResult(False, err)
    token, ua, error = _reddit_token(creds)
    if error:
        return ChannelResult(False, error)

    subreddit = creds["subreddit"].strip().lstrip("/").removeprefix("r/")
    status, body, error = _request(
        "https://oauth.reddit.com/api/submit",
        method="POST",
        headers={"Authorization": f"Bearer {token}", "User-Agent": ua},
        form_body={
            "sr": subreddit,
            "kind": "self",
            "title": post["headline"][:300],
            "text": post["content"],
            "api_type": "json",
        },
    )
    if error:
        return ChannelResult(False, error)

    # Reddit returns HTTP 200 with the real failure inside json.errors.
    if isinstance(body, dict):
        payload = body.get("json", {})
        errors = payload.get("errors") or []
        if errors:
            first = errors[0]
            reason = " ".join(str(p) for p in first) if isinstance(first, list) else str(first)
            return ChannelResult(False, f"Reddit rejected the submission: {reason}")
        data = payload.get("data", {})
        return ChannelResult(True, f"Posted to r/{subreddit}",
                             external_id=str(data.get("id", "")), url=data.get("url", ""))
    return ChannelResult(False, "Unexpected response from Reddit.")


# ============================================================================ LinkedIn
def linkedin_test(creds):
    err = _missing(creds, "access_token")
    if err:
        return ChannelResult(False, err)
    headers = {"Authorization": f"Bearer {creds['access_token']}"}
    status, body, error = _request("https://api.linkedin.com/v2/userinfo", headers=headers)
    if not error and isinstance(body, dict):
        return ChannelResult(True, f"Connected as {body.get('name', '')}",
                             account=body.get("name", ""))
    # Older tokens lack the openid scope; fall back to a permission probe.
    status2, body2, error2 = _request("https://api.linkedin.com/v2/me", headers=headers)
    if not error2 and isinstance(body2, dict):
        return ChannelResult(True, "Token accepted", account=body2.get("id", ""))
    return ChannelResult(False, error or error2 or "LinkedIn rejected the token.")


def linkedin_publish(creds, post):
    err = _missing(creds, "access_token", "author_urn")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(
        "https://api.linkedin.com/v2/ugcPosts",
        method="POST",
        headers={
            "Authorization": f"Bearer {creds['access_token']}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json_body={
            "author": creds["author_urn"],
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": post["content"][:3000]},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        },
    )
    if error:
        return ChannelResult(False, error)
    post_id = body.get("id", "") if isinstance(body, dict) else ""
    return ChannelResult(True, "Posted to LinkedIn", external_id=str(post_id))


# ============================================================================ Facebook
def facebook_test(creds):
    err = _missing(creds, "page_id", "page_access_token")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(
        f"https://graph.facebook.com/v19.0/{creds['page_id']}"
        f"?fields=name&access_token={urllib.parse.quote(creds['page_access_token'])}"
    )
    if error or not isinstance(body, dict) or not body.get("name"):
        return ChannelResult(False, error or "Facebook did not return the page.")
    return ChannelResult(True, f"Connected to page '{body['name']}'", account=body["name"])


def facebook_publish(creds, post):
    err = _missing(creds, "page_id", "page_access_token")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(
        f"https://graph.facebook.com/v19.0/{creds['page_id']}/feed",
        method="POST",
        form_body={"message": post["content"][:5000], "access_token": creds["page_access_token"]},
    )
    if error or not isinstance(body, dict) or not body.get("id"):
        return ChannelResult(False, error or "Facebook did not create the post.")
    return ChannelResult(True, "Posted to Facebook Page", external_id=str(body["id"]))


# ============================================================================ Instagram
def instagram_test(creds):
    err = _missing(creds, "account_id", "access_token")
    if err:
        return ChannelResult(False, err)
    status, body, error = _request(
        f"https://graph.facebook.com/v19.0/{creds['account_id']}"
        f"?fields=username&access_token={urllib.parse.quote(creds['access_token'])}"
    )
    if error or not isinstance(body, dict) or not body.get("username"):
        return ChannelResult(False, error or "Instagram did not return the account.")
    return ChannelResult(True, f"Connected as @{body['username']}", account=f"@{body['username']}")


def instagram_publish(creds, post):
    err = _missing(creds, "account_id", "access_token")
    if err:
        return ChannelResult(False, err)

    image_url = post.get("public_image_url", "")
    if not image_url:
        # This is a hard API requirement, not a limitation we can work around locally.
        return ChannelResult(
            False,
            "Instagram requires an image reachable at a public URL. Set 'Public Image Base URL' "
            "and make the generated image available there, or post this one manually.",
        )

    status, body, error = _request(
        f"https://graph.facebook.com/v19.0/{creds['account_id']}/media",
        method="POST",
        form_body={
            "image_url": image_url,
            "caption": post["content"][:2200],
            "access_token": creds["access_token"],
        },
    )
    if error or not isinstance(body, dict) or not body.get("id"):
        return ChannelResult(False, error or "Instagram did not accept the media container.")

    status, body2, error = _request(
        f"https://graph.facebook.com/v19.0/{creds['account_id']}/media_publish",
        method="POST",
        form_body={"creation_id": body["id"], "access_token": creds["access_token"]},
    )
    if error or not isinstance(body2, dict) or not body2.get("id"):
        return ChannelResult(False, error or "Instagram did not publish the container.")
    return ChannelResult(True, "Posted to Instagram", external_id=str(body2["id"]))


# ============================================================================ X / Twitter
def twitter_test(creds):
    err = _missing(creds, "api_key", "api_secret", "access_token", "access_token_secret")
    if err:
        return ChannelResult(False, err)
    url = "https://api.twitter.com/2/users/me"
    header = _oauth1_header("GET", url, creds["api_key"], creds["api_secret"],
                            creds["access_token"], creds["access_token_secret"])
    status, body, error = _request(url, headers={"Authorization": header})
    if error or not isinstance(body, dict) or "data" not in body:
        return ChannelResult(False, error or "X rejected the OAuth 1.0a credentials.")
    handle = body["data"].get("username", "")
    return ChannelResult(True, f"Connected as @{handle}", account=f"@{handle}")


def twitter_publish(creds, post):
    err = _missing(creds, "api_key", "api_secret", "access_token", "access_token_secret")
    if err:
        return ChannelResult(False, err)
    url = "https://api.twitter.com/2/tweets"
    header = _oauth1_header("POST", url, creds["api_key"], creds["api_secret"],
                            creds["access_token"], creds["access_token_secret"])
    status, body, error = _request(
        url,
        method="POST",
        headers={"Authorization": header},
        json_body={"text": post["content"][:280]},
    )
    if error or not isinstance(body, dict) or "data" not in body:
        return ChannelResult(False, error or "X did not accept the tweet.")
    tweet_id = body["data"].get("id", "")
    return ChannelResult(True, "Posted to X", external_id=str(tweet_id),
                         url=f"https://x.com/i/status/{tweet_id}" if tweet_id else "")


# ============================================================================ YouTube
def youtube_test(creds):
    if not str(creds.get("api_key", "")).strip():
        return ChannelResult(False, "Add a YouTube Data API key to verify the channel.")
    channel_id = str(creds.get("channel_id", "")).strip()
    if not channel_id:
        return ChannelResult(False, "Add the channel ID to verify.")
    status, body, error = _request(
        "https://www.googleapis.com/youtube/v3/channels"
        f"?part=snippet&id={urllib.parse.quote(channel_id)}&key={urllib.parse.quote(creds['api_key'])}"
    )
    if error or not isinstance(body, dict) or not body.get("items"):
        return ChannelResult(False, error or "YouTube did not return that channel.")
    title = body["items"][0]["snippet"]["title"]
    return ChannelResult(True, f"Channel verified: {title} (posting is manual)", account=title)


def youtube_publish(creds, post):
    # Being explicit beats silently pretending to publish.
    return ChannelResult(
        False,
        "YouTube provides no public API for creating Community posts. Copy the generated "
        "text and post it manually from YouTube Studio.",
    )


# ---------------------------------------------------------------------------- registry
CHANNELS = {
    "twitter":   {"test": twitter_test,   "publish": twitter_publish},
    "linkedin":  {"test": linkedin_test,  "publish": linkedin_publish},
    "reddit":    {"test": reddit_test,    "publish": reddit_publish},
    "telegram":  {"test": telegram_test,  "publish": telegram_publish},
    "discord":   {"test": discord_test,   "publish": discord_publish},
    "wordpress": {"test": wordpress_test, "publish": wordpress_publish},
    "facebook":  {"test": facebook_test,  "publish": facebook_publish},
    "instagram": {"test": instagram_test, "publish": instagram_publish},
    "youtube":   {"test": youtube_test,   "publish": youtube_publish},
}


def test_channel(platform: str, creds: dict) -> ChannelResult:
    handler = CHANNELS.get(platform)
    if not handler:
        return ChannelResult(False, f"Unknown channel '{platform}'.")
    try:
        result = handler["test"](creds)
    except Exception as e:
        result = ChannelResult(False, f"Connection test raised an error: {e}")
    log_event("ChannelClient", f"Connection test for {platform}: "
                               f"{'OK' if result.ok else 'FAILED'} - {result.message}",
              level="SUCCESS" if result.ok else "WARNING")
    return result


def publish_to_channel(platform: str, creds: dict, post: dict) -> ChannelResult:
    handler = CHANNELS.get(platform)
    if not handler:
        return ChannelResult(False, f"Unknown channel '{platform}'.")
    try:
        return handler["publish"](creds, post)
    except Exception as e:
        return ChannelResult(False, f"Publish raised an error: {e}")
