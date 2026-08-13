<p align="center">
  <img src="assets/monster_logo.jpg" width="220" alt="SocialMediaMonster Logo" style="border-radius: 16px;">
</p>

<h1 align="center">SocialMediaMonster</h1>
<p align="center">
  <strong>Autonomous Multi-Platform AI Content Engine & MCP Protocol Server</strong>
</p>

---

## 📌 Overview

**SocialMediaMonster** is a state-of-the-art, autonomous multi-agent content generation and publishing engine. It continuously scans the internet (RSS feeds, Google News, Hacker News, ArXiv, TechCrunch), verifies emerging trends, drafts platform-tailored content across **9 social channels**, optimizes copy for high CTR with zero AI detection markers, generates striking visual artwork, and exposes a standardized **Model Context Protocol (MCP) Server**.

It features a high-contrast corporate control dashboard equipped with a **15-Band Visual Graphic Equalizer**, **Author Voice Cloning**, **Dynamic 16-Bit Pixel Art Writer Personas**, **Abstract LLM/Visual Provider Layer**, **Temporal-like Worker State Recovery**, and an **Emergency Stop Controller**.

---

## ⚡ Key Features & Technologies

### 🧠 1. Multi-Agent Autonomous Architecture
* **ResearchAgent**: Scans target internet queries and tech feeds (Google News, Hacker News, ArXiv, TechCrunch) with automatic de-duplication.
* **VerifierAgent**: Validates source credibility and cross-references trend items before copywriting.
* **WriterAgent**: Crafts platform-optimized posts across 9 supported channels (Twitter/X, Instagram, Facebook, YouTube Community, Telegram, LinkedIn, Reddit, Discord, WordPress Blog) using the active equalizer profile and voice sample.
* **HumanizerAgent**: Eliminates robotic AI phrasings, enhances natural pacing, and optimizes CTR & SEO scores.
* **ValidatorAgent**: Performs 2nd-pass QA auditing, verifying text tone, formatting, and prompt boundaries.
* **VisualAgent**: Generates high-resolution visuals supporting **Local ComfyUI (SD1.5/SDXL)**, **Stability AI Cloud API**, **ComfyUI Org Cloud API**, and **Ideogram Editorial Templates**.
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

### 🔌 4. Abstract Provider API Layer
* Abstracted routing for text generation and reasoning across:
  * **Local Ollama** (Llama 3.3, Qwen 2.5, Mistral)
  * **OpenAI API** (GPT-4o / DALL-E 3)
  * **Google Gemini API** (1.5 Flash / 2.0)
  * **Anthropic Claude API** (3.5 Sonnet)
  * **Custom Endpoints**

### 🖼 5. Multi-Engine Image Generation Selector
* Instant UI toggle buttons for image generation engines:
  * **Local ComfyUI** (`http://127.0.0.1:8188`) with automatic SD1.5/SDXL model detection & history polling image downloader.
  * **Stability AI Cloud API** (`https://api.stability.ai`)
  * **ComfyUI Org Cloud API** (`https://api.comfy.org`)
  * **Ideogram Editorial Template Engine**

### 🌐 6. Model Context Protocol (MCP) Protocol Server
* Exposes standardized MCP endpoints (`GET /api/mcp/manifest` & `POST /api/mcp/call`) allowing external AI agents to control the system:
  * `get_system_status`: Inspect mode, active persona, and anti-spam schedule.
  * `trigger_scan`: Trigger internet research scan.
  * `trigger_full_cycle`: Execute complete multi-agent pipeline cycle.
  * `list_posts`: Fetch drafted multi-platform posts.

### 🔁 7. Temporal-Like Persistent State Restoration Engine
* SQLite state checkpointing engine (`TemporalStateManager`) recording pipeline stages (`RESEARCH`, `VERIFICATION`, `COPYWRITING`, `QA_VALIDATION`, `VISUAL_GENERATION`, `PUBLISHING`).
* If the server restarts or the webpage closes, worker state is restored seamlessly.

### 🛑 8. Emergency Stop & Hibernation
* Server initializes strictly in **`HIBERNATING (IDLE)`** mode with zero unrequested background network activity.
* Header **"STOP ALL AGENTS"** red button (`POST /api/stop`) immediately halts all background agent operations.

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

## 🛠 Tech Stack

* **Language**: Python 3.12+
* **Web Framework**: FastAPI, Uvicorn
* **Database & ORM**: SQLite, SQLModel
* **Frontend**: HTML5, Vanilla JavaScript, TailwindCSS, JetBrains Mono
* **Image Processing**: Pillow (PIL), ComfyUI API, Stability AI REST API
* **Testing**: PyTest (15/15 test modules passed)

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
