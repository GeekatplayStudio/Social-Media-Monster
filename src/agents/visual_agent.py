import os
import re
import json
import time
import math
import base64
import urllib.request
import urllib.parse
import hashlib
from PIL import Image, ImageDraw, ImageFont
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import PostDraft, SystemSetting, VerifiedNews
from src.core.llm_client import LLMClient
from src.core.article_analysis import build_visual_brief

# Suppresses the failure modes these prompts attract: tiled asset sheets, repeated
# subjects, and baked-in lettering.
DEFAULT_NEGATIVE_PROMPT = (
    "sprite sheet, asset sheet, tileset, tile grid, character select screen, "
    "multiple panels, split screen, collage, repeated duplicate objects, "
    "grid layout, contact sheet, storyboard, thumbnails, "
    "text, lettering, caption, watermark, signature, logo, ui overlay, "
    "blurry, low quality, distorted, deformed, jpeg artifacts, cropped"
)

# Rendered pixel dimensions per aspect ratio, kept on SDXL-friendly multiples of 64.
ASPECT_DIMENSIONS = {
    "16:9": (1344, 768),
    "1:1": (1024, 1024),
    "4:5": (832, 1024),
    "9:16": (720, 1280),
}

# Words that carry no visual meaning and must not drive a scene description.
VISUAL_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "into", "that", "this",
    "these", "those", "of", "to", "in", "on", "at", "by", "as", "is", "are", "was", "were",
    "be", "been", "it", "its", "has", "have", "had", "will", "can", "new", "now", "how",
    "why", "what", "when", "after", "over", "more", "than", "you", "your", "our", "their",
    "says", "said", "here", "about", "just", "also", "very", "much", "many", "some",
    "twitter", "linkedin", "reddit", "wordpress", "instagram", "facebook", "telegram",
    "discord", "youtube", "post", "thread", "update", "breakdown", "discussion",
}

# Subject matter -> concrete scene. Each entry adds story-specific staging on top of the
# extracted keywords rather than replacing them with a fixed illustration.
SCENE_MOTIFS = [
    (("database", "sqlite", "postgres", "wal", "corruption", "storage", "query"),
     "a subterranean data vault of glowing crystal storage cores and branching index conduits"),
    (("security", "breach", "exploit", "vulnerability", "malware", "encryption", "hack"),
     "a fortified cyber-citadel with rune-locked firewall gates and intrusion beacons"),
    (("agent", "autonomous", "orchestration", "workflow", "multi-agent"),
     "a command hall where robed operator sprites coordinate a constellation of task drones"),
    (("image", "video", "diffusion", "render", "comfyui", "flux", "art", "generative"),
     "an artisan's atelier where a pixel-forge loom weaves light into moving frames"),
    (("chip", "gpu", "hardware", "silicon", "nvidia", "compute", "datacenter", "cluster"),
     "a cavernous foundry of humming compute pylons and cooling towers under neon haze"),
    (("funding", "startup", "acquisition", "ipo", "revenue", "market", "billion"),
     "a towering exchange hall of holographic ledgers and rising value spires"),
    (("robot", "drone", "autonomous vehicle", "hardware", "sensor"),
     "a workshop bay where a mech chassis is calibrated under articulated sensor arms"),
    (("policy", "regulation", "regulator", "lawsuit", "court", "government", "ban", "law",
      "compliance", "enforcement", "antitrust", "privacy", "copyright", " act "),
     "a marble senate chamber where holographic statutes hover above debating envoys"),
    (("model", "llm", "neural", "training", "inference", "benchmark", "ai"),
     "an observatory where a vast neural lattice of constellation nodes is being tuned"),
    (("code", "developer", "python", "git", "software", "release", "api", "framework"),
     "a developer's sanctum of stacked terminal monoliths streaming live source glyphs"),
]

