import json
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import VerifiedNews, PostDraft, SystemSetting, TrendItem
from src.core.llm_client import LLMClient
from src.agents.research_agent import ResearchAgent
from src.agents.verifier_agent import VerifierAgent
from src.agents.humanizer_agent import HumanizerAgent

ALL_PLATFORMS = ["twitter", "instagram", "facebook", "youtube", "telegram", "linkedin", "reddit", "discord", "wordpress", "autoagent"]

# Channel-native briefs. Without these every platform received an identical instruction
# and the model had no reason to produce anything but the same post nine times.
PLATFORM_BRIEFS = {
    "twitter": "Under 280 characters total. One sharp hook line, one concrete detail, at most 2 hashtags. No preamble.",
    "instagram": "Caption voice. Short lines with breathing room, a vivid opening image, 5-8 hashtags in a block at the end.",
    "facebook": "Conversational, 2-4 short paragraphs, plain language, close with a genuine question to the reader.",
    "youtube": "Community post. Punchy update, 2-3 bullet lines, end with a poll or a direct callout to subscribers.",
    "telegram": "Fast broadcast. Bold the headline, 3 tight bullet lines, no fluff, no hashtags.",
    "linkedin": "Professional analysis. Strong first line, 3-5 structured bullets with specifics, one takeaway line, 3-4 industry hashtags.",
    "reddit": "Technical breakdown for a dev subreddit. Markdown headers, real detail, no marketing tone, no hashtags, end with a genuine discussion question.",
    "discord": "Announcement. Bold title, short blockquote bullets, casual and direct, no hashtags.",
    "wordpress": "Full blog article, 500-800 words, markdown H2 subheadings, an intro, analysis with specifics, and a conclusion.",
    "autoagent": "Technical blog article for AutoAgent. Clean HTML formatting, bold section headers, intro summary, code block placeholders if code present, crisp conclusion.",
}

