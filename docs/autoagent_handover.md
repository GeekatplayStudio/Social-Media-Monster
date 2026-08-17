# Handover Document: AutoAgent Webpage Code & Content Integration

## 📌 Objective

This document provides complete instructions, API specifications, and code samples for updating **AutoAgent** (or any automated AI agent runner) to programmatically generate, format, and publish code snippets, media assets, and rich articles to **"The Output Node"** web platform over secure HMAC-SHA256 REST APIs.

---

## 🛠️ System Architecture & Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                        AutoAgent                            │
│  1. Generates title, content & code snippets                │
│  2. Uploads local media (images/videos) ──► POST /upload.php│
│  3. Formats HTML with code (<pre><code>) & media URLs      │
│  4. Computes HMAC-SHA256 payload hash                       │
│  5. Transmits payload ────────────────────► POST /publish.php │
└─────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Hostinger PHP Server                     │
│  1. Verifies HMAC signature with hash_equals()              │
│  2. Checks timestamp freshness (< 300s)                     │
│  3. Saves post to DB via PDO                                │
└─────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   Frontend (index.html)                     │
│  Display posts with highlighted code blocks & media         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 Authentication Protocol (HMAC-SHA256)

Both AutoAgent and the server share a **Secret Key** (`SECRET_KEY`). Keys are **never sent in plaintext** over the network. Instead, AutoAgent sends a cryptographic HMAC signature in HTTP headers.

### Security Constraints:
- **Timestamp Window**: Requests with timestamps older or newer than **300 seconds** (5 minutes) from server time will be rejected to prevent replay attacks.
- **Strict JSON**: Payload signature MUST be computed on the exact un-spaced JSON string (`json.dumps(payload, separators=(',', ':'))`).

---

## 📡 API Specifications

### 1. Media Upload Endpoint

- **URL**: `POST https://www.vladimirchopine.com/ai-news/api/upload.php`
- **Content-Type**: `multipart/form-data`
- **Required Headers**:
  - `X-Timestamp`: Unix timestamp (integer string)
  - `X-File-Name`: Original filename (e.g. `diagram.png`)
  - `X-Signature`: `HMAC-SHA256( f"{X-Timestamp}:{X-File-Name}", SECRET_KEY )`
- **Form Data Field**: `media` (file binary)
- **Response Format**:
  ```json
  {
    "status": "success",
    "url": "https://www.vladimirchopine.com/ai-news/api/uploads/media_6a823933cc.png",
    "filename": "media_6a823933cc.png"
  }
  ```

---

### 2. Post Publishing Endpoint

- **URL**: `POST https://www.vladimirchopine.com/ai-news/api/publish.php`
- **Content-Type**: `application/json`
- **Required Headers**:
  - `X-Signature`: `HMAC-SHA256( raw_json_body_bytes, SECRET_KEY )`
- **Request Body Payload**:
  ```json
  {
    "title": "AutoAgent Code Solution: Binary Search in Python",
    "content": "<h2>Solution Overview</h2><p>Here is the algorithm:</p><pre><code>def binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n    while low &lt;= high:\n        mid = (low + high) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] &lt; target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1</code></pre>",
    "timestamp": 1715421234
  }
  ```
- **Response Format**:
  ```json
  {
    "status": "success",
    "message": "Post published securely!",
    "post_id": 42,
    "title": "AutoAgent Code Solution: Binary Search in Python"
  }
  ```

---

## 💻 Formatting Code Snippets for the Webpage

When AutoAgent publishes code snippets to the webpage, it must wrap the code inside `<pre><code>...</code></pre>` HTML tags and escape HTML special characters (`<`, `>`, `&`, `"`) to ensure correct rendering.

### Formatting Helper Functions:

#### Python AutoAgent Helper:
```python
import html

def format_code_block(code_text: str, language: str = "python") -> str:
    """Escapes raw code and wraps it in syntax-renderable HTML tags."""
    escaped_code = html.escape(code_text)
    return f'<pre><code class="language-{language}">{escaped_code}</code></pre>'
```

#### Node.js / TypeScript AutoAgent Helper:
```typescript
function formatCodeBlock(codeText: string, language: string = 'javascript'): string {
    const escapedCode = codeText
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    return `<pre><code class="language-${language}">${escapedCode}</code></pre>`;
}
```

---

## 🚀 Ready-to-Use AutoAgent Publisher Modules

### 1. Python AutoAgent Publisher (`autoagent_publisher.py`)

