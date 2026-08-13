# Product Requirements Document (PRD)
## SocialMediaMonster: Autonomous Multi-Platform AI Content Engine & MCP Protocol Server

---

## 1. Executive Summary

**SocialMediaMonster** is an enterprise-grade, autonomous multi-agent content generation and publishing engine. It continuously monitors target internet feeds (RSS, Hacker News, ArXiv, TechCrunch), verifies emerging news, crafts platform-optimized copy across **9 social channels**, eliminates robotic AI markers, generates high-resolution 16-bit RPG visuals, and exposes a standardized **Model Context Protocol (MCP)** server interface.

---

## 2. Product Objectives & Core Capabilities

1. **Autonomous Research & Fact Verification**: Continuously scan target RSS feeds and tech sources, de-duplicate items, and verify technical facts.
2. **Multi-Platform Copywriting Engine**: Adapt content for 9 distinct channels:
   - **X (Twitter)**: Short punchy threads with hashtag optimization (<280 chars).
   - **Instagram**: Visual captions with aesthetic spacing and hashtag clusters.
   - **Facebook**: Conversational long-form post with engagement questions.
   - **YouTube Community**: Community update formatted with poll/callout style.
   - **Telegram**: Fast broadcast style with bold highlights and direct links.
   - **LinkedIn**: Executive post-mortems with structured bullet points and industry hashtags.
   - **Reddit**: Deep technical breakdowns formatted for dev subreddits (`r/LocalLLaMA`, `r/MachineLearning`).
   - **Discord**: Embedded markdown announcements with channel callouts.
   - **WordPress Blog**: Comprehensive article posts with structured subheadings.
3. **15-Band Fine-Tune Graphic Equalizer**: Precision sliders (-1.0 to +1.0) controlling Seriousness, Formality, Cynicism/Sarcasm, Technical Depth, Controversy Stance, Pacing, Emotional Warmth, Storytelling, Authority, Metaphors, Clickbait Energy, Tech Jargon, Action CTA, Humor Type, and Provocativeness.
4. **Author Voice Cloning**: Upload sample articles to extract exact sentence rhythms, vocabulary, and writing fingerprints.
5. **Dynamic 16-Bit RPG Writer Personas**: 6 retro pixel art author archetypes dynamically matching style vector sliders in real time.
6. **Traffic Controller Agent**: Bandwidth watchdog that halts unnecessary web scanning when pending post quotas are met.
7. **Abstract Provider API Layer**: Abstracted routing across Local Ollama, OpenAI, Google Gemini, Anthropic Claude, Stability AI, and ComfyUI Org. When no provider responds, an offline synthesizer reformats only the material already present in the prompt — it never fabricates story facts.
8. **Tavily Research Layer (optional)**: Tavily Search drives topic discovery with relevance scoring and a freshness window; Tavily Extract retrieves full article bodies for fact verification. It is never a hard dependency — an absent, blank, placeholder, rate-limited or rejected key degrades to Google News RSS and the cycle still completes.
9. **Security & Credential Encryption**: PBKDF2-HMAC-SHA256 derived Fernet credential encryption with a git-ignored master key (`.env.secret` or `SMM_MASTER_KEY`), plus an input/output payload sanitization gate.
10. **Google OAuth 2.0 Authentication**: Conditional remote access protection (bypassed on local desktop, enforced on remote deployment).
11. **MCP Protocol Server**: Standardized MCP tools (`/api/mcp/manifest` and `/api/mcp/call`).
12. **Temporal State Manager**: SQLite worker state checkpointing for continuous execution recovery.
13. **Explicit Draft Lifecycle**: `draft → humanized → approved | needs_review → published | rejected`. Each agent claims only its own stage, so no post is reprocessed on later cycles and no verified story is drafted twice.

---

## 3. Sub-Agent System Architecture

```
                                  ┌────────────────────────┐
                                  │   SuperAgent Master    │
                                  └───────────┬────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
         ┌────────────────────┐    ┌────────────────────┐    ┌────────────────────┐
         │ TrafficController  │    │   ResearchAgent    │    │   VerifierAgent    │
         │ (Quota Watchdog)   │    │  (RSS/Tech Scans)  │    │  (Fact Validator)  │
         └────────────────────┘    └────────────────────┘    └────────────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
         ┌────────────────────┐    ┌────────────────────┐    ┌────────────────────┐
         │    WriterAgent     │    │   HumanizerAgent   │    │   ValidatorAgent   │
         │ (15-Band Equalizer)│    │  (CTR / Zero-AI)   │    │(Final Content Mgr) │
         └────────────────────┘    └────────────────────┘    └────────────────────┘
                                              │
                                    ┌─────────┴─────────┐
                                    ▼                   ▼
                         ┌────────────────────┐┌────────────────────┐
                         │    VisualAgent     ││   PublisherAgent   │
                         │ (16-Bit ComfyUI)   ││(Multi-Channel Out)│
                         └────────────────────┘└────────────────────┘
```

---

## 4. Technical Specifications & Dependencies

* **Core Runtime**: Python 3.12+
* **Web Framework**: FastAPI & Uvicorn
* **Database / ORM**: SQLite & SQLModel
* **Security**: `cryptography` (Fernet symmetric key encryption over a PBKDF2-derived key)
* **Research**: Tavily Search & Extract API (optional; RSS fallback via feedparser)
* **Frontend Interface**: HTML5, Vanilla JavaScript, TailwindCSS, JetBrains Mono
* **Image Synthesis**: Local ComfyUI (SD1.5/SDXL), Stability AI REST API, ComfyUI Org API, PIL editorial card fallback
* **Testing Framework**: PyTest (45 tests, 100% pass rate), including regression coverage for content quality, image prompts and credential encryption

