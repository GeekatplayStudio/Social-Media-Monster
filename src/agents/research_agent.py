import feedparser
import urllib.request
import urllib.parse
import json
import re
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import TrendItem, SystemSetting
from src.core.tavily_client import TavilyClient

class ResearchAgent:
    """
    Research Agent with Granular Real-Time Telemetry:
    Logs every target website URL, search query, incoming article title, source URL, 
    and deduplication verdict in real-time.
    """
    def __init__(self):
        self.config = load_config().get("research_sources", {})
        self.rss_feeds = self.config.get("rss_feeds", [
            "https://news.ycombinator.com/rss",
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://rss.arxiv.org/rss/cs.AI"
        ])
        self.tavily = TavilyClient()
        self.max_results_per_topic = int(self.config.get("max_results_per_topic", 6))
        self.last_scan_telemetry = {
            "active_queries": [],
            "scanned_sources": [],
            "found_articles": [],
            "search_engine": "RSS"
        }

    def get_search_topics(self) -> list:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "search_topics")).first()
            if setting and setting.value:
                return [t.strip() for t in setting.value.split(",") if t.strip()]
        return ["Generative AI", "Local LLMs", "ComfyUI", "Flux", "AI Agents"]

    def run(self) -> int:
        topics = self.get_search_topics()
        log_event("ResearchAgent", f"🔍 STARTING INTERNET SCAN across {len(topics)} target queries...", level="INFO")
        
        self.last_scan_telemetry["active_queries"] = topics
        self.last_scan_telemetry["scanned_sources"] = []
        self.last_scan_telemetry["found_articles"] = []

        use_tavily = self.tavily.is_configured()
        self.last_scan_telemetry["search_engine"] = "Tavily" if use_tavily else "Google News RSS"
        log_event(
            "ResearchAgent",
            f"🔎 Discovery engine: {'Tavily Search API' if use_tavily else 'Google News RSS (no Tavily key configured)'}",
        )

        new_items_count = 0

        # 1. Targeted per-topic search
        for topic in topics:
            if use_tavily:
                new_items_count += self._scan_topic_with_tavily(topic)
            else:
                new_items_count += self._scan_topic_with_google_rss(topic)

        # 2. Tech RSS Feeds Scan
        for feed_url in self.rss_feeds:
            self.last_scan_telemetry["scanned_sources"].append(f"Tech RSS | Feed URL: {feed_url}")
            log_event("ResearchAgent", f"🌐 Scanning Tech RSS Feed: {feed_url}")
            try:
                feed = feedparser.parse(feed_url)
                log_event("ResearchAgent", f"📡 Feed returned {len(feed.entries)} entries from {feed_url[:40]}")

                for entry in feed.entries[:6]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = entry.get("summary", entry.get("description", ""))

                    if title and self._is_topic_match(title + " " + summary, topics):
                        is_new, item_id = self._save_trend_item(title, link, f"RSS ({feed_url.split('/')[2]})", summary)
                        status_str = "NEW (SAVED)" if is_new else "DUPLICATE (SKIPPED)"

                        log_event("ResearchAgent", f"  ↳ [{status_str}] '{title[:70]}...'")

                        self.last_scan_telemetry["found_articles"].append({
                            "title": title,
                            "url": link,
                            "query": "RSS Feed Match",
                            "source": feed_url,
                            "status": status_str
                        })
                        if is_new:
                            new_items_count += 1
            except Exception as e:
                # Silently swallowing this hid dead feeds and made an empty scan look healthy.
                log_event("ResearchAgent", f"Tech RSS feed '{feed_url}' failed: {e}", level="WARNING")

        log_event("ResearchAgent", f"✨ RESEARCH SCAN COMPLETE. Discovered {new_items_count} fresh AI news articles.", level="SUCCESS")
        return new_items_count

    def _scan_topic_with_tavily(self, topic: str) -> int:
        """Tavily news search: ranked, freshness-filtered, with article text attached."""
        self.last_scan_telemetry["scanned_sources"].append(f"Tavily Search API | Query: '{topic}'")
        log_event("ResearchAgent", f"🌐 Tavily Search | Query: '{topic}'")

        results = self.tavily.search(topic, max_results=self.max_results_per_topic)
        if not results:
            log_event("ResearchAgent", f"Tavily returned nothing for '{topic}'. Falling back to Google News RSS.", level="WARNING")
            return self._scan_topic_with_google_rss(topic)

        log_event("ResearchAgent", f"📡 Tavily returned {len(results)} ranked results for '{topic}'")

        found = 0
        for r in results:
            is_new, _ = self._save_trend_item(
                r["title"], r["url"], f"Tavily ({r['source']})", r["content"],
                viral_score=r["score"], raw_content=r["content"],
            )
            status_str = "NEW (SAVED)" if is_new else "DUPLICATE (SKIPPED)"
            log_event("ResearchAgent", f"  ↳ [{status_str}] '{r['title'][:70]}' | relevance {r['score']:.2f}")

            self.last_scan_telemetry["found_articles"].append({
                "title": r["title"],
                "url": r["url"],
                "query": topic,
                "source": f"Tavily / {r['source']}",
                "status": status_str,
            })
            if is_new:
                found += 1
        return found

    def _scan_topic_with_google_rss(self, topic: str) -> int:
        encoded_q = urllib.parse.quote(topic)
        google_rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"

        self.last_scan_telemetry["scanned_sources"].append(
            f"Google News RSS | Query: '{topic}' | URL: {google_rss_url}"
        )
        log_event("ResearchAgent", f"🌐 Scanning Website: Google News RSS | Query: '{topic}'")

        found = 0
        try:
            feed = feedparser.parse(google_rss_url)
            log_event("ResearchAgent", f"📡 Google News returned {len(feed.entries)} raw entries for query '{topic}'")

            for entry in feed.entries[:self.max_results_per_topic]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))
                if not title:
                    continue

                is_new, _ = self._save_trend_item(title, link, f"Google News ('{topic}')", summary)
                status_str = "NEW (SAVED)" if is_new else "DUPLICATE (SKIPPED)"
                log_event("ResearchAgent", f"  ↳ [{status_str}] '{title[:70]}...' | Source: {link[:50]}")

                self.last_scan_telemetry["found_articles"].append({
                    "title": title,
                    "url": link,
                    "query": topic,
                    "source": "Google News",
                    "status": status_str,
                })
                if is_new:
                    found += 1
        except Exception as e:
            log_event("ResearchAgent", f"Notice querying Google News for '{topic}': {e}", level="WARNING")
        return found

    def _is_topic_match(self, text: str, topics: list) -> bool:
        text_lower = text.lower()
        return any(t.lower() in text_lower for t in topics) or "ai" in text_lower or "model" in text_lower

    @staticmethod
    def _canonical_url(url: str) -> str:
        """Strips tracking query parameters and trailing slashes for canonical deduplication."""
        parsed = urllib.parse.urlparse(url or "")
        clean_query = urllib.parse.parse_qs(parsed.query)
        # Strip common tracking query params
        tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
        filtered_query = {k: v for k, v in clean_query.items() if k.lower() not in tracking_keys}
        new_query = urllib.parse.urlencode(filtered_query, doseq=True)
        canonical = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            new_query,
            ""
        ))
        return canonical or url

    def _save_trend_item(self, title: str, url: str, source: str, summary: str,
                         viral_score: float = 1.0, raw_content: str = None) -> tuple:
        canonical_url = self._canonical_url(url)
        norm_title = (title or "").strip().lower()

        with Session(engine) as session:
            # Check by exact URL or canonical URL
            existing = session.exec(
                select(TrendItem).where(
                    (TrendItem.url == url) | (TrendItem.url == canonical_url)
                )
            ).first()

            # Also check by normalized title match if title is substantial (> 10 chars)
            if not existing and len(norm_title) > 10:
                all_items = session.exec(select(TrendItem)).all()
                for item in all_items:
                    if (item.title or "").strip().lower() == norm_title:
                        existing = item
                        break

            if not existing:
                clean_summary = re.sub(r'<[^>]+>', '', summary or "")[:800]
                item = TrendItem(
                    title=title,
                    url=canonical_url,
                    source=source,
                    summary=clean_summary,
                    raw_content=(raw_content or "")[:8000] or None,
                    score=viral_score,
                    processed=False
                )
                session.add(item)
                session.commit()
                return True, item.id
            return False, existing.id
