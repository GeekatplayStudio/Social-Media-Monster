<p align="center">
  <img src="assets/monster_logo.jpg" width="220" alt="SocialMediaMonster Logo" style="border-radius: 16px;">
</p>

<h1 align="center">SocialMediaMonster</h1>
<p align="center">
  <strong>Autonomous Multi-Platform AI Content Engine & MCP Protocol Server</strong>
</p>

---

## 📌 Overview

**SocialMediaMonster** is a state-of-the-art, autonomous multi-agent content generation and publishing engine. It continuously monitors target internet feeds (RSS, Google News, Hacker News, ArXiv, TechCrunch), verifies emerging news, crafts authentic human-quality posts across **9 social channels**, optimizes copy for high CTR with zero AI detection markers, generates high-resolution 16-bit RPG visual artwork, and exposes a standardized **Model Context Protocol (MCP) Server**.

It features a high-contrast corporate control dashboard equipped with a **15-Band Visual Graphic Equalizer**, **Author Voice Cloning**, **Dynamic 16-Bit Pixel Art Writer Personas**, **Traffic Controller Watchdog**, **Fernet Credential Encryption**, **Google OAuth 2.0**, **Abstract LLM/Visual Provider Layer**, **Temporal-like Worker State Recovery**, and an **Emergency Stop Controller**.

---

## ⚡ Key Features & Technologies

### 🧠 1. Multi-Agent Autonomous Architecture
* **TrafficControllerAgent**: Bandwidth watchdog that halts unnecessary web scanning when pending draft quotas are met or when articles are accepted by the Final Content Manager.
* **ResearchAgent**: Discovers stories through the **Tavily Search API** (ranked, freshness-filtered news) when a key is configured, and falls back to Google News RSS and tech feeds (Hacker News, ArXiv, TechCrunch) otherwise, with automatic de-duplication by URL.
* **VerifierAgent**: Pulls the full article body via **Tavily Extract**, strips feed noise, and derives concrete technical facts. It does not emit generic boilerplate.
* **WriterAgent**: Crafts platform-optimized posts across 9 supported channels (Twitter/X, Instagram, Facebook, YouTube Community, Telegram, LinkedIn, Reddit, Discord, WordPress Blog) using the active equalizer profile and voice sample.
* **HumanizerAgent**: Eliminates robotic AI phrasings, enhances natural pacing, and optimizes CTR & SEO scores.
* **ValidatorAgent**: Acts as the Final Content Manager QA Gate. It re-audits AI signatures, repairs generic image prompts, then marks each draft `approved` or `needs_review` so the PublisherAgent has a queue to work from.
* **VisualAgent**: Supports dynamic **Image vs Video Mode selection**. In Image mode, generates story-specific 16-bit RPG artwork supporting **Local ComfyUI (SD1.5/SDXL)**, **Stability AI Cloud API**, **ComfyUI Org Cloud API**, and an **Editorial Card** fallback. In Video mode, generates **1 Master 9:16 Vertical Video** per story (AnimateDiff / Wan2.1 / LTX-Video / FFmpeg overlay engine) and attaches that single video asset across **all 9 post drafts** for that story.
* **PublisherAgent**: Dispatches approved drafts and video/image media to live channel APIs using credentials stored (encrypted) in **Channel Connections**. A channel is contacted only when it is connected and enabled; anything else is skipped with the reason, and a post is marked published only when the remote service confirms it.
* **SuperAgent**: Master orchestrator controlling stage execution and anti-spam schedule intervals.

### 🎛 2. 15-Band Visual Style Graphic Equalizer & Voice Cloning
* **15 Precision Style Bands**: Fine-tune tone across Seriousness/Humor, Formality, Cynicism/Sarcasm, Technical Depth, Controversy Stance, Pacing, Emotional Warmth, Storytelling, Authority, Metaphors, Clickbait Energy, Tech Jargon, Action CTA, Humor Type, and Provocativeness.
* **Author Voice Cloning**: Paste a sample article written by you. The system analyzes your syntax and mirrors your exact writing voice.

### 👤 3. Dynamic 16-Bit RPG Writer Personas
* Features 6 distinct 16-bit retro RPG writer character portraits representing diverse ages, genders, races, and aesthetic styles:
  * **Dr. Marcus Vance**: Academic & Research Specialist
  * **Sora Takahashi**: Cyberpunk Tech Analyst
  * **Elena Rostova**: Sarcastic AI Realist
  * **Jax Sterling**: Viral Growth Strategist
  * **Aaliyah Thorne**: Empathetic AI Mentor
  * **Kai Chen**: Futurist & Deep Essayist
