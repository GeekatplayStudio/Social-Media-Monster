import os
import re
import json
import time
import base64
import urllib.request
import urllib.parse
import hashlib
from PIL import Image, ImageDraw, ImageFont

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
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import PostDraft, SystemSetting
from src.core.llm_client import LLMClient
from src.core.article_analysis import build_visual_brief

class VisualAgent:
    """
    Visual Agent:
    Supports 1-click single test image generation for a specific post draft.
    Supports Local ComfyUI, Stability AI Cloud API, ComfyUI Org Cloud API,
    and Editorial Card Template Engine.
    """
    def __init__(self):
        self.config = load_config().get("comfyui", {})
        self.server_address = self.config.get("server_address", "127.0.0.1:8188")
        self.output_dir = "data/outputs/images"
        self.llm = LLMClient()
        self.comfy_poll_attempts = int(self.config.get("poll_attempts", 60))
        self.comfy_poll_interval = float(self.config.get("poll_interval_seconds", 2))
        # "blurry, low quality, distorted" was too weak to suppress the sprite-sheet
        # layouts these prompts otherwise attract.
        self.negative_prompt = self.config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
        self.active_checkpoint = self._auto_detect_comfyui_checkpoint()
        os.makedirs(self.output_dir, exist_ok=True)

    def is_enabled(self) -> bool:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "comfyui_enabled")).first()
            if setting:
                return setting.value.lower() == "true"
        return False

    def get_active_image_provider(self) -> str:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_image_provider")).first()
            if setting and setting.value:
                return setting.value
        return "comfyui_local"

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
                        for preferred in ["sd_xl_base", "sdxl", "sd_xl", "flux1-dev", "flux",
                                          "hidream", "zimage", "v2-1", "v1-5", "sd15"]:
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
        provider = self.get_active_image_provider()
        with Session(engine) as session:
            draft = session.get(PostDraft, post_id)
            if not draft:
                return ""

            log_event("VisualAgent", f"Generating test image for Post #{draft.id} ({draft.platform}) using [{provider.upper()}]...")

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

    def run(self) -> int:
        if not self.is_enabled():
            log_event("VisualAgent", "Bulk image auto-rendering is PAUSED. Use 'Generate Test Image' button on any post to test.")
            return 0

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

            batch = drafts_needing_images[:max_per_cycle]
            skipped = len(drafts_needing_images) - len(batch)
            log_event(
                "VisualAgent",
                f"Generating visuals for {len(batch)} of {len(drafts_needing_images)} pending drafts"
                + (f" ({skipped} deferred to the next cycle)." if skipped else "."),
            )
            draft_ids = [d.id for d in batch]

        # Run generation outside the read session; each call opens its own transaction.
        generated_count = 0
        for draft_id in draft_ids:
            if self.generate_single_test_image(draft_id):
                generated_count += 1

        return generated_count

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

        return (
            f"A single cohesive 16-bit SNES-era RPG scene, one illustration: {brief['scene']}. "
            f"Foreground details: {brief['props']}. {actors} "
            f"{composition}, dramatic key lighting, hand-dithered shading, limited retro "
            f"palette of deep indigo, cyan rim light and warm amber highlights, volumetric "
            f"haze, subtle CRT scanline grain, detailed pixel artwork."
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
            workflow = {
                "3": {
                    "inputs": {
                        "seed": seed, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                        "scheduler": "normal", "denoise": 1, "model": ["4", 0],
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
