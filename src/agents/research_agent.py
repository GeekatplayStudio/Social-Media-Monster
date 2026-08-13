import feedparser
import urllib.request
import urllib.parse
import json
import re
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import TrendItem, SystemSetting

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
        self.last_scan_telemetry = {
            "active_queries": [],
            "scanned_sources": [],
            "found_articles": []
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
        
        new_items_count = 0

        # 1. Targeted Google News RSS Search for each subject
        for topic in topics:
            encoded_q = urllib.parse.quote(topic)
            google_rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"
            
            source_info = f"Google News RSS | Query: '{topic}' | URL: {google_rss_url}"
            self.last_scan_telemetry["scanned_sources"].append(source_info)
            log_event("ResearchAgent", f"🌐 Scanning Website: Google News RSS | Query: '{topic}'")

            try:
                feed = feedparser.parse(google_rss_url)
                log_event("ResearchAgent", f"📡 Google News returned {len(feed.entries)} raw entries for query '{topic}'")

                for entry in feed.entries[:6]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    summary = entry.get("summary", entry.get("description", ""))
                    
                    if title:
                        is_new, item_id = self._save_trend_item(title, link, f"Google News ('{topic}')", summary)
                        status_str = "NEW (SAVED)" if is_new else "DUPLICATE (SKIPPED)"
                        
                        log_event("ResearchAgent", f"  ↳ [{status_str}] '{title[:70]}...' | Source: {link[:50]}")
                        
                        self.last_scan_telemetry["found_articles"].append({
                            "title": title,
                            "url": link,
                            "query": topic,
                            "source": "Google News",
                            "status": status_str
                        })
                        if is_new:
                            new_items_count += 1
            except Exception as e:
                log_event("ResearchAgent", f"Notice querying Google News for '{topic}': {e}", level="WARNING")

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
                pass

        log_event("ResearchAgent", f"✨ RESEARCH SCAN COMPLETE. Discovered {new_items_count} fresh AI news articles.", level="SUCCESS")
        return new_items_count

    def _is_topic_match(self, text: str, topics: list) -> bool:
        text_lower = text.lower()
        return any(t.lower() in text_lower for t in topics) or "ai" in text_lower or "model" in text_lower

    def _save_trend_item(self, title: str, url: str, source: str, summary: str, viral_score: float = 1.0) -> tuple:
        with Session(engine) as session:
            existing = session.exec(select(TrendItem).where(TrendItem.url == url)).first()
            if not existing:
                clean_summary = re.sub(r'<[^>]+>', '', summary)[:800]
                item = TrendItem(
                    title=title,
                    url=url,
                    source=source,
                    summary=clean_summary,
                    score=viral_score,
                    processed=False
                )
                session.add(item)
                session.commit()
                return True, item.id
            return False, existing.id
