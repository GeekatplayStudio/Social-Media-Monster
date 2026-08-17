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
            content_parts.append(f"<p>{html.escape(summary)}</p>")

        # 1. Upload & Embed Image if provided
        if image_path and os.path.exists(image_path):
            img_url = self.upload_media(image_path)
            content_parts.append(f'<img src="{img_url}" alt="Agent Media Asset" />')

        # 2. Format & Escape Code Block if provided
        if code_snippet:
            formatted_code = self.format_code_block(code_snippet, language=language)
            content_parts.append(formatted_code)

        full_content = "\n".join(content_parts)
        return self.publish_article(title=title, content=full_content)


if __name__ == "__main__":
    import sys
    print("AutoAgentPublisher module loaded successfully.")