---

## 4a. Operational Lifecycle & Tooling

The project ships install / start / stop scripts for both platforms. `start` performs its
own build phase, so a clean checkout reaches a running server in one command.

| Action | Windows | Linux / macOS |
|---|---|---|
| Install | `.\scripts\install.ps1` | `./scripts/install.sh` |
| Build + Start | `.\scripts\start.ps1` | `./scripts/start.sh` |
| Stop | `.\scripts\stop.ps1` | `./scripts/stop.sh` |

* **Build phase** (inside `start`): provisions `.venv`, reinstalls dependencies when the
  SHA-256 of `requirements.txt` differs from the recorded value, and initializes the database.
* **Readiness gate**: `start` polls `GET /api/health` and only reports success once the
  server answers. On failure it prints the captured server log rather than exiting silently.
* **Process tracking**: PID and port are recorded in `.run/`; `stop` issues an in-app
  emergency agent halt before terminating, and falls back to the port listener if the PID
  file is stale. Both scripts are idempotent.
* **Binding**: overridable via `SMM_HOST` / `SMM_PORT` or the script flags.

**Execution model**: the engine boots HIBERNATING and runs the pipeline only on an explicit
manual trigger (dashboard **Execute Cycle**, `POST /api/trigger`, or the MCP
`trigger_full_cycle` tool). Scheduled autonomous execution is deferred until manual runs
are validated.

---

## 4b. Channel Connection & Authorization Layer

Each of the 9 channels is described by one declarative spec (`src/core/platforms.py`) that
drives the dashboard form, the encrypted store, the connection test and the publisher, so
adding a channel is a single-file change.

| Channel | Auth mechanism | Automated posting |
|---|---|---|
| X (Twitter) | OAuth 1.0a user context (HMAC-SHA1 signed) | Yes |
| LinkedIn | OAuth 2.0 bearer token (`w_member_social`) | Yes |
| Reddit | OAuth 2.0 password grant (script app) | Yes |
| Telegram | Bot token | Yes |
| Discord | Incoming webhook | Yes |
| WordPress | Application password (HTTP Basic) | Yes |
| Facebook Page | Graph API page access token | Yes |
| Instagram Business | Graph API two-step container publish | Yes, requires a public image URL |
| YouTube Community | OAuth 2.0 / API key | **No public API — manual posting** |

* **Storage**: credentials are Fernet-encrypted per field before serialization into SQLite.
  Non-secret fields (URLs, usernames, channel ids) remain readable so the form can repopulate.
* **Disclosure**: `GET /api/platforms` returns an `is_set` flag per field and never a secret
  value. A blank secret on save preserves the stored one.
* **Verification**: `POST /api/platforms/{name}/test` calls the channel's own API and records
  the authenticated account, timestamp and any error. Saving new credentials invalidates a
  previous verification result.
* **Gating**: the publisher requires `enabled AND configured AND can_post`. Failures never
  advance the draft, so a post remains `approved` and retryable.
* **Honesty constraints**: YouTube Community posting and Instagram-without-a-public-URL both
  return an explicit failure explaining the platform limitation rather than reporting success.

---

## 5. Security & Data Protection Standards

* **Credential Storage**: All API keys (OpenAI, Gemini, Anthropic, Stability AI, ComfyUI Org, Tavily, and platform tokens) are encrypted in SQLite using `SecurityManager` (`ENC:v2:` Fernet tokens; legacy `ENC:` records remain readable).
* **Master Key**: Held in `.env.secret` or `SMM_MASTER_KEY`. The file is git-ignored and must never be committed.
* **Key Rotation**: `scripts/rotate_key.py` performs an atomic rotation — it verifies every stored credential is readable, generates a new 256-bit key, re-encrypts all credentials under it in one transaction, archives the previous key, and asserts that the new key decrypts the data while the previous key does not. Because `.env.secret` was tracked prior to `v1.1`, that key is considered compromised; rotation renders it inert against current data without rewriting git history. Credentials that also live at the provider should be regenerated there as well.
* **Key Handling in the UI**: `GET /api/provider-config` returns only whether each credential is set, never the decrypted value. Submitting a blank field preserves the stored key instead of erasing it.
* **Payload Sanitization**: Automatic stripping of script/iframe tags, control chars, and prompt injection scaffolding on input, with provider token redaction on output.
* **Authentication**: Google OAuth 2.0 integration with conditional local bypass.

---

## 6. Success Metrics & Quality Control

* **CTR Score**: Heuristic estimate from headline signals (power words, numerals, punctuation). It is a ranking aid, not a measured click-through rate, and is computed from the copy that was actually produced.
* **AI Detection Score**: Heuristic estimate from trope frequency and sentence-length variance. Target < 0.35 at the QA gate; drafts above it are rewritten or held for review.
* **Factual Grounding**: Generated copy must derive only from the verified facts attached to the story. No cross-contamination between articles.
* **Visual Relevance**: Every `image_prompt` is derived from its own article's subject matter, and an `image_path` is recorded only when a decodable file exists on disk.
* **Network Traffic Efficiency**: 0 unrequested background network scans when in Hibernation mode.

> Note: the CTR and AI-detection figures are internal heuristics computed locally. They are not validated against a third-party AI detector or live engagement data.
