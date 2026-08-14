# Technical Specification: Image/Video Mode Switching & Video Template Overlay Engine

## 1. Executive Summary & Core Objectives

This document defines the architectural specification for expanding **SocialMediaMonster** from static image generation into a multi-modal media engine supporting **Image**, **Video**, and **Dual (Both)** media modes.

### Key Objectives:
1. **Dynamic Media Mode Selection**: Provide configuration switches (`active_media_mode`: `image`, `video`, `both`) accessible via system settings and dashboard controls.
2. **Single Master Video Distribution Model**: Generate **exactly one master video per verified news story**, which is attached to all 9 target social channel drafts (X, Instagram, Facebook, YouTube, Telegram, LinkedIn, Reddit, Discord, WordPress). This minimizes compute/API costs while ensuring cross-platform brand visual consistency.
3. **Video Template Overlay Engine**: Compositing layer using FFmpeg/MoviePy to place customizable templates over raw videos, including audio tracks (background music + voiceover TTS), dynamic text overlays (headlines, lower thirds, subtitle captions), retro 16-bit RPG UI frames, and brand watermarks.
4. **Abstract Provider API Layer Interface**: Define a modular `BaseVideoProvider` interface to cleanly isolate video generation engines (local ComfyUI AnimateDiff/Wan2.1/CogVideoX/LTX-Video, cloud APIs like Runway, Luma, Kling, Stability Video, and deterministic FFmpeg slide fallbacks).

---

## 2. Architecture & Data Flow

### 2.1 Single Master Video Lifecycle

```
                                  ┌──────────────────────────────┐
                                  │   VerifiedNews Story Item    │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │    VisualAgent / VideoEngine │
                                  │  (Generates 1 Master Video)  │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │ Video Template Overlay Engine│
                                  │ (Audio + Text + RPG Frame)   │
                                  └──────────────┬───────────────┘
                                                 │
            ┌────────────────────────────────────┼────────────────────────────────────┐
            ▼                                    ▼                                    ▼
┌─────────────────────────┐          ┌─────────────────────────┐          ┌─────────────────────────┐
│ Draft 1: X (Twitter)    │          │ Draft 2: Instagram      │          │ Draft 3: YouTube        │
│ media_type = "video"    │          │ media_type = "video"    │          │ media_type = "video"    │
│ media_path = master.mp4 │          │ media_path = master.mp4 │          │ media_path = master.mp4 │
└─────────────────────────┘          └─────────────────────────┘          └─────────────────────────┘
            │                                    │                                    │
            └────────────────────────────────────┼────────────────────────────────────┘
                                                 ▼
                                (All 9 Social Channel Link Drafts)
```

1. **Trigger**: Pipeline reaches `VISUAL_GENERATION` stage. `VisualAgent` checks `active_media_mode`.
2. **Story Grouping**: `VisualAgent` groups pending drafts by `verified_news_id`.
3. **Master Video Generation**: For each story group needing video, the active `VideoProvider` generates 1 master raw video asset stored in `data/outputs/videos/raw_story_{verified_news_id}.mp4`.
4. **Template Compositing**: The **Video Template Overlay Engine** takes the raw video and applies the configured preset (e.g. `retro_16bit_rpg`), injecting background audio, story text overlays, subtitle tracks, and pixel art borders. The output is saved to `data/outputs/videos/master_story_{verified_news_id}.mp4`.
5. **Draft Attachment**: `VerifiedNews.master_video_path` is updated, and every `PostDraft` under that story receives `media_type="video"` and `media_path="master_story_{verified_news_id}.mp4"`.

---

## 3. Data Model & Database Schema Extensions

### 3.1 `SystemSetting` Configuration Keys

| Key Name | Values | Default | Description |
|---|---|---|---|
| `active_media_mode` | `"image"`, `"video"`, `"both"` | `"image"` | Controls active media asset generation mode across cycles |
| `active_video_provider` | `"comfyui_video"`, `"runway"`, `"luma"`, `"kling"`, `"stability_video"`, `"ffmpeg_template"` | `"ffmpeg_template"` | Selected video synthesis provider |
| `video_template_preset` | `"retro_16bit_rpg"`, `"cyberpunk_hud"`, `"minimal_editorial"`, `"news_break"` | `"retro_16bit_rpg"` | Active frame/overlay design preset |
| `video_aspect_mode` | `"single_master"`, `"adaptive_multi_aspect"` | `"single_master"` | Direct single master sharing vs auto-cropped aspect variants |

### 3.2 SQLModel Schema Updates (`src/core/models.py`)

```python
class VerifiedNews(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trend_id: int = Field(foreign_key="trenditem.id")
    headline: str
    verified_facts: str
    source_reliability_score: float = 1.0
    key_takeaways: str
    created_at: datetime = Field(default_factory=datetime.now)
    status: str = "verified"
    # New Video Fields:
    master_video_path: Optional[str] = None
    master_video_prompt: Optional[str] = None

class PostDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    verified_news_id: int = Field(foreign_key="verifiednews.id")
    platform: str
    persona_key: str
    headline: str
    content: str
    image_prompt: Optional[str] = None
    image_path: Optional[str] = None
    seo_keywords: Optional[str] = None
    ctr_score: float = 0.0
    ai_detection_score: float = 0.0
    status: str = "draft"
    published_at: Optional[datetime] = None
    external_post_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    # New Multi-Media Fields:
    media_type: str = "image"  # "image", "video", "none"
    media_path: Optional[str] = None
```

---

## 4. Video Template Overlay Engine Architecture