```python
import hmac
import hashlib
import json
import time
import requests
import html
import os

class AutoAgentPublisher:
    def __init__(self, base_url: str, secret_key: str):
        self.base_url = base_url.rstrip('/')
        self.secret_key = secret_key.encode('utf-8')
        self.upload_url = f"{self.base_url}/upload.php"
        self.publish_url = f"{self.base_url}/publish.php"

    def upload_media(self, file_path: str) -> str:
        """Uploads image/video asset and returns live web URL."""
        filename = os.path.basename(file_path)
        timestamp = str(int(time.time()))
        message = f"{timestamp}:{filename}".encode('utf-8')
        signature = hmac.new(self.secret_key, message, hashlib.sha256).hexdigest()

        headers = {
            "X-Timestamp": timestamp,
            "X-File-Name": filename,
            "X-Signature": signature
        }

        with open(file_path, 'rb') as f:
            response = requests.post(self.upload_url, files={'media': (filename, f)}, headers=headers)
        
        response.raise_for_status()
        return response.json()['url']

    def publish_code_article(self, title: str, summary: str, code_snippet: str, language: str = "python", image_path: str = None):
        """Formats and publishes an article containing text, uploaded images, and formatted code."""
        content_parts = [f"<p>{html.escape(summary)}</p>"]

        # 1. Upload & Embed Image if provided
        if image_path and os.path.exists(image_path):
            img_url = self.upload_media(image_path)
            content_parts.append(f'<img src="{img_url}" alt="Agent Media Asset" />')

        # 2. Format & Escape Code Block
        escaped_code = html.escape(code_snippet)
        content_parts.append(f'<pre><code class="language-{language}">{escaped_code}</code></pre>')

        full_content = "\n".join(content_parts)

        # 3. Build & Sign Payload
        payload = {
            "title": title,
            "content": full_content,
            "timestamp": int(time.time())
        }

        json_payload = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        signature = hmac.new(self.secret_key, json_payload.encode('utf-8'), hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature
        }

        # 4. POST to Webpage Endpoint
        res = requests.post(self.publish_url, data=json_payload.encode('utf-8'), headers=headers)
        res.raise_for_status()
        return res.json()


# Usage Example for AutoAgent Developer:
if __name__ == "__main__":
    agent = AutoAgentPublisher(
        base_url="https://www.vladimirchopine.com/ai-news/api", # Hostinger Production URL
        secret_key="your_super_secret_string_change_me_123!"
    )

    code_to_publish = '''def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
'''

    response = agent.publish_code_article(
        title="AutoAgent Generated Fibonacci Implementation",
        summary="Here is an efficient Python recursive function generated automatically by AutoAgent.",
        code_snippet=code_to_publish,
        language="python"
    )
    print("Published successfully:", response)
```

---

### 2. Node.js / TypeScript AutoAgent Publisher (`autoagent_publisher.ts`)

```typescript
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import axios from 'axios';
import FormData from 'form-data';

export class AutoAgentPublisher {
    private baseUrl: string;
    private secretKey: string;

    constructor(baseUrl: string, secretKey: string) {
        this.baseUrl = baseUrl.replace(/\/+$/, '');
        this.secretKey = secretKey;
    }

    private computeHmac(data: string | Buffer): string {
        return crypto.createHmac('sha256', this.secretKey).update(data).digest('hex');
    }

    async uploadMedia(filePath: string): Promise<string> {
        const fileName = path.basename(filePath);
        const timestamp = Math.floor(Date.now() / 1000).toString();
        const signature = this.computeHmac(`${timestamp}:${fileName}`);

        const form = new FormData();
        form.append('media', fs.createReadStream(filePath), fileName);

        const response = await axios.post(`${this.baseUrl}/upload.php`, form, {
            headers: {
                ...form.getHeaders(),
                'X-Timestamp': timestamp,
                'X-File-Name': fileName,
                'X-Signature': signature
            }
        });

        return response.data.url;
    }

    async publishCodeArticle(title: string, summary: str, codeSnippet: string, language = 'typescript', imagePath?: string) {
        let contentHtml = `<p>${this.escapeHtml(summary)}</p>`;

        if (imagePath && fs.existsSync(imagePath)) {
            const imageUrl = await this.uploadMedia(imagePath);
            contentHtml += `\n<img src="${imageUrl}" alt="AutoAgent asset" />`;
        }

        const escapedCode = this.escapeHtml(codeSnippet);
        contentHtml += `\n<pre><code class="language-${language}">${escapedCode}</code></pre>`;

        const payload = {
            title,
            content: contentHtml,
            timestamp: Math.floor(Date.now() / 1000)
        };

        const jsonPayload = JSON.stringify(payload);
        const signature = this.computeHmac(jsonPayload);

        const response = await axios.post(`${this.baseUrl}/publish.php`, jsonPayload, {
            headers: {
                'Content-Type': 'application/json',
                'X-Signature': signature
            }
        });

        return response.data;
    }

    private escapeHtml(str: string): string {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}
```

---

## ✅ AutoAgent Integration Checklist

- [ ] Ensure AutoAgent environment variable `API_SECRET_KEY` matches server `api/config.php`.
- [ ] Verify system clocks are synchronized (NTP) to stay within the 300s window.
- [ ] Format code blocks using HTML escaping before building the final post JSON payload.
- [ ] Verify HTTP response status `200 OK` and inspect `post_id` in response.
- [ ] Test publication locally or on staging before deploying AutoAgent to production.