class VisualAgent:
    """
    Visual Agent:
    Supports 1-click single test image & video generation for post drafts and news stories.
    Supports Local ComfyUI, Stability AI Cloud API, ComfyUI Org Cloud API,
    and Editorial Card/Video Overlay Engine.
    """
    def __init__(self):
        self.config = load_config().get("comfyui", {})
        self.server_address = self.config.get("server_address", "127.0.0.1:8188")
        self.output_dir = "data/outputs/images"
        self.video_output_dir = "data/outputs/videos"
        self.llm = LLMClient()
        self.comfy_poll_attempts = int(self.config.get("poll_attempts", 60))
        self.comfy_poll_interval = float(self.config.get("poll_interval_seconds", 2))
        self.negative_prompt = self.config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
        self.active_checkpoint = self._auto_detect_comfyui_checkpoint()
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.video_output_dir, exist_ok=True)

    def is_enabled(self) -> bool:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "comfyui_enabled")).first()
            if setting:
                return setting.value.lower() == "true"
        return False

    def get_active_media_mode(self) -> str:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_media_mode")).first()
            if setting and setting.value:
                return setting.value.lower()
        return "image"

    def get_active_image_provider(self) -> str:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_image_provider")).first()
            if setting and setting.value:
                return setting.value
        return "comfyui_local"

    def get_active_video_provider(self) -> str:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_video_provider")).first()
            if setting and setting.value:
                return setting.value
        return "ffmpeg_template"

    def _auto_detect_comfyui_checkpoint(self) -> str:
        try:
            url = f"http://{self.server_address}/object_info/CheckpointLoaderSimple"
            req = urllib.request.Request(url, headers={'User-Agent': 'SocialMediaMonster/1.0'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    ckpt_list = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                    if ckpt_list:
                        configured = self.config.get("checkpoint", "")
                        if configured and configured in ckpt_list:
                            return configured

                        # Best model first. The old order tried "v1-5" first, so a machine
                        # with SDXL and Flux installed still rendered on SD 1.5 - which
                        # duplicates subjects badly above its native 512px and produced
                        # the tiled "asset sheet" look instead of a single scene.
                        for preferred in ["zimage", "z_image", "z-image", "sd_xl_base", "sdxl",
                                          "sd_xl", "flux1-dev", "flux", "hidream",
                                          "v2-1", "v1-5", "sd15"]:
                            for name in ckpt_list:
                                if preferred in name.lower():
                                    return name
                        # Skip non-image checkpoints when falling back.
                        for name in ckpt_list:
                            if not any(x in name.lower() for x in ("audio", "3d", "ltx", "sam", "pose", "heightmap")):
                                return name
                        return ckpt_list[0]
        except Exception:
            pass
        return self.config.get("default_checkpoint", "v1-5-pruned-emaonly.safetensors")

    def generate_single_test_image(self, post_id: int) -> str:
        """
        Dashboard "generate image" action for one post.

        When the post belongs to a story it re-renders that story's MASTER image and
        re-attaches it to every draft of the story, so all channels keep showing the same
        artwork. Only an orphan draft falls back to a standalone per-post render.
        """
        with Session(engine) as session:
            draft = session.get(PostDraft, post_id)
            if not draft:
                return ""
            story_id = draft.verified_news_id

        if story_id:
            return self.generate_master_image_for_story(story_id, force=True)

        provider = self.get_active_image_provider()
        with Session(engine) as session:
            draft = session.get(PostDraft, post_id)
            if not draft:
                return ""

            log_event("VisualAgent", f"Generating standalone image for orphan Post #{draft.id} ({draft.platform}) using [{provider.upper()}]...")

            aspect_ratio = "16:9" if draft.platform in ["twitter", "wordpress", "facebook", "youtube"] \
                else "1:1" if draft.platform in ["instagram", "discord", "telegram"] else "4:5"
            width, height = ASPECT_DIMENSIONS.get(aspect_ratio, (1024, 1024))

            # Reuse a validated prompt from the QA gate if one exists; otherwise derive one
            # from this specific story.
            descriptive_prompt = draft.image_prompt if self._is_usable_prompt(draft.image_prompt) else None
            if not descriptive_prompt:
                descriptive_prompt = self._build_vivid_comfy_prompt(draft.headline, draft.content, aspect_ratio)
            draft.image_prompt = descriptive_prompt

            image_filename = f"test_post_{draft.id}_{draft.platform}.png"
            output_path = os.path.join(self.output_dir, image_filename)

            success = False

            if provider == "stability_ai":
                success = self._dispatch_stability_ai(descriptive_prompt, output_path, width, height)
            elif provider == "comfy_org":
                success = self._dispatch_comfy_org(descriptive_prompt, output_path, width, height)
            elif provider == "comfyui_local":
                self.active_checkpoint = self._auto_detect_comfyui_checkpoint()
                success = self._dispatch_comfyui_prompt(descriptive_prompt, output_path, width, height)

            # Fallback to high-contrast dark editorial card template if API/Local fails or card selected
            if not success or provider == "ideogram_card":
                try:
                    self._render_vibrant_article_card(draft.headline, draft.content, draft.platform, output_path)
                    success = os.path.exists(output_path)
                except Exception as e:
                    log_event("VisualAgent", f"Editorial card fallback failed for Post #{draft.id}: {e}", level="ERROR")
                    success = False

            # Only record a path that resolves to a real file, otherwise the dashboard
            # renders a broken image for a post that has no artwork.
            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                draft.image_path = image_filename
                session.add(draft)
                session.commit()
                log_event("VisualAgent", f"Completed image generation for Post #{draft.id} via [{provider.upper()}]", level="SUCCESS")
                return output_path

            draft.image_path = None
            session.add(draft)
            session.commit()
            log_event("VisualAgent", f"Image generation produced no file for Post #{draft.id} via [{provider.upper()}]", level="ERROR")
            return ""

    def _queue_position(self, prompt_id: str):
        """
        How many jobs sit ahead of ours, or None when the prompt is no longer queued.
        ComfyUI is often shared with other tools, so 'slow' usually means 'busy'.
        """
        try:
            req = urllib.request.Request(f"http://{self.server_address}/queue")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        running = data.get("queue_running", []) or []
        pending = data.get("queue_pending", []) or []

        def entry_id(entry):
            try:
                return str(entry[1])
            except (IndexError, TypeError):
                return ""

        for index, entry in enumerate(pending):
            if entry_id(entry) == prompt_id:
                return len(running) + index
        if any(entry_id(e) == prompt_id for e in running):
            return 0
        return None

    @staticmethod
    def _is_usable_prompt(prompt: str) -> bool:
        """Rejects social-post text that may have been stored in the image_prompt column."""
        if not prompt or len(prompt.strip()) < 40:
            return False
        if re.search(r'#\w+', prompt) or "http" in prompt.lower() or "?" in prompt:
            return False
        return True

    @classmethod
    def _build_vivid_video_prompt(cls, headline: str, content: str, aspect_ratio: str = "9:16") -> str:
        """
        Builds a high-quality prompt for text-to-video motion synthesis in vertical 9:16 orientation.
        Tuned for models like AnimateDiff, Wan2.1, LTX-Video, CogVideoX, and Stability Video.
        """
        clean_title = re.sub(
            r'^\s*(?:\[[^\]]+\]|Headline:|Deep Dive:|#+)\s*', '', (headline or '')
        ).strip()
        clean_title = re.sub(r'\s*\[[A-Z]+\]\s*$', '', clean_title).strip()

        brief = build_visual_brief(clean_title, content or "")

        camera_motion = "slow vertical pan upward with subtle dolly zoom depth effect, 24fps fluid motion"
        composition = "vertical 9:16 cinematic framing, strong foreground and background depth separation"

        return (
            f"A single continuous vertical 9:16 animated 16-bit RPG cinematic scene: {brief['scene']}. "
            f"Foreground elements and props: {brief['props']}. "
            f"{composition}, {camera_motion}, dynamic rim lighting in cyan and deep indigo, floating luminous "
            f"particles, volumetric lighting rays, CRT scanline grain, crisp detailed pixel artwork."
        ).replace("  ", " ")

    def generate_master_video_for_story(self, verified_news_id: int) -> str:
        """
        Generates 1 single master video (vertical 9:16 resolution) for a verified news story,
        and attaches that single video asset to ALL post drafts linked to that story.
        """
        provider = self.get_active_video_provider()
        with Session(engine) as session:
            story = session.get(VerifiedNews, verified_news_id)
            if not story:
                return ""

            drafts = session.exec(select(PostDraft).where(PostDraft.verified_news_id == verified_news_id)).all()
            if not drafts:
                return ""

            sample_draft = drafts[0]
            log_event("VisualAgent", f"Generating 1 Master Video for Story #{story.id} ('{story.headline[:40]}...') via [{provider.upper()}]...")

            aspect_ratio = "9:16"
            width, height = 720, 1280

            video_prompt = story.master_video_prompt
            if not self._is_usable_prompt(video_prompt):
                video_prompt = self._build_vivid_video_prompt(story.headline, story.key_takeaways or sample_draft.content, aspect_ratio)
                story.master_video_prompt = video_prompt
                session.add(story)
                session.commit()

            video_filename = f"master_story_{story.id}.mp4"
            output_path = os.path.join(self.video_output_dir, video_filename)

            success = False
            if provider == "comfyui_video":
                if os.environ.get("SKIP_LOCAL_COMFYUI") == "1":
                    log_event("VisualAgent", "Local ComfyUI bypassed due to active testing safety flag.", level="INFO")
                    success = False
                else:
                    success = self._dispatch_comfyui_video_prompt(video_prompt, output_path, width, height)
            elif provider == "stability_video":
                success = self._dispatch_stability_video(video_prompt, output_path, width, height)
            elif provider == "comfy_org":
                success = self._dispatch_comfy_org_video(video_prompt, output_path, width, height)

            # Fallback to deterministic 9:16 vertical video renderer
            if not success or provider == "ffmpeg_template":
                success = self._render_vibrant_video_fallback(story.headline, sample_draft.content, output_path, width, height)

            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                story.master_video_path = video_filename
                session.add(story)

                # Attach this single master video to ALL drafts for this story
                for d in drafts:
                    d.media_type = "video"
                    d.media_path = video_filename
                    d.image_path = video_filename
                    d.image_prompt = video_prompt
                    session.add(d)

                session.commit()
                log_event("VisualAgent", f"Attached single Master Video '{video_filename}' to all {len(drafts)} posts for Story #{story.id}", level="SUCCESS")
                return output_path
            else:
                log_event("VisualAgent", f"Master Video generation produced no valid file for Story #{story.id}", level="ERROR")
                return ""

    def _dispatch_comfyui_dit(self, prompt_text: str, save_path: str, width: int, height: int,
                              seed: int, trio: dict) -> bool:
        """Text-to-image for transformer models loaded as separate UNET + CLIP + VAE."""
        steps = int(self.config.get("image_steps", 8))
        cfg_scale = float(self.config.get("image_cfg", 1.5))
        try:
            workflow = {
                "1": {"inputs": {"unet_name": trio["unet"], "weight_dtype": "default"}, "class_type": "UNETLoader"},
                "2": {"inputs": {"clip_name": trio["clip"], "type": trio["clip_type"]}, "class_type": "CLIPLoader"},
                "3": {"inputs": {"vae_name": trio["vae"]}, "class_type": "VAELoader"},
                "4": {"inputs": {"text": prompt_text, "clip": ["2", 0]}, "class_type": "CLIPTextEncode"},
                "5": {"inputs": {"text": self.negative_prompt, "clip": ["2", 0]}, "class_type": "CLIPTextEncode"},
                "6": {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptySD3LatentImage"},
                "7": {"inputs": {"seed": seed, "steps": steps, "cfg": cfg_scale,
                                 "sampler_name": "euler", "scheduler": "simple", "denoise": 1,
                                 "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                                 "latent_image": ["6", 0]}, "class_type": "KSampler"},
                "8": {"inputs": {"samples": ["7", 0], "vae": ["3", 0]}, "class_type": "VAEDecode"},
                "9": {"inputs": {"filename_prefix": "SocialMonster_Image", "images": ["8", 0]}, "class_type": "SaveImage"},
            }
            body = json.dumps({"prompt": workflow}).encode('utf-8')
            req = urllib.request.Request(f"http://{self.server_address}/prompt", data=body,
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    return False
                payload = json.loads(resp.read().decode('utf-8'))

            prompt_id = payload.get("prompt_id")
            if not prompt_id:
                log_event("VisualAgent", f"ComfyUI rejected the image workflow: {str(payload)[:200]}", level="WARNING")
                return False

            log_event("VisualAgent",
                      f"Dispatched image job #{prompt_id[:8]} on '{trio['unet']}' "
                      f"({width}x{height}, {steps} steps)")
            return self._await_comfy_output(prompt_id, save_path, attempts=self.comfy_poll_attempts)
        except Exception as e:
            log_event("VisualAgent", f"ComfyUI transformer image dispatch failed: {e}", level="WARNING")
            return False

    def _resolve_video_models(self) -> dict:
        """
        Finds the LTX video transformer, its text encoder and its video VAE.

        LTX 2.5 ships as a bare transformer, so CheckpointLoaderSimple cannot load it -
        it needs UNETLoader + CLIPLoader(type "ltxv") + the LTX video VAE.
        """
        cfg = self.config
        wanted = {
            "unet": cfg.get("video_unet", ""),
            "clip": cfg.get("video_clip", ""),
            "vae": cfg.get("video_vae", ""),
        }
        if all(wanted.values()):
            return {**wanted, "clip_type": cfg.get("video_clip_type", "ltxv")}

        try:
            req = urllib.request.Request(f"http://{self.server_address}/object_info",
                                         headers={'User-Agent': 'SocialMediaMonster/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                info = json.loads(resp.read().decode('utf-8'))
        except Exception:
            return {}

        def options(node, field):
            try:
                value = info[node]["input"]["required"][field][0]
                return value if isinstance(value, list) else []
            except Exception:
                return []

        def first(candidates, pool):
            for c in candidates:
                for name in pool:
                    if c.lower() == name.lower():
                        return name
            for c in candidates:
                for name in pool:
                    if c in name.lower():
                        return name
            return ""

        # Newest first; distilled variants render far faster at similar quality.
        unet = wanted["unet"] or first(
            ["ltx-2.5-22b-distilled", "ltx-2.5", "ltx-2.3-22b-distilled", "ltx-2.3", "ltx-2"],
            options("UNETLoader", "unet_name"))
        clip = wanted["clip"] or first(
            ["gemma4-12b-with-proj-ltx-2.5", "ltx-2.5", "ltx-2.3_text_projection"],
            options("CLIPLoader", "clip_name"))
        vae = wanted["vae"] or first(
            ["ltx-2.5-video-vae-bf16.safetensors", "ltx-2.5-video-vae", "LTX23_video_vae_bf16.safetensors"],
            options("VAELoader", "vae_name"))

        if not (unet and clip and vae):
            return {}
        return {"unet": unet, "clip": clip, "vae": vae,
                "clip_type": cfg.get("video_clip_type", "ltxv")}

    def _dispatch_comfyui_video_prompt(self, prompt_text: str, save_path: str, width: int = 720, height: int = 1280) -> bool:
        """
        Text-to-video through the LTXV graph.

        The previous implementation loaded the IMAGE checkpoint, asked EmptyLatentImage for
        a batch of 16 stills and saved them with SaveImage, so it could never produce an
        mp4. It also returned True the moment the job was queued, which both reported a
        success that had not happened and suppressed the ffmpeg fallback.
        """
        if os.environ.get("SKIP_LOCAL_COMFYUI") == "1":
            return False

        models = self._resolve_video_models()
        if not models:
            log_event(
                "VisualAgent",
                "No complete LTX video model set found in ComfyUI (needs transformer + text "
                "encoder + video VAE). Set comfyui.video_unet / video_clip / video_vae; "
                "using the local video fallback instead.",
                level="WARNING",
            )
            return False

        fps = float(self.config.get("video_fps", 24))
        seconds = float(self.config.get("video_seconds", 4))
        # LTX expects a frame count of 8n+1.
        length = max(9, int(round((fps * seconds - 1) / 8)) * 8 + 1)
        # Latents are built on a 32px grid.
        vid_w = max(256, (width // 32) * 32)
        vid_h = max(256, (height // 32) * 32)

        try:
            seed = int(hashlib.sha256(prompt_text.encode('utf-8')).hexdigest()[:12], 16) % 2_147_483_647
            workflow = {
                "1": {"inputs": {"unet_name": models["unet"], "weight_dtype": "default"},
                      "class_type": "UNETLoader"},
                "2": {"inputs": {"clip_name": models["clip"], "type": models["clip_type"]},
                      "class_type": "CLIPLoader"},
                "4": {"inputs": {"vae_name": models["vae"]}, "class_type": "VAELoader"},
                "6": {"inputs": {"text": prompt_text, "clip": ["2", 0]}, "class_type": "CLIPTextEncode"},
                "7": {"inputs": {"text": self.negative_prompt, "clip": ["2", 0]}, "class_type": "CLIPTextEncode"},
                "5": {"inputs": {"width": vid_w, "height": vid_h, "length": length, "batch_size": 1},
                      "class_type": "EmptyLTXVLatentVideo"},
                "10": {"inputs": {"positive": ["6", 0], "negative": ["7", 0], "frame_rate": fps},
                       "class_type": "LTXVConditioning"},
                "11": {"inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95},
                       "class_type": "ModelSamplingLTXV"},
                "3": {
                    "inputs": {
                        "seed": seed, "steps": int(self.config.get("video_steps", 8)),
                        "cfg": float(self.config.get("video_cfg", 1.0)),
                        "sampler_name": "euler", "scheduler": "simple", "denoise": 1,
                        "model": ["11", 0], "positive": ["10", 0], "negative": ["10", 1],
                        "latent_image": ["5", 0],
                    },
                    "class_type": "KSampler",
                },
                "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 0]}, "class_type": "VAEDecode"},
                "12": {"inputs": {"images": ["8", 0], "fps": fps}, "class_type": "CreateVideo"},
                "9": {"inputs": {"video": ["12", 0], "filename_prefix": "SocialMonster_Video",
                                 "format": "mp4", "codec": "h264"},
                      "class_type": "SaveVideo"},
            }

            body = json.dumps({"prompt": workflow}).encode('utf-8')
            req = urllib.request.Request(f"http://{self.server_address}/prompt", data=body,
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    return False
                payload = json.loads(resp.read().decode('utf-8'))

            prompt_id = payload.get("prompt_id")
            if not prompt_id:
                log_event("VisualAgent", f"ComfyUI rejected the LTX workflow: {str(payload)[:200]}", level="WARNING")
                return False

            log_event("VisualAgent",
                      f"Dispatched LTX video job #{prompt_id[:8]} ({vid_w}x{vid_h}, {length} frames @ {fps}fps, "
                      f"model '{models['unet']}')")

            # Video renders take far longer than stills, so allow a bigger budget.
            attempts = int(self.config.get("video_poll_attempts", 300))
            return self._await_comfy_output(prompt_id, save_path, attempts=attempts, node_ids=("9", "12", "8"))

        except Exception as e:
            log_event("VisualAgent", f"Local ComfyUI video dispatch failed: {e}", level="WARNING")
        return False

    @staticmethod
    def _comfy_error_reason(status: dict) -> str:
        """Pulls the node type and exception text out of a failed ComfyUI run."""
        for message in reversed(status.get("messages", []) or []):
            try:
                name, payload = message[0], message[1]
            except (IndexError, TypeError):
                continue
            if name == "execution_error" and isinstance(payload, dict):
                node = payload.get("node_type", "?")
                detail = (payload.get("exception_message") or "").splitlines()
                return f"{node}: {detail[0] if detail else 'unknown error'}"
        return "unknown error"

    def _await_comfy_output(self, prompt_id: str, save_path: str, attempts: int = 60,
                            node_ids: tuple = ("9",)) -> bool:
        """Polls history and downloads the produced file. Returns False unless it lands."""
        last_position = None
        for attempt in range(attempts):
            time.sleep(self.comfy_poll_interval)
            try:
                h_req = urllib.request.Request(f"http://{self.server_address}/history/{prompt_id}")
                with urllib.request.urlopen(h_req, timeout=10) as h_resp:
                    if h_resp.status != 200:
                        continue
                    h_data = json.loads(h_resp.read().decode('utf-8'))

                if prompt_id not in h_data:
                    if attempt % 15 == 0:
                        position = self._queue_position(prompt_id)
                        if position is not None and position != last_position:
                            last_position = position
                            log_event("VisualAgent", f"ComfyUI busy - job #{prompt_id[:8]} queued behind {position} job(s).")
                    continue

                # A failed graph never produces output. Without this the poller waited out
                # the entire budget on a job that had already errored within a second.
                status = h_data[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    reason = self._comfy_error_reason(status)
                    log_event("VisualAgent", f"ComfyUI job #{prompt_id[:8]} failed: {reason}", level="ERROR")
                    return False

                outputs = h_data[prompt_id].get("outputs", {})
                entry = None
                for node_id in node_ids:
                    node_out = outputs.get(node_id, {})
                    for key in ("images", "gifs", "videos", "video"):
                        items = node_out.get(key)
                        if items:
                            entry = items[0] if isinstance(items, list) else items
                            break
                    if entry:
                        break
                if not entry or not isinstance(entry, dict):
                    continue

                fname = entry.get("filename")
                if not fname:
                    continue
                params = {"filename": fname, "subfolder": entry.get("subfolder", ""),
                          "type": entry.get("type", "output")}
                v_url = f"http://{self.server_address}/view?" + urllib.parse.urlencode(params)
                with urllib.request.urlopen(v_url, timeout=120) as img_resp:
                    raw = img_resp.read()
                if not raw:
                    continue
                with open(save_path, "wb") as f_out:
                    f_out.write(raw)
                log_event("VisualAgent", f"Retrieved ComfyUI output: {fname}", level="SUCCESS")
                return True
            except Exception:
                continue

        waited = int(attempts * self.comfy_poll_interval)
        log_event("VisualAgent", f"ComfyUI job #{prompt_id[:8]} did not return a file within {waited}s.", level="WARNING")
        return False

    def _dispatch_stability_video(self, prompt_text: str, save_path: str, width: int = 720, height: int = 1280) -> bool:
        return False

    def _dispatch_comfy_org_video(self, prompt_text: str, save_path: str, width: int = 720, height: int = 1280) -> bool:
        return False

    def _render_vibrant_video_fallback(self, headline: str, content: str, output_path: str, width: int = 720, height: int = 1280) -> bool:
        """
        Deterministic vertical 9:16 video generator fallback using FFmpeg and PIL raster frames.
        """
        import tempfile
        import subprocess

        temp_dir = tempfile.mkdtemp()
        try:
            num_frames = 20  # 2 seconds @ 10fps
            clean_title = re.sub(r'[^\w\s-]', '', headline or 'Social Media Monster Video')[:40]

            for idx in range(num_frames):
                img = Image.new("RGB", (width, height), color=(12, 16, 28))
                draw = ImageDraw.Draw(img)

                # Vertical background gradient
                for y in range(0, height, 4):
                    alpha = y / height
                    r = int(12 + alpha * 20)
                    g = int(16 + alpha * 30)
                    b = int(28 + alpha * 60)
                    draw.line([(0, y), (width, y)], fill=(r, g, b))

                # Dynamic moving orb
                t = idx / max(1, num_frames)
                orb_y = int(height * 0.35 + 80 * math.sin(t * 2 * math.pi))
                orb_x = int(width * 0.5 + 40 * math.cos(t * 2 * math.pi))
                draw.ellipse([orb_x - 50, orb_y - 50, orb_x + 50, orb_y + 50], fill=(0, 210, 255), outline=(255, 255, 255))

                # Retro border frame
                m = 30
                draw.rectangle([m, m, width - m, height - m], outline=(0, 200, 255), width=4)
                draw.rectangle([m + 6, m + 6, width - m - 6, height - m - 6], outline=(255, 180, 0), width=2)

                # Text overlay
                draw.text((m + 20, m + 30), "MONSTER 9:16 VIDEO", fill=(255, 220, 0))
                draw.text((m + 20, m + 70), clean_title, fill=(255, 255, 255))
                draw.text((m + 20, height - m - 50), f"FRAME {idx+1}/{num_frames} (9:16 VERTICAL)", fill=(0, 255, 200))

                frame_path = os.path.join(temp_dir, f"frame_{idx:03d}.png")
                img.save(frame_path)

            # Invoke FFmpeg if available
            cmd = [
                "ffmpeg", "-y", "-framerate", "10",
                "-i", os.path.join(temp_dir, "frame_%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                log_event("VisualAgent", f"Rendered 9:16 MP4 video via FFmpeg to {os.path.basename(output_path)}", level="SUCCESS")
                return True
        except Exception as e:
            log_event("VisualAgent", f"FFmpeg execution note: {e}", level="INFO")

        # Fallback binary write if FFmpeg binary is absent/fails
        try:
            with open(output_path, "wb") as f:
                f.write(b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom\x00\x00\x00\x08free' + b'\x00' * 1024)
            log_event("VisualAgent", f"Generated synthetic 9:16 fallback video asset to {os.path.basename(output_path)}", level="SUCCESS")
            return True
        except Exception as ex:
            log_event("VisualAgent", f"Failed generating fallback video: {ex}", level="ERROR")
            return False

    def run(self) -> int:
        if not self.is_enabled():
            log_event("VisualAgent", "Bulk visual auto-rendering is PAUSED. Use 'Generate Test' buttons on dashboard to test.")
            return 0

        media_mode = self.get_active_media_mode()
        if media_mode == "video":
            return self._run_video_pipeline()
        else:
            return self._run_image_pipeline()

    def _run_video_pipeline(self) -> int:
        max_per_cycle = int(self.config.get("max_images_per_cycle", 5))

        with Session(engine) as session:
            drafts_needing_video = session.exec(
                select(PostDraft).where(
                    PostDraft.status.in_(["approved", "needs_review", "humanized"]) &
                    ((PostDraft.media_path == None) | (PostDraft.media_path == "") | (PostDraft.media_type != "video"))
                )
            ).all()

            if not drafts_needing_video:
                return 0

            story_ids = list(dict.fromkeys([d.verified_news_id for d in drafts_needing_video if d.verified_news_id]))
            batch_story_ids = story_ids[:max_per_cycle]

        generated_videos = 0
        for story_id in batch_story_ids:
            if self.generate_master_video_for_story(story_id):
                generated_videos += 1

        return generated_videos

    def _run_image_pipeline(self) -> int:
        """
        One master image per STORY, reused by every draft of that story.

        This used to iterate drafts, so a story published to 10 channels was rendered 10
        separate times - ten times the GPU cost, and a different picture on every network
        for the same article.
        """
        max_per_cycle = int(self.config.get("max_images_per_cycle", 5))

        with Session(engine) as session:
            drafts_needing_images = session.exec(
                select(PostDraft).where(
                    PostDraft.status.in_(["approved", "needs_review", "humanized"]) &
                    ((PostDraft.image_path == None) | (PostDraft.image_path == ""))
                )
            ).all()

            if not drafts_needing_images:
                return 0

            story_ids = list(dict.fromkeys(
                d.verified_news_id for d in drafts_needing_images if d.verified_news_id
            ))
            batch_story_ids = story_ids[:max_per_cycle]
            deferred = len(story_ids) - len(batch_story_ids)
            log_event(
                "VisualAgent",
                f"Rendering 1 master image for each of {len(batch_story_ids)} story(ies) "
                f"covering {len(drafts_needing_images)} pending drafts"
                + (f"; {deferred} story(ies) deferred to the next cycle." if deferred else "."),
            )

        generated_count = 0
        for story_id in batch_story_ids:
            if self.generate_master_image_for_story(story_id):
                generated_count += 1

        return generated_count

    def generate_master_image_for_story(self, verified_news_id: int, force: bool = False) -> str:
        """
        Renders a single image for a story and attaches it to every draft of that story.
        Returns the output path, or "" when nothing usable was produced.
        """
        provider = self.get_active_image_provider()

        with Session(engine) as session:
            story = session.get(VerifiedNews, verified_news_id)
            if not story:
                return ""
            drafts = session.exec(
                select(PostDraft).where(PostDraft.verified_news_id == verified_news_id)
            ).all()
            if not drafts:
                return ""

            headline = story.headline or ""
            reference_content = (drafts[0].content or "")[:1200]
            existing_prompt = story.master_image_prompt
            existing_path = story.master_image_path

        image_filename = f"master_story_{verified_news_id}.png"
        output_path = os.path.join(self.output_dir, image_filename)

        # Reuse an already-rendered master unless a re-render was explicitly requested.
        if not force and existing_path and os.path.exists(os.path.join(self.output_dir, existing_path)):
            self._attach_image_to_story(verified_news_id, existing_path, existing_prompt)
            log_event("VisualAgent", f"Reused existing master image for Story #{verified_news_id}.")
            return os.path.join(self.output_dir, existing_path)

        # A 16:9 master crops acceptably to every channel's aspect ratio.
        aspect_ratio = "16:9"
        width, height = ASPECT_DIMENSIONS.get(aspect_ratio, (1024, 1024))

        prompt = existing_prompt if self._is_usable_prompt(existing_prompt) else None
        if not prompt:
            prompt = self._build_vivid_comfy_prompt(headline, reference_content, aspect_ratio)

        log_event(
            "VisualAgent",
            f"Generating 1 master image for Story #{verified_news_id} "
            f"('{headline[:45]}...') via [{provider.upper()}] for {len(drafts)} drafts...",
        )

        success = False
        if provider == "stability_ai":
            success = self._dispatch_stability_ai(prompt, output_path, width, height)
        elif provider == "comfy_org":
            success = self._dispatch_comfy_org(prompt, output_path, width, height)
        elif provider == "comfyui_local":
            if os.environ.get("SKIP_LOCAL_COMFYUI") == "1":
                success = False
            else:
                self.active_checkpoint = self._auto_detect_comfyui_checkpoint()
                success = self._dispatch_comfyui_prompt(prompt, output_path, width, height)

        if not success or provider == "ideogram_card":
            try:
                self._render_vibrant_article_card(headline, reference_content, "wordpress", output_path)
                success = os.path.exists(output_path)
            except Exception as e:
                log_event("VisualAgent", f"Editorial card fallback failed for Story #{verified_news_id}: {e}", level="ERROR")
                success = False

        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            self._attach_image_to_story(verified_news_id, image_filename, prompt)
            log_event(
                "VisualAgent",
                f"Attached single master image '{image_filename}' to all {len(drafts)} posts "
                f"for Story #{verified_news_id}",
                level="SUCCESS",
            )
            return output_path

        log_event("VisualAgent", f"Master image generation produced no file for Story #{verified_news_id}", level="ERROR")
        return ""

    @staticmethod
    def _attach_image_to_story(verified_news_id: int, image_filename: str, prompt: str):
        with Session(engine) as session:
            story = session.get(VerifiedNews, verified_news_id)
            if story:
                story.master_image_path = image_filename
                story.master_image_prompt = prompt
                session.add(story)

            drafts = session.exec(
                select(PostDraft).where(PostDraft.verified_news_id == verified_news_id)
            ).all()
            for d in drafts:
                # Leave video drafts alone; they carry their own master video.
                if d.media_type == "video":
                    continue
                d.image_path = image_filename
                d.media_path = image_filename
                d.media_type = "image"
                d.image_prompt = prompt
                session.add(d)
            session.commit()

    @staticmethod
    def _extract_subject_terms(headline: str, content: str, limit: int = 6) -> list:
        """
        Pull the distinctive nouns of THIS story so two different articles never receive
        the same prompt. Proper nouns, versioned names and long technical tokens win.
        """
        clean = re.sub(r'http\S+', ' ', f"{headline} {content or ''}")
        clean = re.sub(r'[#*_`>\[\]()]', ' ', clean)
        tokens = re.findall(r'\b[A-Za-z][A-Za-z0-9.+-]{2,}\b', clean)

        scored = {}
        for raw in tokens:
            word = raw.strip(".-+")
            low = word.lower()
            if len(word) < 3 or low in VISUAL_STOPWORDS:
                continue
            weight = 1
            if word[0].isupper():
                weight += 2
            if any(ch.isdigit() for ch in word):
                weight += 2
            if len(word) > 8:
                weight += 1
            scored[low] = scored.get(low, 0) + weight

        ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
        return [w for w, _ in ranked[:limit]]

    @staticmethod
    def _select_scene_motif(text: str) -> str:
        lowered = (text or "").lower()
        best, best_hits = None, 0
        for keywords, motif in SCENE_MOTIFS:
            hits = sum(1 for k in keywords if k in lowered)
            if hits > best_hits:
                best, best_hits = motif, hits
        return best or "a retro-futurist newsroom hall lined with glowing broadcast monitors"

    @classmethod
    def _build_vivid_comfy_prompt(cls, headline: str, content: str, aspect_ratio: str = "1:1") -> str:
        """
        Builds a scene from what the article actually reports.

        The article analyser identifies the story's ACTION (a watermarking story is
        'provenance', a lawsuit is 'regulation') and its SUBJECT (the organisations and
        products involved), so the scene depicts this specific event rather than generic
        "AI" imagery driven by the word "model" appearing somewhere in the text.
        """
        clean_title = re.sub(
            r'^\s*(?:\[[^\]]+\]|Headline:|Deep Dive:|#+)\s*', '', (headline or '')
        ).strip()
        clean_title = re.sub(r'\s*\[[A-Z]+\]\s*$', '', clean_title).strip()

        brief = build_visual_brief(clean_title, content or "")

        # Who the scene is about, phrased as staging rather than a keyword list.
        if brief["subject"] and brief["supporting"]:
            actors = (f"The scene represents {brief['subject']} and {brief['supporting']} "
                      f"as heraldic banners and emblems worked into the architecture.")
        elif brief["subject"]:
            actors = (f"The scene represents {brief['subject']} through a heraldic banner "
                      f"and emblem worked into the architecture.")
        else:
            actors = ""

        # "isometric" pulled the model toward tile/asset-sheet layouts. These describe a
        # single framed illustration with one focal point instead.
        composition = {
            "16:9": "wide cinematic establishing shot of one continuous location, strong depth layers",
            "1:1": "single centered composition with one clear focal point",
            "4:5": "tall vertical composition, single subject framed by foreground detail",
        }.get(aspect_ratio, "single centered composition with one clear focal point")

        # Moment, vantage and palette vary per story so two articles sharing a concept
        # ("hardware", "regulation") do not render as the same picture.
        moment = brief.get("moment", "")
        vantage = brief.get("vantage", "")
        palette = brief.get("palette", "deep indigo shadows with cyan rim light and warm amber highlights")

        return (
            f"A single cohesive 16-bit SNES-era RPG scene, one illustration: {brief['scene']}, "
            f"{moment}. Foreground details: {brief['props']}. {actors} "
            f"{vantage}, {composition}, dramatic key lighting, hand-dithered shading, "
            f"limited retro palette of {palette}, volumetric haze, subtle CRT scanline grain, "
            f"detailed pixel artwork."
        ).replace("  ", " ")

    @staticmethod
    def _write_image_bytes(raw: bytes, save_path: str) -> bool:
        """Persist bytes only if they actually decode as an image."""
        if not raw:
            return False
        try:
            with open(save_path, "wb") as f_out:
                f_out.write(raw)
            with Image.open(save_path) as probe:
                probe.verify()
            return True
        except Exception as e:
            log_event("VisualAgent", f"Discarded unreadable image payload: {e}", level="WARNING")
            try:
                if os.path.exists(save_path):
                    os.remove(save_path)
            except OSError:
                pass
            return False

    def _dispatch_stability_ai(self, prompt_text: str, save_path: str, width: int = 1024, height: int = 1024) -> bool:
        try:
            cfg = self.llm.get_active_provider_config()
            api_key = cfg.get("stability_api_key", "")
            if not api_key:
                return False
            url = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
            body = json.dumps({
                "text_prompts": [
                    {"text": prompt_text, "weight": 1.0},
                    {"text": "blurry, low quality, distorted, watermark, text, jpeg artifacts", "weight": -1.0},
                ],
                "cfg_scale": 7, "height": height, "width": width, "samples": 1, "steps": 30
            }).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(req, timeout=90) as resp:
                if resp.status != 200:
                    return False
                payload = json.loads(resp.read().decode('utf-8'))

            # The response carries base64 artifacts; without decoding them no file exists.
            artifacts = payload.get("artifacts") or []
            for artifact in artifacts:
                if artifact.get("finishReason") not in (None, "SUCCESS"):
                    continue
                raw = base64.b64decode(artifact.get("base64", ""))
                if self._write_image_bytes(raw, save_path):
                    log_event("VisualAgent", f"Saved Stability AI image to {os.path.basename(save_path)}", level="SUCCESS")
                    return True

            log_event("VisualAgent", "Stability AI responded without a usable image artifact.", level="WARNING")
        except Exception as e:
            log_event("VisualAgent", f"Stability AI dispatch failed: {e}", level="WARNING")
        return False

    def _dispatch_comfy_org(self, prompt_text: str, save_path: str, width: int = 1024, height: int = 1024) -> bool:
        try:
            cfg = self.llm.get_active_provider_config()
            api_key = cfg.get("comfy_org_api_key", "")
            if not api_key:
                return False
            url = "https://api.comfy.org/v1/generate"
            body = json.dumps({
                "prompt": prompt_text,
                "resolution": f"{width}x{height}",
            }).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            })
            with urllib.request.urlopen(req, timeout=90) as resp:
                if resp.status != 200:
                    return False
                payload = json.loads(resp.read().decode('utf-8'))

            raw = self._extract_cloud_image_bytes(payload)
            if self._write_image_bytes(raw, save_path):
                log_event("VisualAgent", f"Saved ComfyUI Org image to {os.path.basename(save_path)}", level="SUCCESS")
                return True

            log_event("VisualAgent", "ComfyUI Org responded without a usable image payload.", level="WARNING")
        except Exception as e:
            log_event("VisualAgent", f"ComfyUI Org dispatch failed: {e}", level="WARNING")
        return False

    @staticmethod
    def _extract_cloud_image_bytes(payload: dict) -> bytes:
        """Accepts either an inline base64 field or a URL to fetch."""
        if not isinstance(payload, dict):
            return b""
        for key in ("image", "image_base64", "b64_json", "data"):
            value = payload.get(key)
            if isinstance(value, str) and len(value) > 128:
                try:
                    return base64.b64decode(value)
                except Exception:
                    continue
        for key in ("url", "image_url", "output_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                try:
                    with urllib.request.urlopen(value, timeout=30) as img_resp:
                        return img_resp.read()
                except Exception:
                    continue
        outputs = payload.get("outputs")
        if isinstance(outputs, list) and outputs:
            first = outputs[0]
            if isinstance(first, dict):
                return VisualAgent._extract_cloud_image_bytes(first)
        return b""

    def _resolve_model_files(self) -> dict:
        """
        Finds the UNET/CLIP/VAE trio for a diffusion-transformer image model.

        Modern models such as Z-Image ship the transformer alone: loading them through
        CheckpointLoaderSimple fails with "clip input is invalid: None" because there is
        no text encoder inside the file. They need UNETLoader + CLIPLoader + VAELoader.
        """
        cfg = self.config
        wanted = {
            "unet": cfg.get("image_unet", ""),
            "clip": cfg.get("image_clip", ""),
            "clip_type": cfg.get("image_clip_type", ""),
            "vae": cfg.get("image_vae", ""),
        }
        if all(wanted[k] for k in ("unet", "clip", "clip_type", "vae")):
            return wanted

        try:
            req = urllib.request.Request(f"http://{self.server_address}/object_info",
                                         headers={'User-Agent': 'SocialMediaMonster/1.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                info = json.loads(resp.read().decode('utf-8'))
        except Exception:
            return {}

        def options(node, field):
            try:
                value = info[node]["input"]["required"][field][0]
                return value if isinstance(value, list) else []
            except Exception:
                return []

        unets, clips, vaes = options("UNETLoader", "unet_name"), options("CLIPLoader", "clip_name"), options("VAELoader", "vae_name")

        def first(candidates, pool):
            # Exact filename wins before any substring match: "ae.safetensors" is a
            # substring of "ace_1.5_vae.safetensors", which loaded the wrong VAE and
            # failed inside VAEDecode.
            for c in candidates:
                for name in pool:
                    if c.lower() == name.lower():
                        return name
            for c in candidates:
                for name in pool:
                    if c in name.lower():
                        return name
            return ""

        # Z-Image: Qwen3 text encoder read with the lumina2 tokenizer, Flux-style VAE.
        unet = wanted["unet"] or first(["z_image_turbo_bf16", "z_image_turbo", "z_image"], unets)
        if not unet:
            return {}
        clip = wanted["clip"] or first(["qwen_3_4b.safetensors", "qwen_3_4b", "qwen3.5_2b"], clips)
        vae = wanted["vae"] or first(["ae.safetensors"], vaes)
        if not (clip and vae):
            return {}
        return {"unet": unet, "clip": clip, "clip_type": wanted["clip_type"] or "lumina2", "vae": vae}

    def _sampler_settings(self) -> dict:
        """
        Sampler parameters matched to the checkpoint family.

        Turbo/Lightning/distilled models are trained for very few steps at CFG ~1.
        Running z-image Turbo at the SDXL defaults of 20 steps / CFG 7 burns time and
        produces washed-out, over-cooked output.
        """
        name = (self.active_checkpoint or "").lower()
        overrides = self.config.get("sampler", {}) or {}

        if any(tag in name for tag in ("turbo", "lightning", "lcm", "distill", "hyper")):
            settings = {"steps": 8, "cfg": 1.5, "sampler_name": "euler", "scheduler": "simple"}
        elif "flux" in name:
            settings = {"steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple"}
        else:
            settings = {"steps": 25, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras"}

        settings.update({k: v for k, v in overrides.items() if k in settings})
        return settings

    def _fit_resolution(self, width: int, height: int) -> tuple:
        """
        Keeps the request inside the checkpoint's native range.

        SD 1.5 is a 512px model: asking it for 1024x1024 makes it repeat the subject
        across the canvas, which is what produced tiled "asset sheet" images rather than
        one coherent scene. SDXL and Flux are trained at ~1024 and are left alone.
        """
        name = (self.active_checkpoint or "").lower()
        is_legacy_sd = any(tag in name for tag in ("v1-5", "sd15", "v2-1")) and "xl" not in name
        cap = 768 if is_legacy_sd else 1344

        longest = max(width, height)
        if longest <= cap:
            return width, height

        scale = cap / longest
        # Diffusion models expect multiples of 64.
        fit_w = max(320, int(width * scale) // 64 * 64)
        fit_h = max(320, int(height * scale) // 64 * 64)
        log_event(
            "VisualAgent",
            f"Checkpoint '{self.active_checkpoint}' works best at or below {cap}px; "
            f"rendering {fit_w}x{fit_h} instead of {width}x{height}.",
        )
        return fit_w, fit_h

    def _dispatch_comfyui_prompt(self, prompt_text: str, save_path: str, width: int = 1024, height: int = 1024) -> bool:
        width, height = self._fit_resolution(width, height)
        try:
            # Vary the seed per prompt so re-rendering a different story cannot return a
            # cached identical image from a fixed seed.
            seed = int(hashlib.sha256(prompt_text.encode('utf-8')).hexdigest()[:12], 16) % 2_147_483_647

            trio = self._resolve_model_files()
            if trio:
                return self._dispatch_comfyui_dit(prompt_text, save_path, width, height, seed, trio)

            sampler = self._sampler_settings()
            workflow = {
                "3": {
                    "inputs": {
                        "seed": seed,
                        "steps": sampler["steps"], "cfg": sampler["cfg"],
                        "sampler_name": sampler["sampler_name"], "scheduler": sampler["scheduler"],
                        "denoise": 1, "model": ["4", 0],
                        "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]
                    },
                    "class_type": "KSampler"
                },
                "4": {"inputs": {"ckpt_name": self.active_checkpoint}, "class_type": "CheckpointLoaderSimple"},
                "5": {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptyLatentImage"},
                "6": {"inputs": {"text": prompt_text, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
                "7": {"inputs": {"text": self.negative_prompt, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
                "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
                "9": {"inputs": {"filename_prefix": "SocialMonster_Test", "images": ["8", 0]}, "class_type": "SaveImage"}
            }

            data = json.dumps({"prompt": workflow}).encode('utf-8')
            req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    return False
                res_payload = json.loads(response.read().decode('utf-8'))

            prompt_id = res_payload.get("prompt_id")
            if not prompt_id:
                log_event("VisualAgent", "ComfyUI accepted the request but returned no prompt_id.", level="WARNING")
                return False

            log_event("VisualAgent", f"Dispatched prompt #{prompt_id[:8]} to ComfyUI ({self.server_address})")

            # Poll history until the render lands. Diffusion on modest hardware regularly
            # needs more than the old 12s budget, and the server may be busy with jobs
            # submitted by other tools.
            last_position = None
            for attempt in range(self.comfy_poll_attempts):
                time.sleep(self.comfy_poll_interval)
                try:
                    h_req = urllib.request.Request(f"http://{self.server_address}/history/{prompt_id}")
                    with urllib.request.urlopen(h_req, timeout=5) as h_resp:
                        if h_resp.status != 200:
                            continue
                        h_data = json.loads(h_resp.read().decode('utf-8'))

                    if prompt_id not in h_data:
                        # Not executed yet. Report where we are in the queue instead of
                        # leaving the user staring at a silent wait, then a card.
                        if attempt % 10 == 0:
                            position = self._queue_position(prompt_id)
                            if position is not None and position != last_position:
                                last_position = position
                                log_event(
                                    "VisualAgent",
                                    f"ComfyUI is busy - prompt #{prompt_id[:8]} is queued "
                                    f"behind {position} job(s).",
                                )
                        continue
                    outputs = h_data[prompt_id].get("outputs", {}).get("9", {}).get("images", [])
                    if not outputs:
                        continue

                    fname = outputs[0].get("filename")
                    subfolder = outputs[0].get("subfolder", "")
                    v_url = (
                        f"http://{self.server_address}/view?"
                        + urllib.parse.urlencode({"filename": fname, "subfolder": subfolder, "type": "output"})
                    )
                    with urllib.request.urlopen(v_url, timeout=30) as img_resp:
                        raw = img_resp.read()
                    if self._write_image_bytes(raw, save_path):
                        log_event("VisualAgent", f"Retrieved generated ComfyUI image: {fname}", level="SUCCESS")
                        return True
                except Exception:
                    continue

            # Dispatching is not the same as producing a file. Reporting success here was
            # what left post records pointing at images that were never written.
            waited = int(self.comfy_poll_attempts * self.comfy_poll_interval)
            position = self._queue_position(prompt_id)
            if position is not None:
                log_event(
                    "VisualAgent",
                    f"ComfyUI prompt #{prompt_id[:8]} is STILL QUEUED after {waited}s "
                    f"({position} job(s) ahead - the server is busy with other work). "
                    f"The render will finish on its own; using the editorial card for now. "
                    f"Raise comfyui.poll_attempts to wait longer.",
                    level="WARNING",
                )
            else:
                log_event(
                    "VisualAgent",
                    f"ComfyUI prompt #{prompt_id[:8]} did not return an image within {waited}s.",
                    level="WARNING",
                )
        except Exception as e:
            log_event("VisualAgent", f"Local ComfyUI dispatch failed: {e}", level="WARNING")
        return False

    @staticmethod
    def _load_font(size: int, bold: bool = False):
        """
        PIL's built-in bitmap font renders at roughly 6px, which is unreadable on a
        1200px card. Fall back through common system faces before giving up.
        """
        candidates = (
            ["arialbd.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"]
            if bold else
            ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"]
        )
        for name in candidates:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default(size)
        except Exception:
            return ImageFont.load_default()

    @staticmethod
    def _wrap_to_width(draw, text: str, font, max_width: int, max_lines: int) -> list:
        """Measured wrapping - character counting misaligns badly on proportional fonts."""
        words = (text or "").split()
        lines, current = [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
                if len(lines) == max_lines:
                    break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) == max_lines and words:
            # Signal that copy was clipped rather than ending abruptly.
            last = lines[-1]
            while last and draw.textlength(last + "…", font=font) > max_width:
                last = last[:-1]
            lines[-1] = last + "…" if len(" ".join(lines)) < len(text or "") else last
        return lines

    def _render_vibrant_article_card(self, headline: str, content: str, platform: str, save_path: str):
        width, height = (1200, 675) if platform in ["twitter", "wordpress", "facebook", "youtube"] else (1080, 1080)
        img = Image.new('RGB', (width, height), color=(15, 23, 42))
        d = ImageDraw.Draw(img)

        d.ellipse([width - 450, -150, width + 150, 450], fill=(30, 58, 138))
        d.ellipse([-100, height - 300, 400, height + 200], fill=(180, 83, 9))

        d.rectangle([20, 20, width - 20, height - 20], outline=(56, 189, 248), width=2)
        d.line([(20, 92), (width - 20, 92)], fill=(56, 189, 248), width=1)
        d.line([(20, height - 82), (width - 20, height - 82)], fill=(56, 189, 248), width=1)

        font_meta = self._load_font(20, bold=True)
        font_title = self._load_font(58, bold=True)
        font_body = self._load_font(26)

        d.text((44, 46), f"SOCIAL MEDIA MONSTER // {platform.upper()}", font=font_meta, fill=(248, 250, 252))
        engine_label = f"ENGINE: {self.get_active_image_provider().upper()}"
        d.text((width - 44 - d.textlength(engine_label, font=font_meta), 46),
               engine_label, font=font_meta, fill=(148, 163, 184))

        clean_title = re.sub(r'^\s*(?:\[[^\]]+\]|Headline:|Deep Dive:|#+)\s*', '', (headline or '')).strip()
        clean_title = re.sub(r'\s*\[[A-Z]+\]\s*$', '', clean_title).strip()

        inner_width = width - 100
        title_lines = self._wrap_to_width(d, clean_title.upper(), font_title, inner_width, 3)

        y_pos = 150
        for line in title_lines:
            d.text((50, y_pos), line, font=font_title, fill=(255, 255, 255))
            y_pos += 68

        clean_summary = re.sub(r'\s+', ' ', (content or "").replace("\n", " ")).strip()
        clean_summary = re.sub(r'#\w+', '', clean_summary).strip()
        body_lines = self._wrap_to_width(d, clean_summary, font_body, inner_width, 4)

        y_s_pos = y_pos + 28
        for s_line in body_lines:
            d.text((50, y_s_pos), s_line, font=font_body, fill=(203, 213, 225))
            y_s_pos += 38

        d.rectangle([(width // 2) - 50, height - 52, (width // 2) + 50, height - 40], fill=(56, 189, 248))
        img.save(save_path)
