"""
AutoAgent Publisher: Secure HMAC-SHA256 Content & Code Snippet Publishing Client.

Integrates with "The Output Node" web platform (e.g. https://www.vladimirchopine.com/ai-news/api)
for publishing rich articles, media assets, and HTML-escaped syntax-highlighted code blocks.
"""
import hmac
import hashlib
import json
import time
import html
import os
import urllib.request
import urllib.parse
import urllib.error
import mimetypes


class AutoAgentPublisher:
    """
    Publisher client for The Output Node REST API using HMAC-SHA256 authentication.
    """

    def __init__(self, base_url: str, secret_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.secret_key = secret_key.encode('utf-8')
        self.upload_url = f"{self.base_url}/upload.php"
        self.publish_url = f"{self.base_url}/publish.php"
        self.timeout = timeout

    # Extensions that must render as a player rather than an image.
    VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v")

    @classmethod
    def media_embed(cls, url: str, alt: str = "Agent Media Asset") -> str:
        """
        Picks the right tag for the asset.

        Everything used to be emitted as <img>, so a generated .mp4 published as a broken
        image instead of a playable video.
        """
        safe_url = html.escape(url, quote=True)
        if url.lower().split("?")[0].endswith(cls.VIDEO_EXTENSIONS):
            return (f'<video src="{safe_url}" controls playsinline preload="metadata" '
                    f'style="max-width:100%"></video>')
        return f'<img src="{safe_url}" alt="{html.escape(alt, quote=True)}" />'

    @staticmethod
    def markdown_to_html(text: str, drop_title: str = "") -> str:
        """
        Converts the markdown the writer produces into HTML.

        The body was HTML-escaped wholesale, so "# Heading" and "**bold**" published as
        literal characters. Everything is still escaped first, then a small, fixed set of
        inline patterns is promoted to tags - no raw author HTML is ever passed through.
        """
        import re as _re

        blocks = []
        for raw_block in _re.split(r'\n\s*\n', (text or "").strip()):
            block = raw_block.strip()
            if not block:
                continue

            heading = _re.match(r'^(#{1,6})\s+(.*)$', block)
            if heading:
                level = min(len(heading.group(1)) + 1, 6)  # the page supplies the h1
                content = heading.group(2).strip()
                # The site stores the title separately; repeating it reads as duplication.
                if drop_title and content.lower().strip('*# ') == drop_title.lower().strip():
                    continue
                blocks.append(f"<h{level}>{html.escape(content)}</h{level}>")
                continue

            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if lines and all(_re.match(r'^([-*•▪]|\d+[.)])\s+', l) for l in lines):
                marker = _re.compile(r'^([-*•▪]|\d+[.)])\s+')
                items = "".join(
                    f"<li>{html.escape(marker.sub('', l))}</li>" for l in lines
                )
                tag = "ol" if _re.match(r'^\d+[.)]', lines[0]) else "ul"
                blocks.append(f"<{tag}>{items}</{tag}>")
                continue

            escaped = html.escape(" ".join(lines))
            if drop_title and escaped.strip('*').lower() == html.escape(drop_title).lower():
                continue
            blocks.append(f"<p>{escaped}</p>")

        rendered = "\n".join(blocks)
        # Inline emphasis, applied after escaping so no author markup can slip through.
        rendered = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', rendered)
        rendered = _re.sub(r'(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', rendered)
        return rendered

    @staticmethod
    def format_code_block(code_text: str, language: str = "python") -> str:
        """Escapes raw code and wraps it in syntax-renderable HTML tags."""
        escaped_code = html.escape(code_text)
        return f'<pre><code class="language-{language}">{escaped_code}</code></pre>'

    def compute_upload_signature(self, timestamp: str, filename: str) -> str:
        """Computes HMAC-SHA256 signature for media upload headers."""
        message = f"{timestamp}:{filename}".encode('utf-8')
        return hmac.new(self.secret_key, message, hashlib.sha256).hexdigest()

    def compute_payload_signature(self, raw_json_bytes: bytes) -> str:
        """Computes HMAC-SHA256 signature for post publishing body bytes."""
        return hmac.new(self.secret_key, raw_json_bytes, hashlib.sha256).hexdigest()

    def upload_media(self, file_path: str) -> str:
        """Uploads image/video asset and returns live web URL."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Media file not found: {file_path}")

        filename = os.path.basename(file_path)
        timestamp = str(int(time.time()))
        signature = self.compute_upload_signature(timestamp, filename)

        headers = {
            "X-Timestamp": timestamp,
            "X-File-Name": filename,
            "X-Signature": signature,
            "User-Agent": "SocialMediaMonster-AutoAgent/1.0"
        }

        # Build multipart/form-data payload
        boundary = f"----WebKitFormBoundary{os.urandom(16).hex()}"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            file_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(self.upload_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and data.get("status") == "success" and "url" in data:
                    return data["url"]
                raise RuntimeError(f"Media upload rejected by server: {data}")
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} Media upload failed: {raw_err}") from e

    def publish_article(self, title: str, content: str) -> dict:
        """Publishes raw HTML article content to /publish.php with HMAC signature."""
        payload = {
            "title": title,
            "content": content,
            "timestamp": int(time.time())
        }

        # Strict JSON formatting with separators=(',', ':')
        json_payload = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        raw_bytes = json_payload.encode('utf-8')
        signature = self.compute_payload_signature(raw_bytes)

        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature,
            "User-Agent": "SocialMediaMonster-AutoAgent/1.0"
        }

        req = urllib.request.Request(self.publish_url, data=raw_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return res_data
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} Publishing failed: {raw_err}") from e

    def publish_code_article(
        self,
        title: str,
        summary: str,
        code_snippet: str = "",
        language: str = "python",
        image_path: str = None
    ) -> dict:
        """Formats and publishes an article containing text, uploaded images, and formatted code."""
        content_parts = []
        if summary:
            content_parts.append(self.markdown_to_html(summary, drop_title=title))

        # 1. Upload & Embed Image if provided
        if image_path and os.path.exists(image_path):
            img_url = self.upload_media(image_path)
            content_parts.append(self.media_embed(img_url))

        # 2. Format & Escape Code Block if provided
        if code_snippet:
            formatted_code = self.format_code_block(code_snippet, language=language)
            content_parts.append(formatted_code)

        full_content = "\n".join(content_parts)
        return self.publish_article(title=title, content=full_content)


if __name__ == "__main__":
    import sys
    print("AutoAgentPublisher module loaded successfully.")
