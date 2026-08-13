import os
import json
import time
import urllib.request
import urllib.error
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import SystemSetting
from src.core.security import SecurityManager

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


class TavilyClient:
    """
    Tavily Research Layer.

    Two capabilities are used by the pipeline:
      search(query)  -> ranked, freshness-filtered news results with relevance scores,
                        replacing the Google News RSS scrape in the ResearchAgent.
      extract(url)   -> the full readable body of an article, so the VerifierAgent can
                        derive real facts instead of a truncated feed blurb.

    The key is read from the encrypted Abstract Provider config first, then the
    TAVILY_API_KEY environment variable, then config.yaml. When no key is present the
    client reports itself unconfigured and callers fall back to RSS.
    """

    # Cache lifetime for the resolved key. Long enough to avoid a DB round trip per
    # article during a scan, short enough that a key saved in the UI takes effect promptly.
    KEY_CACHE_SECONDS = 30.0

    def __init__(self):
        self.security = SecurityManager()
        self.config = load_config().get("tavily", {}) or {}
        self.timeout = int(self.config.get("timeout_seconds", 30))
        self._cached_key = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------ credentials

    def get_api_key(self) -> str:
        now = time.monotonic()
        if self._cached_key is not None and (now - self._cached_at) < self.KEY_CACHE_SECONDS:
            return self._cached_key
        key = self._resolve_api_key()
        self._cached_key, self._cached_at = key, now
        return key

    def invalidate_key_cache(self):
        self._cached_key = None

    def _resolve_api_key(self) -> str:
        # 1. Encrypted dashboard config
        try:
            with Session(engine) as session:
                setting = session.exec(
                    select(SystemSetting).where(SystemSetting.key_name == "abstract_provider_cfg")
                ).first()
                if setting and setting.value:
                    data = json.loads(setting.value)
                    key = self.security.decrypt_credential(data.get("tavily_api_key", ""))
                    if key:
                        return key.strip()
        except Exception:
            pass

        # 2. Environment
        env_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if env_key:
            return env_key

        # 3. config.yaml
        return str(self.config.get("api_key", "") or "").strip()

    def is_configured(self) -> bool:
        key = self.get_api_key()
        return bool(key) and not key.upper().startswith("YOUR_")

    # ------------------------------------------------------------------ transport

    def _post(self, url: str, payload: dict) -> dict:
        api_key = self.get_api_key()
        if not api_key:
            return {}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    log_event("TavilyClient", f"Tavily returned HTTP {resp.status} for {url}", level="WARNING")
                    return {}
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            if e.code in (401, 403):
                log_event("TavilyClient", "Tavily rejected the API key (check the key in Provider Config).", level="ERROR")
            elif e.code == 429:
                log_event("TavilyClient", "Tavily rate limit reached. Falling back to RSS for this cycle.", level="WARNING")
            else:
                log_event("TavilyClient", f"Tavily HTTP {e.code}: {detail}", level="WARNING")
        except Exception as e:
            log_event("TavilyClient", f"Tavily request failed: {e}", level="WARNING")
        return {}

    # ------------------------------------------------------------------ capabilities

    def search(self, query: str, max_results: int = 6, days: int = None,
               topic: str = None, search_depth: str = None) -> list:
        """
        Returns a list of {title, url, content, score, published_date, source}.
        An empty list means "no usable answer" - callers should fall back to RSS.
        """
        if not self.is_configured():
            return []

        payload = {
            "query": query,
            "max_results": max(1, min(int(max_results), 20)),
            "topic": topic or self.config.get("topic", "news"),
            "search_depth": search_depth or self.config.get("search_depth", "advanced"),
            "include_answer": False,
            "include_raw_content": bool(self.config.get("include_raw_content", False)),
        }
        # "days" is only meaningful for the news topic.
        if payload["topic"] == "news":
            payload["days"] = int(days or self.config.get("days", 7))

        include_domains = self.config.get("include_domains") or []
        exclude_domains = self.config.get("exclude_domains") or []
        if include_domains:
            payload["include_domains"] = list(include_domains)
        if exclude_domains:
            payload["exclude_domains"] = list(exclude_domains)

        data = self._post(TAVILY_SEARCH_URL, payload)
        results = data.get("results") or []

        normalized = []
        for r in results:
            url = (r.get("url") or "").strip()
            title = (r.get("title") or "").strip()
            if not url or not title:
                continue
            normalized.append({
                "title": title,
                "url": url,
                "content": (r.get("raw_content") or r.get("content") or "").strip(),
                "score": float(r.get("score") or 0.0),
                "published_date": r.get("published_date", ""),
                "source": self._domain(url),
            })
        return normalized

    def extract(self, url: str) -> str:
        """Returns the readable body text of a single URL, or '' when unavailable."""
        if not self.is_configured() or not url:
            return ""

        payload = {
            "urls": [url],
            "extract_depth": self.config.get("extract_depth", "basic"),
        }
        data = self._post(TAVILY_EXTRACT_URL, payload)

        for entry in data.get("results") or []:
            content = (entry.get("raw_content") or entry.get("content") or "").strip()
            if content:
                return content

        for failed in data.get("failed_results") or []:
            log_event("TavilyClient", f"Tavily could not extract {failed.get('url', url)}", level="INFO")
        return ""

    @staticmethod
    def _domain(url: str) -> str:
        try:
            parts = url.split("/")
            return parts[2] if len(parts) > 2 else url
        except Exception:
            return url
