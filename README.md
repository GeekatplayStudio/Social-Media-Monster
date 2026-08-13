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
* **VisualAgent**: Generates story-specific 16-bit RPG artwork supporting **Local ComfyUI (SD1.5/SDXL)**, **Stability AI Cloud API**, **ComfyUI Org Cloud API**, and an **Editorial Card** fallback. Prompts are built from the article's own subject matter, and a post only records an `image_path` once a decodable file exists on disk.
* **PublisherAgent**: Manages multi-channel dispatch in production mode. Channels still holding placeholder credentials are skipped rather than reported as published.
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
* **Google OAuth 2.0 Auth**: Conditional remote protection (bypassed on local desktop, enforced on remote deployment).

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

### 3. Running the Engine

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

### 4. Rotating the Credential Master Key

`.env.secret` was tracked in git before `v1.1`, so that key must be treated as public. Rotate it:

```bash
python scripts/rotate_key.py --dry-run   # report what would change
python scripts/rotate_key.py             # rotate (asks to confirm; --yes to skip)
```

The tool decrypts every stored credential with the current key, generates a new 256-bit key, re-encrypts everything under it in one transaction, and archives the old key as `.env.secret.revoked-<timestamp>` (git-ignored). It refuses to run if any value fails to decrypt first, then verifies that the new key reads the data and the old key no longer can.

> Rotation does **not** rewrite git history — the old key remains in past commits. Rotation is what makes it worthless against your current data. Credentials that also exist at the provider (OpenAI, Tavily, platform tokens) should additionally be regenerated in those dashboards.

### 5. Tavily is Optional

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
* **Image Processing**: Pillow (PIL), ComfyUI API, Stability AI REST API
* **Testing**: PyTest — 45 tests, including a regression suite pinning the content-quality fixes

```bash
python -m pytest tests/ -q
```

---

## 📄 Documentation & License

* **Product Requirements Document**: See [PRD.md](file:///d:/Projects/SocialMediaMonster/PRD.md)
* **Walkthrough & Log**: See [walkthrough.md](file:///C:/Users/iam/.gemini/antigravity-ide/brain/740dceb4-dccf-445d-9c8d-fbc87db74c14/walkthrough.md)
* Distributed under the MIT License.