* Real-time vector matching dynamically calculates the closest writer persona and updates the avatar image, name, title, and style match percentage as you move the equalizer sliders!

### 🔐 4. Security & Credential Encryption
* **Fernet Credential Encryption**: All API credentials (OpenAI, Gemini, Anthropic, Stability AI, ComfyUI Org, Tavily, and platform tokens) are encrypted with a PBKDF2-HMAC-SHA256 derived Fernet key before saving to SQLite (`ENC:v2:...`). Records written by earlier builds still decrypt transparently.
* **Master Key Handling**: The key lives in `.env.secret` (git-ignored) or the `SMM_MASTER_KEY` environment variable. It is never committed.
* **Key Rotation**: `python scripts/rotate_key.py` replaces the master key and re-encrypts every stored credential under the new one in a single transaction, so a previously exposed key stops decrypting current data.
* **Payload Sanitization Gate**: Input script/injection stripping and output redaction of OpenAI, Anthropic, Gemini, Tavily and Slack-style tokens.
* **Secrets never leave the server**: no API returns a decrypted credential. `GET /api/platforms` and `GET /api/provider-config` report only an `is_set` flag per field, and submitting a blank secret preserves the stored one rather than wiping it.
* **Nothing sensitive is committed**: `.env.secret`, `*.db`, `.run/` and generated media are git-ignored. The repository contains no live key, and no credential is ever written to the event log.
* **Google OAuth 2.0 Auth**: Conditional remote protection (bypassed on local desktop, enforced on remote deployment).

> **Historical note:** `.env.secret` was tracked before `v1.1`. That key has been rotated
> with `scripts/rotate_key.py`, so the copy still present in git history no longer
> decrypts anything. Rotate again if you ever suspect exposure.

### 🔌 5. Abstract Provider API Layer & Image Engine Selector
* Abstracted routing across Local Ollama, OpenAI, Google Gemini, Anthropic Claude, Stability AI, ComfyUI Org, and the Editorial Card renderer.
* When no provider answers, an **offline synthesizer** reformats the material already in the prompt. It never invents a story, and it never substitutes one article's facts into another post.

### 🔎 6. Tavily Research Integration *(optional)*
* **Discovery** — `ResearchAgent` calls Tavily Search per topic with a freshness window, receiving ranked results with relevance scores instead of scraping RSS.
* **Fact Extraction** — `VerifierAgent` calls Tavily Extract on each story URL to obtain the full article body, so verified facts come from the real text rather than a truncated feed blurb.
* **MCP Tool** — `research_topic` exposes a live Tavily search to external agents.
* **Never required.** No key, a blank key, a placeholder, a rate limit or a rejected key each fall back to Google News RSS. The pipeline completes either way.

### 🌐 7. Model Context Protocol (MCP) Protocol Server
* Exposes standardized MCP endpoints (`GET /api/mcp/manifest` & `POST /api/mcp/call`) allowing external AI agents to inspect status, trigger research scans, run a live Tavily topic search, execute cycles, and approve or reject drafts.

### ✅ 8. Draft Lifecycle
Posts move through explicit states, and each agent only picks up its own stage:

`draft` → `humanized` → `approved` \| `needs_review` → `published` \| `rejected`

Approve or reject any post from the dashboard, from `POST /api/posts/{id}/approve`, or via the MCP `approve_post` tool. Publishing only dispatches in **PRODUCTION** mode.

---

## 🧭 How It Works (the whole flow)

```
  Topics you type
        ↓
  1. RESEARCH    Tavily Search (or Google News RSS) finds fresh stories, de-duped by URL
        ↓
  2. VERIFY      Full article text pulled, page chrome stripped, core facts extracted
        ↓
  3. WRITE       One post per channel, in your equalizer voice and each channel's format
        ↓
  4. HUMANIZE    AI tropes removed, CTR and AI-detection scored
        ↓
  5. QA GATE     Approved, or held for review
        ↓
  6. ARTWORK     ONE image or video per STORY, reused by every channel's post
        ↓
  7. PUBLISH     Sent only in PRODUCTION mode, only to connected channels,
                 only once the artwork exists — then marked published so it never repeats
```

**The dashboard shows this as a live checklist.** The **Setup & Status** panel at the top
lists all eight steps with their state and, when something is blocking, the exact action
that clears it:

```
NOT POSTING - Click PROD in the header. Nothing is dispatched while in DEMO.
```

That panel is the first place to look whenever the engine seems idle. It is also
available as `GET /api/readiness`.

