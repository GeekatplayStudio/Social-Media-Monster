import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import SystemSetting
from src.core.security import SecurityManager

# Hard character ceilings enforced on generated copy, per channel.
PLATFORM_LIMITS = {
    "twitter": 280,
    "instagram": 2200,
    "facebook": 5000,
    "youtube": 1500,
    "telegram": 4096,
    "linkedin": 3000,
    "reddit": 10000,
    "discord": 2000,
    "wordpress": 20000,
}

# Generic filler that must never survive into published copy.
BOILERPLATE_PATTERNS = [
    r'^\s*VERIFIED FACTS:\s*',
    r'Verified Source \([^)]*\):\s*',
    r'The story provides significant technical advancements in generative AI architectures\.?',
    r'Source authority is confirmed across tech outlets\.?',
    r'^\s*Impact:\s*',
    r'^\s*Engineering update regarding\s*',
]

# Only these labels delimit a section when parsing a prompt back apart.
PROMPT_SECTION_LABELS = [
    "Headline", "Article Headline", "Verified Facts", "Key Takeaways", "Target Platform",
    "Equalizer Profile", "Author Sample Article", "Original Text", "Target Text",
    "Target Persona Voice Sample", "Post Content Summary", "Source Article",
    "Source Summary", "Problem", "Task",
]

# Tokens that end in a period without ending a sentence.
ABBREVIATIONS = {
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "inc", "ltd", "co", "corp", "dr", "mr", "mrs", "ms", "prof", "st", "vs", "etc",
    "no", "fig", "approx", "al", "u.s", "e.g", "i.e", "est", "min", "max", "ver", "rev",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "into", "that", "this",
    "these", "those", "of", "to", "in", "on", "at", "by", "as", "is", "are", "was", "were",
    "be", "been", "it", "its", "has", "have", "had", "will", "can", "new", "now", "how",
    "why", "what", "when", "after", "over", "more", "than", "you", "your", "our", "their",
}


class ProviderCircuitBreaker:
    """
    Skips a provider that just refused a connection.

    A refused TCP connect costs ~2s on Windows, and the pipeline makes one call per post
    per stage. With no provider running that turned a single cycle into minutes of dead
    waiting. After a transport failure the endpoint is skipped for a cooldown window and
    generation goes straight to the offline synthesizer.
    """
    COOLDOWN_SECONDS = 60.0

    def __init__(self):
        self._open_until = {}

    def is_open(self, endpoint: str) -> bool:
        until = self._open_until.get(endpoint, 0.0)
        if until and time.monotonic() < until:
            return True
        if until:
            self._open_until.pop(endpoint, None)
        return False

    def trip(self, endpoint: str):
        first_trip = endpoint not in self._open_until
        self._open_until[endpoint] = time.monotonic() + self.COOLDOWN_SECONDS
        if first_trip:
            log_event(
                "LLMClient",
                f"Provider endpoint [{endpoint}] is unreachable. Skipping it for "
                f"{int(self.COOLDOWN_SECONDS)}s and using the offline synthesizer.",
                level="WARNING",
            )

    def reset(self, endpoint: str = None):
        if endpoint:
            self._open_until.pop(endpoint, None)
        else:
            self._open_until.clear()


# Shared across every agent in the process so one dead provider is probed once, not once
# per agent per post.
_CIRCUIT = ProviderCircuitBreaker()


