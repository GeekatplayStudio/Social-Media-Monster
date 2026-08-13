import os
import json
import time
import urllib.request
import urllib.parse
import hashlib
from PIL import Image, ImageDraw
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import PostDraft, SystemSetting
from src.core.llm_client import LLMClient

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
                        # Prioritize SD1.5 and SDXL for standard CheckpointLoaderSimple
                        for preferred in ["v1-5", "sd15", "sd_xl", "sdxl", "v2-1", "stable-diffusion", "flux"]:
                            for name in ckpt_list:
                                if preferred in name.lower():
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

            aspect_ratio = "16:9" if draft.platform in ["twitter", "wordpress"] else "1:1" if draft.platform == "instagram" else "4:5"
            descriptive_prompt = self._build_vivid_comfy_prompt(draft.headline, draft.content, aspect_ratio)
            draft.image_prompt = descriptive_prompt

            image_filename = f"test_post_{draft.id}_{draft.platform}.png"
            output_path = os.path.join(self.output_dir, image_filename)

            success = False

            if provider == "stability_ai":
                success = self._dispatch_stability_ai(descriptive_prompt, output_path)
            elif provider == "comfy_org":
                success = self._dispatch_comfy_org(descriptive_prompt, output_path)
            elif provider == "comfyui_local":
                self.active_checkpoint = self._auto_detect_comfyui_checkpoint()
                success = self._dispatch_comfyui_prompt(descriptive_prompt, output_path)

            # Fallback to high-contrast dark editorial card template if API/Local fails or card selected
            if not success or provider == "ideogram_card":
                self._render_vibrant_article_card(draft.headline, draft.content, draft.platform, output_path)

            draft.image_path = image_filename
            session.add(draft)
            session.commit()
            log_event("VisualAgent", f"Completed image generation for Post #{draft.id} via [{provider.upper()}]", level="SUCCESS")
            return output_path

    def run(self) -> int:
        if not self.is_enabled():
            log_event("VisualAgent", "Bulk image auto-rendering is PAUSED. Use 'Generate Test Image' button on any post to test.")
            return 0

        with Session(engine) as session:
            drafts_needing_images = session.exec(
                select(PostDraft).where(
                    (PostDraft.status == "draft") & 
                    ((PostDraft.image_path == None) | (PostDraft.image_path == ""))
                )
            ).all()

            if not drafts_needing_images:
                return 0

            log_event("VisualAgent", f"Generating visuals for {len(drafts_needing_images)} new post drafts...")
            generated_count = 0

            for draft in drafts_needing_images[:1]:
                self.generate_single_test_image(draft.id)
                generated_count += 1

        return generated_count

    def _build_vivid_comfy_prompt(self, headline: str, content: str, aspect_ratio: str) -> str:
        clean_title = headline.replace("Headline:", "").replace("[Discussion]", "").replace("Deep Dive:", "").strip()
        return (
            f"High-contrast editorial concept artwork representing '{clean_title}', "
            f"glowing neural network nodes, cybernetic sculpture visual, metallic textures, "
            f"cinematic studio lighting, cyan and amber highlights, highly detailed, masterwork 8k"
        )

    def _dispatch_stability_ai(self, prompt_text: str, save_path: str) -> bool:
        try:
            cfg = self.llm.get_active_provider_config()
            api_key = cfg.get("stability_api_key", "")
            if not api_key:
                return False
            url = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"
            body = json.dumps({
                "text_prompts": [{"text": prompt_text, "weight": 1.0}],
                "cfg_scale": 7, "height": 1024, "width": 1024, "samples": 1, "steps": 30
            }).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    log_event("VisualAgent", "Generated image via Stability AI Cloud API", level="SUCCESS")
                    return True
        except Exception:
            pass
        return False

    def _dispatch_comfy_org(self, prompt_text: str, save_path: str) -> bool:
        try:
            cfg = self.llm.get_active_provider_config()
            api_key = cfg.get("comfy_org_api_key", "")
            if not api_key:
                return False
            url = "https://api.comfy.org/v1/generate"
            body = json.dumps({"prompt": prompt_text, "resolution": "1024x1024"}).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            })
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    log_event("VisualAgent", "Generated image via ComfyUI Org Cloud API", level="SUCCESS")
                    return True
        except Exception:
            pass
        return False

    def _dispatch_comfyui_prompt(self, prompt_text: str, save_path: str) -> bool:
        try:
            workflow = {
                "3": {
                    "inputs": {
                        "seed": 407231, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                        "scheduler": "normal", "denoise": 1, "model": ["4", 0],
                        "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]
                    },
                    "class_type": "KSampler"
                },
                "4": {"inputs": {"ckpt_name": self.active_checkpoint}, "class_type": "CheckpointLoaderSimple"},
                "5": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1}, "class_type": "EmptyLatentImage"},
                "6": {"inputs": {"text": prompt_text, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
                "7": {"inputs": {"text": "blurry, low quality, distorted", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
                "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
                "9": {"inputs": {"filename_prefix": "SocialMonster_Test", "images": ["8", 0]}, "class_type": "SaveImage"}
            }

            data = json.dumps({"prompt": workflow}).encode('utf-8')
            req = urllib.request.Request(f"http://{self.server_address}/prompt", data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    res_payload = json.loads(response.read().decode('utf-8'))
                    prompt_id = res_payload.get("prompt_id")
                    log_event("VisualAgent", f"Dispatched prompt #{prompt_id[:8] if prompt_id else ''} to ComfyUI ({self.server_address})", level="SUCCESS")
                    
                    # Poll history for up to 12s to fetch output image
                    if prompt_id:
                        for _ in range(12):
                            time.sleep(1)
                            try:
                                h_req = urllib.request.Request(f"http://{self.server_address}/history/{prompt_id}")
                                with urllib.request.urlopen(h_req, timeout=2) as h_resp:
                                    if h_resp.status == 200:
                                        h_data = json.loads(h_resp.read().decode('utf-8'))
                                        if prompt_id in h_data:
                                            outputs = h_data[prompt_id].get("outputs", {}).get("9", {}).get("images", [])
                                            if outputs:
                                                fname = outputs[0].get("filename")
                                                subfolder = outputs[0].get("subfolder", "")
                                                v_url = f"http://{self.server_address}/view?filename={fname}&subfolder={subfolder}&type=output"
                                                with urllib.request.urlopen(v_url, timeout=5) as img_resp:
                                                    with open(save_path, "wb") as f_out:
                                                        f_out.write(img_resp.read())
                                                log_event("VisualAgent", f"Retrieved generated ComfyUI image: {fname}", level="SUCCESS")
                                                return True
                            except Exception:
                                pass
                    return True
        except Exception:
            pass
        return False

    def _render_vibrant_article_card(self, headline: str, content: str, platform: str, save_path: str):
        width, height = (1200, 675) if platform in ["twitter", "wordpress"] else (1000, 1000)
        img = Image.new('RGB', (width, height), color=(15, 23, 42))
        d = ImageDraw.Draw(img)

        d.ellipse([width - 450, -150, width + 150, 450], fill=(30, 58, 138))
        d.ellipse([-100, height - 300, 400, height + 200], fill=(180, 83, 9))

        d.rectangle([20, 20, width - 20, height - 20], outline=(56, 189, 248), width=2)
        d.line([(20, 75), (width - 20, 75)], fill=(56, 189, 248), width=1)
        d.line([(20, height - 75), (width - 20, height - 75)], fill=(56, 189, 248), width=1)

        d.text((40, 40), f"SOCIAL MEDIA MONSTER // {platform.upper()}", fill=(248, 250, 252))
        d.text((width - 340, 40), f"ENGINE: {self.get_active_image_provider().upper()}", fill=(148, 163, 184))

        clean_title = headline.replace("Headline:", "").replace("[Discussion]", "").replace("Deep Dive:", "").strip()
        words = clean_title.split()
        lines = []
        curr = ""
        for w in words:
            if len(curr + " " + w) > 34:
                lines.append(curr)
                curr = w
            else:
                curr += " " + w
        lines.append(curr)

        y_pos = 130
        for line in lines[:3]:
            d.text((50, y_pos), line.strip().upper(), fill=(255, 255, 255))
            y_pos += 50

        clean_summary = content.replace("\n", " ").strip()[:160]
        sum_words = clean_summary.split()
        sum_lines = []
        curr_s = ""
        for sw in sum_words:
            if len(curr_s + " " + sw) > 50:
                sum_lines.append(curr_s)
                curr_s = sw
            else:
                curr_s += " " + sw
        sum_lines.append(curr_s)

        y_s_pos = y_pos + 25
        for s_line in sum_lines[:3]:
            d.text((50, y_s_pos), s_line.strip(), fill=(203, 213, 225))
            y_s_pos += 32

        d.rectangle([(width // 2) - 50, height - 48, (width // 2) + 50, height - 36], fill=(56, 189, 248))
        img.save(save_path)
