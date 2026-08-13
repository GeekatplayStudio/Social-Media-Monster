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
* **ResearchAgent**: Scans target internet queries and tech feeds (Google News, Hacker News, ArXiv, TechCrunch) with automatic de-duplication.
* **VerifierAgent**: Extracts clean, real technical facts from news stories without generic robotic boilerplate text.
* **WriterAgent**: Crafts platform-optimized posts across 9 supported channels (Twitter/X, Instagram, Facebook, YouTube Community, Telegram, LinkedIn, Reddit, Discord, WordPress Blog) using the active equalizer profile and voice sample.
* **HumanizerAgent**: Eliminates robotic AI phrasings, enhances natural pacing, and optimizes CTR & SEO scores.
* **ValidatorAgent**: Acts as the Final Content Manager QA Gate, verifying readability, tone consistency, and approval status before publishing.
* **VisualAgent**: Generates story-specific 16-bit RPG artwork supporting **Local ComfyUI (SD1.5/SDXL)**, **Stability AI Cloud API**, **ComfyUI Org Cloud API**, and **Ideogram Editorial Templates**.
* **PublisherAgent**: Manages multi-channel dispatch in production mode.
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

### 🔐 4. Extreme Security & Credential Encryption
* **AES-256 / Fernet Key Encryption**: All API credentials (OpenAI, Gemini, Anthropic, Stability AI, ComfyUI Org, Twitter, LinkedIn, Reddit, Discord) are encrypted before saving to SQLite (`ENC:...` cipher).
* **Payload Sanitization Gate**: Input payload script/injection stripping and output sensitive API key redaction.
* **Google OAuth 2.0 Auth**: Conditional remote protection (bypassed on local desktop, enforced on remote deployment).

### 🔌 5. Abstract Provider API Layer & Image Engine Selector
* Abstracted routing across Local Ollama, OpenAI (GPT-4o), Google Gemini (1.5/2.0), Anthropic Claude (3.5 Sonnet), Stability AI, ComfyUI Org, and Ideogram Templates.

### 🌐 6. Model Context Protocol (MCP) Protocol Server
* Exposes standardized MCP endpoints (`GET /api/mcp/manifest` & `POST /api/mcp/call`) allowing external AI agents to inspect status, trigger research scans, execute cycles, and manage draft queues.

---

## 🚀 Getting Started

### 1. Prerequisites
* **Python 3.12+**
* (Optional) **Local Ollama** or **ComfyUI** for local execution.

### 2. Installation
```bash
git clone https://github.com/GeekatplayStudio/Social-Media-Monster.git
cd Social-Media-Monster
pip install -r requirements.txt
```

### 3. Running the Engine
```bash
python main.py
```
Open your browser and navigate to:
👉 **`http://127.0.0.1:8000`**

---

## 🛠 Tech Stack & Tests

* **Language**: Python 3.12+
* **Web Framework**: FastAPI, Uvicorn
* **Database & ORM**: SQLite, SQLModel
* **Security**: Cryptography (Fernet symmetric key encryption)
* **Frontend**: HTML5, Vanilla JavaScript, TailwindCSS, JetBrains Mono
* **Image Processing**: Pillow (PIL), ComfyUI API, Stability AI REST API
* **Testing**: PyTest (19/19 tests passed cleanly)

---

## 📄 Documentation & License

* **Product Requirements Document**: See [PRD.md](file:///d:/Projects/SocialMediaMonster/PRD.md)
* **Walkthrough & Log**: See [walkthrough.md](file:///C:/Users/iam/.gemini/antigravity-ide/brain/740dceb4-dccf-445d-9c8d-fbc87db74c14/walkthrough.md)
* Distributed under the MIT License.