class LLMClient:
    """
    Abstract Multi-Provider API Layer:
    Provides abstract routing across Local Ollama, OpenAI, Google Gemini, Anthropic Claude,
    and Custom API endpoints with input payload sanitization, credential encryption,
    and a task-aware offline synthesis engine.

    The offline synthesizer NEVER invents story facts. It only reshapes the material that
    was passed into the prompt, so an unreachable provider degrades the formatting but
    never contaminates a post with an unrelated story.
    """

    def __init__(self):
        self.config = load_config().get("llm", {})
        self.security = SecurityManager()

    def get_active_provider_config(self) -> dict:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "abstract_provider_cfg")).first()
            if setting and setting.value:
                try:
                    data = json.loads(setting.value)
                    # Decrypt stored credentials in-memory
                    for key in ("openai_api_key", "gemini_api_key", "anthropic_api_key",
                                "stability_api_key", "comfy_org_api_key", "tavily_api_key"):
                        data[key] = self.security.decrypt_credential(data.get(key, ""))
                    return data
                except Exception:
                    pass
        return {
            "provider": self.config.get("provider", "ollama"),
            "host_mode": "local",
            "model_name": self.config.get("model_name", "llama3"),
            "base_url": self.config.get("base_url", "http://127.0.0.1:11434"),
            "openai_api_key": self.config.get("openai_api_key", ""),
            "gemini_api_key": self.config.get("gemini_api_key", ""),
            "anthropic_api_key": self.config.get("anthropic_api_key", ""),
            "stability_api_key": self.config.get("stability_api_key", ""),
            "comfy_org_api_key": self.config.get("comfy_org_api_key", ""),
            "tavily_api_key": self.config.get("tavily_api_key", ""),
        }

    def generate(self, prompt: str, system_prompt: str = None, platform: str = "twitter",
                 task: str = "post") -> str:
        """
        task controls what the offline synthesizer produces when no provider answers:
          "post"         -> a platform-native social post built from the prompt's story fields
          "rewrite"      -> the caller's own text, humanized (never replaced by a new story)
          "image_prompt" -> a visual generation prompt (never a social post)
          "facts"        -> condensed factual bullets extracted from the supplied source text
        """
        cfg = self.get_active_provider_config()
        provider = cfg.get("provider", "ollama").lower()

        # Input Payload Sanitization & Defense Gate
        sanitized_prompt = self.security.sanitize_input_payload(prompt)
        sanitized_sys_prompt = self.security.sanitize_input_payload(system_prompt) if system_prompt else None

        raw_output = ""
        endpoint = self._endpoint_id(provider, cfg)

        if _CIRCUIT.is_open(endpoint):
            # Known-unreachable: do not pay another connect timeout for this call.
            raw_output = ""
        else:
            log_event("LLMClient", f"Attempting text generation via provider [{provider.upper()}] (task={task})...")
            if provider == "openai" and cfg.get("openai_api_key"):
                raw_output = self._call_openai(sanitized_prompt, sanitized_sys_prompt, cfg)
            elif provider == "gemini" and cfg.get("gemini_api_key"):
                raw_output = self._call_gemini(sanitized_prompt, sanitized_sys_prompt, cfg)
            elif provider == "anthropic" and cfg.get("anthropic_api_key"):
                raw_output = self._call_anthropic(sanitized_prompt, sanitized_sys_prompt, cfg)
            else:
                raw_output = self._call_ollama(sanitized_prompt, sanitized_sys_prompt, cfg)

        raw_output = (raw_output or "").strip()

        if not self._is_usable(raw_output, task):
            log_event(
                "LLMClient",
                f"No usable response from [{provider.upper()}]. Using offline synthesizer (task={task}).",
                level="WARNING",
            )
            raw_output = self._synthesize_offline(prompt, platform, task)

        if task in ("post", "rewrite"):
            raw_output = self._enforce_platform_limit(raw_output, platform)

        # Output Payload Sanitization & API Key Redaction Gate
        return self.security.sanitize_output_payload(raw_output)

    @staticmethod
    def _endpoint_id(provider: str, cfg: dict) -> str:
        if provider == "ollama":
            return f"ollama@{cfg.get('base_url', 'http://127.0.0.1:11434')}"
        return provider

    def _is_usable(self, text: str, task: str) -> bool:
        if not text:
            return False
        minimum = 20 if task == "image_prompt" else 30
        if len(text) < minimum:
            return False
        # A model that echoed our scaffolding back is not a usable answer.
        if text.lower().startswith(("task:", "original text:", "target text:")):
            return False
        if task == "image_prompt" and self._looks_like_social_post(text):
            return False
        return True

    @staticmethod
    def _looks_like_social_post(text: str) -> bool:
        """An image prompt must not carry hashtags, engagement questions or link CTAs."""
        return bool(re.search(r'#\w+', text)) or "http" in text.lower() or text.count("?") > 1

    @staticmethod
    def _enforce_platform_limit(text: str, platform: str) -> str:
        limit = PLATFORM_LIMITS.get((platform or "").lower())
        if not limit or len(text) <= limit:
            return text
        # Trim on a sentence boundary where possible so copy never ends mid-word.
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
        if cut > limit * 0.55:
            return window[:cut + 1].strip()
        return window[:limit - 1].rstrip() + "…"

    # ------------------------------------------------------------------ providers

    def _call_ollama(self, prompt: str, system_prompt: str, cfg: dict) -> str:
        try:
            base_url = cfg.get("base_url", "http://127.0.0.1:11434")
            model = cfg.get("model_name", "llama3")
            url = f"{base_url}/api/generate"
            full_prompt = f"System: {system_prompt}\nUser: {prompt}" if system_prompt else prompt
            data = json.dumps({"model": model, "prompt": full_prompt, "stream": False}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode('utf-8'))
                    out = res.get("response", "").strip()
                    if out:
                        return out
        except Exception as e:
            log_event("LLMClient", f"Local Ollama connection skipped ({e}). Using offline synthesizer.", level="INFO")
            _CIRCUIT.trip(self._endpoint_id("ollama", cfg))
        return ""

    def _call_openai(self, prompt: str, system_prompt: str, cfg: dict) -> str:
        try:
            api_key = cfg.get("openai_api_key")
            url = "https://api.openai.com/v1/chat/completions"
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            model = cfg.get("model_name") or "gpt-4o"
            data = json.dumps({"model": model, "messages": messages, "temperature": 0.7}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode('utf-8'))
                    return res['choices'][0]['message']['content'].strip()
        except Exception as e:
            log_event("LLMClient", f"OpenAI API call failed: {e}", level="ERROR")
            if isinstance(e, (urllib.error.URLError, TimeoutError, OSError)) and not isinstance(e, urllib.error.HTTPError):
                _CIRCUIT.trip("openai")
        return ""

    def _call_gemini(self, prompt: str, system_prompt: str, cfg: dict) -> str:
        try:
            api_key = cfg.get("gemini_api_key")
            model = cfg.get("model_name") or "gemini-1.5-flash"
            if not model.startswith("gemini"):
                model = "gemini-1.5-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(api_key)}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode('utf-8'))
                    return res['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            log_event("LLMClient", f"Gemini API call failed: {e}", level="ERROR")
            if isinstance(e, (urllib.error.URLError, TimeoutError, OSError)) and not isinstance(e, urllib.error.HTTPError):
                _CIRCUIT.trip("gemini")
        return ""

    def _call_anthropic(self, prompt: str, system_prompt: str, cfg: dict) -> str:
        try:
            api_key = cfg.get("anthropic_api_key")
            model = cfg.get("model_name") or "claude-sonnet-4-5"
            if not model.startswith("claude"):
                model = "claude-sonnet-4-5"
            payload = {
                "model": model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                payload["system"] = system_prompt
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                },
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                if response.status == 200:
                    res = json.loads(response.read().decode('utf-8'))
                    parts = [b.get("text", "") for b in res.get("content", []) if b.get("type") == "text"]
                    return "\n".join(parts).strip()
        except Exception as e:
            log_event("LLMClient", f"Anthropic API call failed: {e}", level="ERROR")
            if isinstance(e, (urllib.error.URLError, TimeoutError, OSError)) and not isinstance(e, urllib.error.HTTPError):
                _CIRCUIT.trip("anthropic")
        return ""

    # ------------------------------------------------------------------ offline synthesis

    def _synthesize_offline(self, prompt: str, platform: str, task: str) -> str:
        if task == "rewrite":
            return self._synthesize_rewrite(prompt, platform)
        if task == "image_prompt":
            return self._synthesize_image_prompt(prompt)
        if task == "facts":
            return self._synthesize_facts(prompt)
        return self._synthesize_article(prompt, platform)

    @classmethod
    def _field(cls, prompt: str, label: str) -> str:
        """
        Pull a labelled block out of the prompt, up to the next known section label.
        Only recognised labels terminate a block, so a colon inside the body (for example
        "Root Cause:") does not silently truncate the extracted text.
        """
        others = "|".join(re.escape(s) for s in PROMPT_SECTION_LABELS if s != label)
        # A label may carry a parenthetical suffix, e.g. "Equalizer Profile (-1.0 to +1.0):".
        pattern = rf'^{re.escape(label)}[^:\n]{{0,32}}:\s*(.*?)(?=^\s*(?:{others})[^:\n]{{0,32}}:|\Z)'
        m = re.search(pattern, prompt or "", flags=re.DOTALL | re.MULTILINE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _strip_boilerplate(text: str) -> str:
        cleaned = text or ""
        for pattern in BOILERPLATE_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
        cleaned = re.sub(r'<[^>]+>', '', cleaned)
        cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
        return cleaned.strip()

    @classmethod
    def _keywords(cls, *sources: str, limit: int = 4) -> list:
        """Topic terms taken from the actual story - never a fixed list."""
        text = " ".join(s for s in sources if s)
        candidates = re.findall(r'\b[A-Za-z][A-Za-z0-9+.#-]{2,}\b', text)
        seen, out = set(), []
        for raw in candidates:
            word = raw.strip(".-#+")
            low = word.lower()
            if low in STOPWORDS or len(word) < 3 or low in seen:
                continue
            # Prefer proper nouns and technical tokens over generic prose.
            if word[0].isupper() or any(ch.isdigit() for ch in word) or len(word) > 7:
                seen.add(low)
                out.append(word)
            if len(out) >= limit:
                break
        return out

    @classmethod
    def _hashtags(cls, *sources: str, limit: int = 4) -> str:
        tags = ["#" + re.sub(r'[^A-Za-z0-9]', '', k) for k in cls._keywords(*sources, limit=limit)]
        return " ".join(t for t in tags if len(t) > 2)

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        """Truncate on a word boundary so copy never breaks mid-word."""
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        window = text[:limit]
        space = window.rfind(" ")
        return (window[:space] if space > limit * 0.5 else window).rstrip(" ,;:-") + "…"

    @classmethod
    def _split_sentences(cls, text: str) -> list:
        """
        Sentence split that survives abbreviations. A naive split on '. ' turns
        "launched on or after Aug. 2 would include watermarking" into two bullets, one of
        which begins "2 would include...".
        """
        fragments = []
        for chunk in re.split(r'(?<=[.!?])\s+|\n+', text or ""):
            frag = re.sub(r'^\s*(?:[-*•▪]|\d+[.)])\s*', '', chunk).strip()
            if not frag:
                continue
            if fragments:
                previous = fragments[-1]
                last_word = previous.split()[-1].rstrip('.').lower() if previous.split() else ""
                # Re-join when the break followed an abbreviation, or when the next
                # fragment cannot start a sentence.
                if last_word in ABBREVIATIONS or frag[0].isdigit() or frag[0].islower():
                    fragments[-1] = f"{previous} {frag}"
                    continue
            fragments.append(frag)
        return fragments

    @classmethod
    def _sentences(cls, text: str, limit: int = 6) -> list:
        return [s for s in cls._split_sentences(text) if len(s) > 25][:limit]

    def _synthesize_article(self, prompt: str, platform: str) -> str:
        headline = self._strip_boilerplate(self._field(prompt, "Headline")) or "Industry Update"
        facts = self._strip_boilerplate(self._field(prompt, "Verified Facts"))
        takeaways = self._strip_boilerplate(self._field(prompt, "Key Takeaways"))

        # Never fabricate a story. If the pipeline gave us nothing, say only what we know.
        if not facts:
            facts = self._strip_boilerplate(self._field(prompt, "Source Summary")) or headline
        if not takeaways:
            takeaways = ""

        bullets = self._sentences(facts, limit=4) or [facts]

        # A takeaway that merely restates the facts adds nothing and reads as padding.
        takeaway_line = ""
        if takeaways:
            first = self._sentences(takeaways, limit=1)
            candidate = first[0] if first else takeaways.strip()
            if candidate and candidate[:60].lower() not in facts.lower():
                takeaway_line = candidate

        tags = self._hashtags(headline, facts)
        p = (platform or "").lower()

        if p == "twitter":
            body = f"{headline}\n\n{self._clip(bullets[0], 170)}"
            if takeaway_line:
                body += f"\n\nWhy it matters: {self._clip(takeaway_line, 100)}"
            return f"{body}\n\n{tags}".strip()

        if p == "instagram":
            lines = "\n".join(f"▪ {self._clip(b, 110)}" for b in bullets[:3])
            tail = self._clip(takeaway_line, 180) if takeaway_line else ""
            return f"{headline}\n\n{lines}\n\n{tail}\n.\n.\n{tags}".strip()

        if p == "facebook":
            return self._join_blocks(
                headline,
                "\n\n".join(bullets),
                f"The takeaway: {takeaway_line}" if takeaway_line else "",
                "What's your read on this? Drop a comment.",
                tags,
            )

        if p == "youtube":
            lines = "\n".join(f"• {self._clip(b, 120)}" for b in bullets[:3])
            return self._join_blocks(
                f"📺 Community Update — {headline}", lines,
                "Poll: does this change how you build? 👍 Yes / 👎 Not yet", tags,
            )

        if p == "telegram":
            lines = "\n".join(f"▸ {self._clip(b, 140)}" for b in bullets[:3])
            return self._join_blocks(
                f"**{headline}**", lines,
                f"__{self._clip(takeaway_line, 160)}__" if takeaway_line else "",
            )

        if p == "linkedin":
            lines = "\n".join(f"• {b}" for b in bullets[:4])
            return self._join_blocks(
                headline, lines,
                f"Takeaway: {takeaway_line}" if takeaway_line else "",
                "How is your team approaching this?", tags,
            )

        if p == "reddit":
            lines = "\n\n".join(bullets[:5])
            return self._join_blocks(
                f"[Discussion] {headline}",
                f"**What happened**\n\n{lines}",
                f"**Why it matters**\n\n{takeaway_line}" if takeaway_line else "",
                "Has anyone here run into this in production? Curious what your setup looks like.",
            )

        if p == "discord":
            lines = "\n".join(f"> {self._clip(b, 150)}" for b in bullets[:3])
            return self._join_blocks(
                f"**{headline}**", lines,
                f"*{self._clip(takeaway_line, 200)}*" if takeaway_line else "",
            )

        # wordpress / default long-form
        return self._join_blocks(
            f"# {headline}",
            "\n\n".join(bullets),
            f"## Key Takeaways\n\n{takeaway_line}" if takeaway_line else "",
        )

    @staticmethod
    def _join_blocks(*blocks: str) -> str:
        """Joins sections with blank lines, dropping empties so no gaps are left behind."""
        return "\n\n".join(b.strip() for b in blocks if b and b.strip()).strip()

    def _synthesize_rewrite(self, prompt: str, platform: str) -> str:
        """
        Offline humanization pass. Returns the caller's OWN text with robotic connective
        tissue removed - it must never substitute a different story.
        """
        source = self._field(prompt, "Original Text") or self._field(prompt, "Target Text")
        source = self._strip_boilerplate(source)
        if not source:
            # Last resort: reuse the longest block in the prompt rather than inventing copy.
            blocks = [b.strip() for b in (prompt or "").split("\n\n") if len(b.strip()) > 40]
            source = self._strip_boilerplate(max(blocks, key=len)) if blocks else ""

        replacements = {
            r"\bdelve into\b": "dig into",
            r"\bin the realm of\b": "in",
            r"\bit is worth noting that\b": "note that",
            r"\bin conclusion\b": "bottom line",
            r"\bfurthermore\b": "also",
            r"\bmoreover\b": "and",
            r"\ba testament to\b": "proof of",
            r"\bgame-changer\b": "major shift",
            r"\brevolutioniz(e|es|ing)\b": r"reshap\1",
            r"\bleverage(d|s)?\b": "use",
            r"\butiliz(e|es|ed|ing)\b": r"us\1",
            r"\bin today's rapidly evolving landscape,?\s*": "",
            r"\bit's important to note that\b": "",
        }
        out = source
        for pattern, repl in replacements.items():
            out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
        out = re.sub(r'\n{3,}', '\n\n', out).strip()
        return out

    def _synthesize_image_prompt(self, prompt: str) -> str:
        """
        Returns empty deliberately. Composing a scene is the VisualAgent's job, and it
        owns the subject-matter motif table; duplicating a weaker version here would let
        the QA gate overwrite the better prompt with a vaguer one.
        """
        return ""

    def _synthesize_facts(self, prompt: str) -> str:
        """Condenses supplied source material into factual bullets without adding claims."""
        source = self._strip_boilerplate(
            self._field(prompt, "Source Article") or self._field(prompt, "Source Summary") or prompt
        )
        # Honour a request for a single-line answer instead of always returning a bullet list.
        wants_single = re.search(r'\bone or two sentences\b|\bone sentence\b|\bsingle\b', prompt or "", re.IGNORECASE)
        limit = 2 if wants_single else 4

        sentences = self._sentences(source, limit=limit)
        if not sentences:
            return source[:400].strip()
        if wants_single:
            return " ".join(sentences)
        return "\n".join(f"- {s}" for s in sentences)
