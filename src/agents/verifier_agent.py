import re
import html
from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import TrendItem, VerifiedNews
from src.core.llm_client import LLMClient
from src.core.tavily_client import TavilyClient

# Feed furniture that adds no information to a story.
FEED_NOISE_PATTERNS = [
    r'Comments\s*$',
    r'\bRead more\b.*$',
    r'\bContinue reading\b.*$',
    r'\bThe post .*? appeared first on .*?\.',
    r'\bsubmitted by\s+/u/\S+',
    r'\[link\]|\[comments\]',
    r'&#\d+;',
    r'\s*\|\s*[A-Z][A-Za-z ]{2,20}$',
]

# Domains whose reporting we treat as first-party or high-editorial-standard.
HIGH_TRUST_DOMAINS = (
    "arxiv.org", "acm.org", "ieee.org", "nature.com", "science.org",
    "openai.com", "anthropic.com", "deepmind.google", "ai.meta.com",
    "github.com", "github.blog", "reuters.com", "apnews.com", "bloomberg.com",
)


class VerifierAgent:
    """
    Fact Verification Agent:
    Pulls the real article body (via Tavily Extract when configured), strips feed noise,
    and derives concrete technical facts. It no longer emits the
    "Verified Source (RSS): <truncated summary>" boilerplate that leaked into published copy.
    """

    MIN_FACT_CHARS = 40

    def __init__(self):
        self.llm = LLMClient()
        self.tavily = TavilyClient()

    def run(self) -> int:
        log_event("VerifierAgent", "Starting verification cycle on unverified trend items...")
        verified_count = 0

        with Session(engine) as session:
            unprocessed_items = session.exec(
                select(TrendItem).where(TrendItem.processed == False)
            ).all()

            for item in unprocessed_items:
                source_text = self._resolve_source_text(item)

                if len(source_text) < self.MIN_FACT_CHARS:
                    log_event(
                        "VerifierAgent",
                        f"Skipping '{item.title[:60]}' - no substantive source text could be retrieved.",
                        level="WARNING",
                    )
                    item.processed = True
                    session.add(item)
                    session.commit()
                    continue

                verified_facts, key_takeaways = self._extract_facts(item.title, source_text)

                verified = VerifiedNews(
                    trend_id=item.id,
                    headline=self._clean(item.title),
                    verified_facts=verified_facts,
                    source_reliability_score=self._score_source(item),
                    key_takeaways=key_takeaways,
                    status="verified",
                )
                session.add(verified)
                item.processed = True
                if source_text and not item.raw_content:
                    item.raw_content = source_text[:8000]
                session.add(item)
                session.commit()
                verified_count += 1
                log_event("VerifierAgent", f"Verified news item #{verified.id}: '{item.title[:60]}...'")

        log_event("VerifierAgent", f"Verification cycle complete. Processed {verified_count} news items.", level="SUCCESS")
        return verified_count

    def _resolve_source_text(self, item: TrendItem) -> str:
        """Prefer full article text; fall back to the feed summary."""
        if item.raw_content and len(item.raw_content) > 200:
            return self._clean(item.raw_content)

        if item.url and self.tavily.is_configured():
            extracted = self.tavily.extract(item.url)
            if extracted and len(extracted) > 200:
                log_event("VerifierAgent", f"Tavily extracted {len(extracted)} chars of article body for '{item.title[:50]}'")
                return self._clean(extracted)

        return self._clean(item.summary or "")

    def _extract_facts(self, headline: str, source_text: str) -> tuple:
        prompt = (
            f"Headline: {headline}\n"
            f"Source Article: {source_text[:6000]}\n\n"
            f"Task: List the concrete, checkable facts this article reports - names, numbers, "
            f"versions, dates, measured results and stated causes. Use short bullet lines. "
            f"Do not add commentary, do not speculate, and do not restate the headline."
        )
        system_prompt = (
            "You are a technical fact checker. You extract only what the source states. "
            "If the source does not support a claim, you leave it out."
        )
        facts = self.llm.generate(prompt, system_prompt=system_prompt, task="facts").strip()

        takeaway_prompt = (
            f"Headline: {headline}\n"
            f"Source Article: {source_text[:4000]}\n\n"
            f"Task: In one or two sentences, state why this matters to engineers building with AI."
        )
        takeaways = self.llm.generate(
            takeaway_prompt,
            system_prompt="You are a technical editor writing a single sharp takeaway line.",
            task="facts",
        ).strip()

        if len(facts) < self.MIN_FACT_CHARS:
            facts = self._condense(source_text, sentences=4)
        if len(takeaways) < 20:
            takeaways = self._condense(source_text, sentences=1)

        return self._clean(facts), self._clean(takeaways)

    @staticmethod
    def _condense(text: str, sentences: int = 3) -> str:
        parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text or "") if len(s.strip()) > 30]
        return " ".join(parts[:sentences]) if parts else (text or "").strip()[:400]

    @staticmethod
    def _clean(text: str) -> str:
        cleaned = html.unescape(text or "")
        cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
        for pattern in FEED_NOISE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
        cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    @staticmethod
    def _score_source(item: TrendItem) -> float:
        url = (item.url or "").lower()
        if any(domain in url for domain in HIGH_TRUST_DOMAINS):
            return 0.95
        source = (item.source or "").lower()
        if "tavily" in source:
            return 0.88
        if "rss" in source:
            return 0.80
        if "google news" in source:
            return 0.70
        return 0.65