The template overlay engine operates deterministically using FFmpeg filtergraphs and PIL raster overlays.

```
       Input Files:
       ┌────────────────────────┐
       │ 1. Raw AI Video        │
       │ 2. Background Audio    │
       │ 3. Subtitle / SRT File │
       │ 4. Frame Overlay PNG   │
       └───────────┬────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│             FFmpeg Filtergraph Pipeline          │
│                                                  │
│  [0:v] scale=1280:720 [base];                    │
│  [1:v] overlay=0:0 [framed];                     │
│  [framed] drawtext=text='HEADLINE':... [texted]; │
│  [texted] subtitles=captions.srt [vfinal];       │
│                                                  │
│  [2:a] volume=0.35 [bgm];                        │
│  [3:a] volume=1.0 [tts];                         │
│  [bgm][tts] sidechaincompress... [afinal]        │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
       Output Master Video MP4
```

### 4.1 Overlay Components

1. **Music / Audio Layer**:
   - **Background Track**: Looped ambient synth / 16-bit retro soundtrack (`assets/audio/retro_theme.mp3`).
   - **TTS Audio Track**: Synthesized voice reading story key takeaways (`gTTS` or local Edge-TTS).
   - **Ducking Filter**: Automatic sidechain compression lowering music volume by 12dB whenever voiceover is active.

2. **Text / Subtitle Layer**:
   - **Headline Banner**: Top/Bottom text box rendered with retro arcade typography (JetBrains Mono / Press Start 2P).
   - **Subtitles**: Soft/hard-burned SRT subtitles styled with white text, black outline, and highlight color on current spoken word.
   - **Lower Third**: Persona badge showing the active writer persona (e.g. "Tech Visionary & AI Insider").

3. **Frame & Border Layer**:
   - **Retro 16-Bit RPG Frame**: Branded PNG border overlay featuring pixel art corner rivets, CRT scanline overlay, and lower status bar.
   - **Brand Watermark**: Corner logo stamp (`assets/templates/watermark_monster.png`).

---

## 5. Abstract Provider API Layer Interface (`BaseVideoProvider`)

To ensure modularity for future API implementations, all video providers must adhere to the abstract interface contract defined below:

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class VideoProviderResult:
    def __init__(self, ok: bool, output_path: str = "", message: str = "", provider_name: str = ""):
        self.ok = ok
        self.output_path = output_path
        self.message = message
        self.provider_name = provider_name

class BaseVideoProvider(ABC):
    """Abstract Base Class for Video Generation Providers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def generate_video(
        self,
        prompt: str,
        output_path: str,
        width: int = 1280,
        height: int = 720,
        duration_seconds: int = 5,
        fps: int = 24,
        aspect_ratio: str = "16:9"
    ) -> VideoProviderResult:
        """
        Generates a raw video file from a text prompt and saves to output_path.
        Must return a VideoProviderResult indicating success or failure.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Checks whether the backend provider service/API key is available and reachable.
        """
        pass
```

### 5.1 Provider Architecture Hierarchy

- `BaseVideoProvider` (Abstract Contract)
  - `FFmpegTemplateVideoProvider`: Deterministic fallback that generates dynamic animated video slides with audio/text overlays when no AI provider is available.
  - `ComfyUIVideoProvider`: Local AnimateDiff / Wan2.1 / CogVideoX / LTX-Video workflow runner using local ComfyUI API endpoints.
  - `CloudVideoProvider`: Generic driver for cloud video APIs (Runway Gen-3, Luma Dream Machine, Kling AI, Stability Video).

---

## 6. Social Media Channel Media Attachment Matrix

When `PublisherAgent` dispatches drafts to platform channels, the `media_path` is uploaded according to channel capabilities:

| Social Channel | Video Support | Upload Transport Mechanism | Max Video Size |
|---|---|---|---|
| **X (Twitter)** | Supported | Chunked Upload (`INIT -> APPEND -> FINALIZE`) via API v1.1/v2 | 512 MB / 140s |
| **Instagram** | Supported | Reels Container creation (`POST /{ig-user-id}/media?media_type=REELS`) | 100 MB / 60s |
| **Facebook Page** | Supported | Graph API Video Endpoint (`POST /{page-id}/videos`) | 1 GB / 20min |
| **YouTube** | Supported | YouTube Data API v3 Resumable Upload (`POST /upload/youtube/v3/videos`) | 128 GB |
| **Telegram** | Supported | Bot API `sendVideo` (`POST /bot{token}/sendVideo`) | 50 MB |
| **LinkedIn** | Supported | Assets API 3-step register & upload (`POST /v2/assets?action=registerUpload`) | 200 MB / 10min |
| **Reddit** | Supported | Media submit endpoint (`POST /api/submit` with `kind=video`) | 1 GB |
| **Discord** | Supported | Webhook multipart file upload (`file` attachment) | 25 MB (standard) |
| **WordPress** | Supported | REST API Media Upload (`POST /wp/v2/media`) & embed in block | 64 MB |

---

## 7. Operational Workflow Summary

1. User or SuperAgent sets `active_media_mode = "video"` (or `"both"`).
2. `VisualAgent` triggers story-level video generation.
3. 1 master video is synthesized by the active `VideoProvider`.
4. `VideoTemplateOverlayEngine` applies audio ducking, headlines, SRT subtitles, and the retro 16-bit RPG UI frame overlay.
5. Master video is saved to `data/outputs/videos/master_story_{id}.mp4` and attached to all 9 post drafts for that story.
6. `PublisherAgent` publishes the video asset directly to social channel endpoints.