class WriterAgent:
    """
    Writer Agent with Fine-Tuning Equalizer & Voice Cloning Engine:
    Reads 15 fine-tuning style sliders (-1 to +1) and user sample articles to clone style,
    tone, rhythm, and humor levels precisely for each target platform.
    """
    def __init__(self):
        self.llm = LLMClient()

    def get_equalizer_settings(self) -> dict:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "writer_equalizer_settings")).first()
            if setting and setting.value:
                try:
                    return json.loads(setting.value)
                except Exception:
                    pass
        return {}

    def get_sample_writing_article(self) -> str:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "sample_writing_article")).first()
            if setting and setting.value:
                return setting.value
        return ""

    def run(self, target_persona_key: str = "tech_visionary") -> int:
        eq = self.get_equalizer_settings()
        sample_article = self.get_sample_writing_article()

        log_event("WriterAgent", "Generating platform posts with Fine-Tune Equalizer & Voice Sample...")
        generated_count = 0

        # Phase 1 - read what is needed, then release the connection.
        # Generation calls the model and writes log lines through their own connections.
        # Holding an open write transaction across that work made SQLite report
        # "database is locked", because the logger could never acquire the write lock.
        with Session(engine) as session:
            verified_items = session.exec(
                select(VerifiedNews).where(VerifiedNews.status == "verified")
            ).all()

            if not verified_items:
                log_event("WriterAgent", "No verified news items found to write posts for.")
                return 0

            max_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "max_articles_per_cycle")).first()
            max_posts = int(max_setting.value) if max_setting and max_setting.value else 2

            # Detached copies so attributes stay readable once the session is closed.
            selected_items = [
                VerifiedNews(
                    id=item.id, trend_id=item.trend_id, headline=item.headline,
                    verified_facts=item.verified_facts, key_takeaways=item.key_takeaways,
                )
                for item in verified_items[:max_posts]
            ]

            already_drafted = {
                (d.verified_news_id, d.platform)
                for d in session.exec(
                    select(PostDraft).where(
                        PostDraft.verified_news_id.in_([i.id for i in selected_items])
                    )
                ).all()
            }

        # Phase 2 - generate with no session held open.
        pending_drafts = []
        for item in selected_items:
            for platform in ALL_PLATFORMS:
                if (item.id, platform) in already_drafted:
                    continue
                pending_drafts.append(
                    self._generate_draft_for_platform(item, platform, target_persona_key, eq, sample_article)
                )
                generated_count += 1

        # Phase 3 - persist in one short transaction.
        with Session(engine) as session:
            for draft in pending_drafts:
                session.add(draft)

            # Mark each story as written. Without this the same verified news is
            # re-drafted on every cycle, multiplying identical posts indefinitely.
            for item in selected_items:
                stored = session.get(VerifiedNews, item.id)
                if stored:
                    stored.status = "drafted"
                    session.add(stored)

            session.commit()

        log_event("WriterAgent", f"Writer cycle complete. Drafted {generated_count} tailored posts across all platforms.", level="SUCCESS")
        return generated_count

    def generate_single_test_article(self, post_id: int) -> dict:
        eq = self.get_equalizer_settings()
        sample_article = self.get_sample_writing_article()

        with Session(engine) as session:
            draft = session.get(PostDraft, post_id)
            if not draft:
                return {"error": "Post draft not found"}

            log_event("WriterAgent", f"Generating SINGLE TEST ARTICLE for Post #{draft.id} ({draft.platform})...")

            # Verify associated news or fetch fresh trend item
            news = session.get(VerifiedNews, draft.verified_news_id) if draft.verified_news_id else None
            if not news:
                # Run quick scan if needed
                ResearchAgent().run()
                VerifierAgent().run()
                news = session.exec(select(VerifiedNews).where(VerifiedNews.status == "verified")).first()

            if not news:
                news = VerifiedNews(
                    trend_id=1,
                    headline="Breakthrough in Autonomous Multi-Agent AI Frameworks",
                    verified_facts="Multi-agent orchestration reduces execution latency by 45% and improves task accuracy.",
                    key_takeaways="Scalable agent systems, local LLM execution, zero-latency state persistence."
                )

            new_draft = self._generate_draft_for_platform(news, draft.platform, draft.persona_key, eq, sample_article)
            draft.headline = new_draft.headline
            draft.content = new_draft.content

            # Score the copy that was actually produced. The previous version stamped a
            # fixed 94.5% CTR / 0.04 AI score and auto-approved, so the dashboard reported
            # results that had never been measured and the QA gate was bypassed.
            scorer = HumanizerAgent()
            draft.ai_detection_score = scorer._estimate_ai_score(draft.content)
            draft.ctr_score = scorer._calculate_ctr_score(draft.headline, draft.content)
            draft.status = "draft"

            session.add(draft)
            session.commit()

            log_event("WriterAgent", f"Successfully generated single test article for Post #{draft.id} ({draft.platform})", level="SUCCESS")
            return {
                "id": draft.id,
                "platform": draft.platform,
                "headline": draft.headline,
                "content": draft.content,
                "ctr_score": draft.ctr_score,
                "ai_detection_score": draft.ai_detection_score
            }

    def _generate_draft_for_platform(self, news: VerifiedNews, platform: str, persona_key: str, eq: dict, sample_article: str) -> PostDraft:
        eq_summary = (
            f"Equalizer Profile (-1.0 to +1.0):\n"
            f"- Seriousness: {eq.get('seriousness', 0.2):.1f} (-1=Funny, +1=Serious)\n"
            f"- Formality: {eq.get('formality', -0.2):.1f} (-1=Slang, +1=Formal)\n"
            f"- Cynicism/Sarcasm: {eq.get('cynicism', 0.4):.1f} (-1=Hype, +1=Sarcastic)\n"
            f"- Technical Depth: {eq.get('technical_depth', 0.6):.1f} (-1=ELI5, +1=Code)\n"
            f"- Political/Controversial: {eq.get('political_stance', 0.0):.1f} (-1=Safe, +1=Hot-Take)\n"
            f"- Pacing/Length: {eq.get('pacing_length', -0.3):.1f} (-1=Punchy, +1=Deep Essay)\n"
            f"- Emotional Warmth: {eq.get('emotional_warmth', 0.1):.1f} (-1=Cold, +1=Warm)\n"
            f"- Storytelling & Drama: {eq.get('storytelling_drama', 0.5):.1f} (-1=Facts, +1=Drama)\n"
            f"- Authority & Confidence: {eq.get('authority_boldness', 0.7):.1f} (-1=Humble, +1=Bold)\n"
            f"- Metaphor Density: {eq.get('metaphor_density', 0.4):.1f} (-1=Literal, +1=Metaphor)\n"
            f"- Clickbait Energy: {eq.get('clickbait_energy', 0.6):.1f} (-1=Modest, +1=Viral)\n"
            f"- Tech Jargon: {eq.get('tech_jargon', 0.3):.1f} (-1=Plain, +1=Jargon)\n"
            f"- Action CTA: {eq.get('action_cta', 0.5):.1f} (-1=Passive, +1=Direct)\n"
            f"- Humor Type: {eq.get('humor_type', 0.2):.1f} (-1=Dry, +1=Witty)\n"
            f"- Provocativeness: {eq.get('provocativeness', 0.4):.1f} (-1=Consensus, +1=Contrarian)\n"
        )

        sample_prompt = f"\nAuthor Sample Article (Clone this exact style):\n\"\"\"{sample_article[:1000]}\"\"\"\n" if sample_article else ""

        brief = PLATFORM_BRIEFS.get(platform, "Write a clear, specific post for this channel.")

        prompt = (
            f"Headline: {news.headline}\n"
            f"Verified Facts: {news.verified_facts}\n"
            f"Key Takeaways: {news.key_takeaways}\n"
            f"Target Platform: {platform}\n\n"
            f"{eq_summary}\n"
            f"{sample_prompt}\n"
            f"Task: Write one post for {platform}.\n"
            f"Channel brief: {brief}\n"
            f"Ground every sentence in the verified facts above - do not invent numbers, "
            f"companies, product names or quotes that are not there. Do not write a preamble, "
            f"do not explain what you are doing, and output only the post itself."
        )

        system_prompt = (
            f"You are a master copywriter fine-tuned with precision equalizer controls, writing for {platform}. "
            f"Adhere strictly to the requested style slider values and sample article voice. "
            f"You never fabricate facts and you never output meta-commentary."
        )

        content = self.llm.generate(prompt, system_prompt=system_prompt, platform=platform, task="post")
        headline = news.headline

        return PostDraft(
            verified_news_id=news.id,
            platform=platform,
            persona_key=persona_key,
            headline=headline,
            content=content,
            status="draft"
        )