> **The most common surprise:** the engine starts in **DEMO** mode, which generates
> everything but never sends. Click **PROD** in the header to actually publish.

### One asset per story, never per post

A story published to 10 channels used to render 10 separate images. It now renders **one
master asset per story** and attaches it to every post of that story:

* 3 stories × 10 channels = **3 renders**, not 30
* re-running a cycle re-renders **nothing**
* related stories on the same subject get different staging, so artwork never repeats

---

## 🚀 Getting Started

### 1. Prerequisites
* **Python 3.12+**
* (Optional) **Local Ollama** or **ComfyUI** for local execution.

### 2. Installation

```bash
git clone https://github.com/GeekatplayStudio/Social-Media-Monster.git
cd Social-Media-Monster
```

**Windows (PowerShell)**
```powershell
.\scripts\install.ps1
```

**Linux / macOS**
```bash
chmod +x scripts/*.sh
./scripts/install.sh
```

The installer creates a `.venv`, installs dependencies, initializes the SQLite database, and generates the credential encryption key. It is safe to re-run — your data is never deleted.

### 3. Choose a Text Model (this decides article quality)

Output quality depends almost entirely on the text model. With no model reachable the
engine still works, but it falls back to **extractive summaries** — accurate and grounded
in the source, yet plainly worded.

**Local (Ollama)**
```bash
ollama serve                 # must be running; the tray icon alone is not enough
ollama list                  # the model in config must appear here
ollama pull gemma3:12b       # if it does not
```
Then set the model in **⚙ → Abstract API Provider Layer → Model Name**. Press **Detect**
to list what the endpoint actually has. The badge reads `ready`, `model not installed`, or
`endpoint unreachable`, so a misconfigured model can't fail silently.

> A 12B model needs ~30–60s on its first call while it loads into memory. `llm.timeout_seconds`
> (default 300) covers this. A timeout is treated as "slow", not "down" — it will not disable
> the provider.

**Cloud** — paste an OpenAI, Gemini, or Anthropic key in the same panel and switch the
provider dropdown. Cloud models are faster and need no local resources.

### 3b. Image & Video Rendering (ComfyUI)

Choose **Image** or **Video** mode in *Anti-Spam & Image Settings*. Either way the engine
produces **one master asset per story** and reuses it across every channel.

Modern models ship as a bare transformer, so they are loaded as **UNET + text encoder +
VAE** rather than a single checkpoint file. Auto-detection prefers them and falls back to
a self-contained checkpoint. Verified working locally:

| Purpose | Model | Text encoder | VAE | Steps |
|---|---|---|---|---|
| **Image** | `z_image_turbo_bf16` | `qwen_3_4b` (type `lumina2`) | `ae.safetensors` | 8 @ CFG 1.5 |
| **Video** | `ltx-2.5-22b-distilled-transformer` | `gemma4-12b-with-proj-ltx-2.5` | `ltx-2.5-video-vae-bf16` | 8 @ CFG 1.0 |

Pin any of them in `config/config.yaml` under `comfyui:` (`image_unet`, `image_clip`,
`image_clip_type`, `image_vae`, `video_unet`, `video_clip`, `video_vae`) if auto-detection
picks the wrong one.

> Turbo and distilled models are trained for very few steps at low CFG. Running them at
> SDXL's defaults (25 steps / CFG 7) wastes time and over-cooks the output, so step and
> CFG are matched to the checkpoint family automatically.

If a render fails, ComfyUI's own error is reported immediately — the failing node and its
message — rather than waiting out the poll budget. When the server is busy with other
work, the log reports the queue position.

### 3c. Checkpoint Notes (SD 1.5 / SDXL)

Set the engine under **⚙ → Image Engine**. For local ComfyUI, start it first; the agent
auto-detects a checkpoint and **prefers SDXL or Flux over SD 1.5**.

> **Model choice matters more than the prompt.** SD 1.5 is a 512px model — asking it for
> 1024×1024 makes it repeat the subject across the canvas, which comes out looking like a
> tiled asset sheet instead of one scene. Requests are automatically capped to a
> checkpoint's native range (768px for SD 1.5, 1344px for SDXL/Flux).

Pin a specific model in `config/config.yaml` if auto-detection picks the wrong one:
```yaml
comfyui:
  checkpoint: "sd_xl_base_1.0.safetensors"
  negative_prompt: ""       # blank uses the built-in anti sprite-sheet negative
  poll_attempts: 150        # 150 x 2s = 5 minutes of queue wait + render
```

