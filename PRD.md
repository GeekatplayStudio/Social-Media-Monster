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
7. **Abstract Provider API Layer**: Abstracted routing across Local Ollama, OpenAI, Google Gemini, Anthropic Claude, Stability AI, and ComfyUI Org.
8. **Extreme Security & Credential Encryption**: PBKDF2 AES-256/Fernet credential encryption (`.env.secret`) and payload sanitization gate.
9. **Google OAuth 2.0 Authentication**: Conditional remote access protection (bypassed on local desktop, enforced on remote deployment).
10. **MCP Protocol Server**: Standardized MCP tools (`/api/mcp/manifest` and `/api/mcp/call`).
11. **Temporal State Manager**: SQLite worker state checkpointing for continuous execution recovery.

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
* **Security**: PyCryptodome / Cryptography (Fernet symmetric key encryption)
* **Frontend Interface**: HTML5, Vanilla JavaScript, TailwindCSS, JetBrains Mono
* **Image Synthesis**: Local ComfyUI (SD1.5/SDXL), Stability AI REST API, ComfyUI Org API
* **Testing Framework**: PyTest (19 tests, 100% pass rate)

---

## 5. Security & Data Protection Standards

* **Credential Storage**: All API keys (OpenAI, Gemini, Anthropic, Stability AI, Twitter, LinkedIn, Reddit, Discord) are encrypted in SQLite using `SecurityManager` (`ENC:...` cipher).
* **Payload Sanitization**: Automatic stripping of script tags, control chars, and prompt injection attempts on input, with sensitive token redaction on output.
* **Authentication**: Google OAuth 2.0 integration with conditional local bypass.

---

## 6. Success Metrics & Quality Control

* **CTR Target**: >90% estimated click-through rate.
* **AI Detection Score**: <0.10 (Humanized, natural copy).
* **Network Traffic Efficiency**: 0 unrequested background network scans when in Hibernation mode.