If ComfyUI is shared with other work, renders queue behind it. The log reports the queue
position rather than failing silently, and falls back to the editorial card meanwhile:

```
ComfyUI prompt #374b3d95 is STILL QUEUED after 300s (3 job(s) ahead ...)
```

### 4. Running the Engine

**Windows**
```powershell
.\scripts\start.ps1          # build if needed, then start in the background
.\scripts\stop.ps1           # graceful agent halt, then shut down
```

**Linux / macOS**
```bash
./scripts/start.sh
./scripts/stop.sh
```

`start` runs its own **build phase**: it provisions the virtual environment, reinstalls dependencies whenever `requirements.txt` has changed, initializes the database, then waits until the server answers `/api/health` before reporting success. If startup fails it prints the server log instead of leaving you with a silent failure.

| Option | Windows | Linux/macOS | Purpose |
|---|---|---|---|
| Port | `-Port 8080` | `--port 8080` | Bind a different port |
| Host | `-BindHost 0.0.0.0` | `--host 0.0.0.0` | Expose beyond localhost |
| Foreground | `-Foreground` | `--foreground` | Run in this console, Ctrl+C to stop |
| Fast restart | `-SkipBuild` | `--skip-build` | Skip the build phase |
| Force stop | `-Force` | `--force` | Skip the graceful agent halt |

Then open 👉 **`http://127.0.0.1:8000`**

> The engine boots **HIBERNATING**. It performs no scans and posts nothing until you press **Execute Cycle** in the dashboard. Run it manually first to confirm the output looks right before considering any automation.

Manual start without the scripts still works:
```bash
python main.py                     # honours SMM_HOST / SMM_PORT
```

### 5. Rotating the Credential Master Key

`.env.secret` was tracked in git before `v1.1`, so that key must be treated as public. Rotate it:

```bash
python scripts/rotate_key.py --dry-run   # report what would change
python scripts/rotate_key.py             # rotate (asks to confirm; --yes to skip)
```

The tool decrypts every stored credential with the current key, generates a new 256-bit key, re-encrypts everything under it in one transaction, and archives the old key as `.env.secret.revoked-<timestamp>` (git-ignored). It refuses to run if any value fails to decrypt first, then verifies that the new key reads the data and the old key no longer can.

> Rotation does **not** rewrite git history — the old key remains in past commits. Rotation is what makes it worthless against your current data. Credentials that also exist at the provider (OpenAI, Tavily, platform tokens) should additionally be regenerated in those dashboards.

### 6. Publishing to Your Own Website (The Output Node)

Besides the social channels, posts can be published to your own site through a signed
REST API. The channel appears in **Channel Connections** as **The Output Node
(AutoAgent)**, and each row shows its target host so it is identifiable at a glance.

**Authentication — HMAC-SHA256, shared secret, identical on both ends:**

| Operation | Signed message | Sent as |
|---|---|---|
| Publish | the raw JSON request body | `X-Signature`; `timestamp` **inside the body** |
| Upload | `"<timestamp>:<filename>"` | `X-Signature` + `X-Timestamp` + `X-File-Name` |

**Setup:**

1. On the site, copy `api/config.local.php.example` → `api/config.local.php` and set
   `API_SECRET_KEY` (generate one with `php -r "echo bin2hex(random_bytes(32));"`).
   That file is git-ignored and denied over HTTP by `api/.htaccess`.
   An environment variable of the same name takes precedence.
2. In the dashboard, paste **the same key** into the channel's *Secret Key* field and set
   the *Base API URL* to the folder containing `publish.php`.
3. Press **Test Connection**.

The test performs a real signed request against `api/status.php` and reports storage
driver, writability and post count:

```
Connected to https://example.com/ai-news/api | storage sqlite OK (12 posts) | uploads writable
```

Failures are specific rather than generic: `401` names a key mismatch, `404` names a wrong
base URL, `5xx` quotes the server's own error, and an unreachable host says so.

> A `500 Server misconfigured: signing key unavailable` means `config.local.php` is
> missing or `API_SECRET_KEY` is unset **on the server** — the client is fine.

Markdown in the post body is converted to real HTML after escaping (so no markup can be
injected), a leading heading that merely repeats the stored title is dropped, and videos
are embedded with `<video controls>` rather than `<img>`.

### 7. Connecting Your Social Accounts

Open the dashboard, click the **⚙ gear** icon, then the **Channel Connections** tab. Each of the 9 channels has its own panel with the exact fields it needs, a link to its developer portal, and setup notes.

For each channel: fill the fields → **Save** → **Test Connection**. The test calls the channel's real API and reports the account it authenticated as, so you know the link works before anything is published.

| Channel | What you need | Where to get it |
|---|---|---|
| **X (Twitter)** | API key/secret + access token/secret | developer.x.com — app needs **Read and Write** |
| **LinkedIn** | OAuth access token + author URN | developer.linkedin.com — `w_member_social` product |
| **Reddit** | Client id/secret, username, password, subreddit | reddit.com/prefs/apps — app type **script** |
| **Telegram** | Bot token + chat/channel id | @BotFather; add the bot to your channel as admin |
| **Discord** | Webhook URL | Channel Settings → Integrations → Webhooks |
| **WordPress** | Site URL, username, application password | WP Admin → Users → Profile → Application Passwords |
| **Facebook** | Page id + page access token | developers.facebook.com — `pages_manage_posts` |
| **Instagram** | Business account id + token + public image URL | Requires a Business/Creator account linked to a Page |
| **YouTube** | API key + channel id (verification only) | console.cloud.google.com |

**How credentials are handled**
* Encrypted with your master key before being written to SQLite — the database never holds a plaintext token.
* Never sent back to the browser. The UI shows only a "stored" indicator; leaving a secret field blank keeps the existing value.
* Each channel has an on/off switch, and the toggle only turns green once credentials are actually stored.
* **Disconnect** erases that channel's credentials entirely.

**What actually gets posted**

Publishing runs only in **PROD** mode, only for approved drafts, and only to channels that are connected and enabled. A channel that fails is reported with the reason and the draft stays `approved` so you can retry.

> **YouTube Community posts cannot be automated.** Google publishes no API for creating them. The channel is included for verification and copy generation, but the post must be pasted into YouTube Studio by hand — the app will tell you this rather than silently claiming success.
>
> **Instagram** requires the image to be fetchable at a public URL; it cannot read a file from your machine. Set *Public Image Base URL* to somewhere your generated images are actually served.

### 8. Tavily is Optional

The engine runs fully without a Tavily key — `ResearchAgent` falls back to Google News RSS and the tech feeds, and `VerifierAgent` works from feed summaries. Adding a key improves discovery relevance and gives the verifier full article bodies to extract facts from.

To enable it, use any one of:
* **Dashboard** → *Provider Config* → *Tavily Research API Key* (stored encrypted — recommended)
* Environment variable `TAVILY_API_KEY`
* `tavily.api_key` in `config/config.yaml`

A missing, blank, placeholder, rate-limited or rejected key all degrade to the RSS path rather than failing the cycle. `GET /api/health` reports `"research_engine": "rss"` or `"tavily"` so you can confirm which is active.

---

## 🛠 Tech Stack & Tests

* **Language**: Python 3.12+
* **Web Framework**: FastAPI, Uvicorn
* **Database & ORM**: SQLite, SQLModel
* **Security**: Cryptography (Fernet symmetric key encryption)
* **Frontend**: HTML5, Vanilla JavaScript, TailwindCSS, JetBrains Mono
* **Research**: Tavily Search & Extract API (optional, with RSS fallback)
* **Image / Video**: Pillow (PIL), local ComfyUI (Z-Image, SDXL, Flux, LTX 2.5), Stability AI REST API
* **Testing**: PyTest — **147 tests**

```bash
python -m pytest tests/ -q
```

The suite is hermetic: it runs against a throwaway database and never calls a live model
or spends Tavily credits, so it cannot disturb your saved credentials or post history.

| Variable | Effect |
|---|---|
| `SMM_TEST_LIVE=1` | Use the real providers instead of the offline path |
| `SMM_TEST_USE_REAL_DB=1` | Run against the real database (destructive — fixtures delete rows) |
| `SMM_DB_PATH` | Point any run at a specific database file |
| `SMM_DISABLE_LLM` / `SMM_DISABLE_TAVILY` | Force the offline/RSS paths |

Coverage includes regression tests that pin the behaviour most likely to silently
regress: one render per story (never per post), posts held until their artwork exists,
published posts never re-sent, image prompts grounded in their own article, credentials
encrypted at rest and never returned over HTTP, and connection tests that fail on a bad
key rather than reporting a false green.

---

## 📄 Documentation & License

* **Product Requirements Document**: See [PRD.md](file:///d:/Projects/SocialMediaMonster/PRD.md)
* **Walkthrough & Log**: See [walkthrough.md](file:///C:/Users/iam/.gemini/antigravity-ide/brain/740dceb4-dccf-445d-9c8d-fbc87db74c14/walkthrough.md)
* Distributed under the MIT License.
