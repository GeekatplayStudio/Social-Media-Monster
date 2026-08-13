import json
from sqlmodel import Session, select
from src.core.db import engine, log_event, load_config
from src.core.models import VerifiedNews, PostDraft, SystemSetting
from src.core.llm_client import LLMClient

ALL_PLATFORMS = ["twitter", "instagram", "facebook", "youtube", "telegram", "linkedin", "reddit", "discord", "wordpress"]

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

        with Session(engine) as session:
            verified_items = session.exec(
                select(VerifiedNews).where(VerifiedNews.status == "verified")
            ).all()

            if not verified_items:
                log_event("WriterAgent", "No verified news items found to write posts for.")
                return 0

            max_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "max_articles_per_cycle")).first()
            max_posts = int(max_setting.value) if max_setting and max_setting.value else 2
            
            selected_items = verified_items[:max_posts]

            for item in selected_items:
                for platform in ALL_PLATFORMS:
                    draft = self._generate_draft_for_platform(item, platform, target_persona_key, eq, sample_article)
                    session.add(draft)
                    generated_count += 1

            session.commit()

        log_event("WriterAgent", f"Writer cycle complete. Drafted {generated_count} tailored posts across all platforms.", level="SUCCESS")
        return generated_count

    def _generate_draft_for_platform(self, news: VerifiedNews, platform: str, persona_key: str, eq: dict, sample_article: str) -> PostDraft:
        eq_summary = (
            f"Equalizer Profile (-1.0 to +1.0):\n"
            f"- Seriousness: {eq.get('seriousness', 0.2):.1f} (-1=Hilarious/Funny, +1=Academic/Serious)\n"
            f"- Formality: {eq.get('formality', -0.2):.1f} (-1=Casual Slang, +1=Corporate Formal)\n"
            f"- Cynicism/Sarcasm: {eq.get('cynicism', 0.4):.1f} (-1=Optimistic Hype, +1=Highly Sarcastic/Skeptical)\n"
            f"- Technical Depth: {eq.get('technical_depth', 0.6):.1f} (-1=Simple ELI5, +1=PhD Code-Heavy)\n"
            f"- Political/Controversial: {eq.get('political_stance', 0.0):.1f} (-1=Neutral Safe, +1=Provocative Hot-Take)\n"
            f"- Pacing/Length: {eq.get('pacing_length', -0.3):.1f} (-1=Punchy One-Liners, +1=Long-Form Deep Essay)\n"
            f"- Emotional Warmth: {eq.get('emotional_warmth', 0.1):.1f} (-1=Cold Machine, +1=Warm Empathetic)\n"
            f"- Storytelling & Drama: {eq.get('storytelling_drama', 0.5):.1f} (-1=Direct Facts, +1=Cinematic Narrative)\n"
            f"- Authority & Confidence: {eq.get('authority_boldness', 0.7):.1f} (-1=Humble Inquiring, +1=Bold Unapologetic)\n"
            f"- Metaphor Density: {eq.get('metaphor_density', 0.4):.1f} (-1=Literal Facts, +1=Rich Metaphors)\n"
            f"- Clickbait Energy: {eq.get('clickbait_energy', 0.6):.1f} (-1=Modest, +1=Viral High-CTR Hook)\n"
            f"- Tech Jargon: {eq.get('tech_jargon', 0.3):.1f} (-1=Plain English, +1=Heavy Tech Jargon)\n"
            f"- Action CTA: {eq.get('action_cta', 0.5):.1f} (-1=Passive, +1=Direct Call-to-Action)\n"
            f"- Humor Type: {eq.get('humor_type', 0.2):.1f} (-1=Dry/Dark, +1=Witty/Playful Slapstick)\n"
            f"- Provocativeness: {eq.get('provocativeness', 0.4):.1f} (-1=Consensus, +1=Contrarian Disruptive)\n"
        )

        sample_prompt = f"\nAuthor Sample Article (Clone this exact style, sentence rhythm, and vocabulary):\n\"\"\"{sample_article[:1000]}\"\"\"\n" if sample_article else ""

        prompt = (
            f"Headline: {news.headline}\n"
            f"Verified Facts: {news.verified_facts}\n"
            f"Key Takeaways: {news.key_takeaways}\n"
            f"Target Platform: {platform}\n\n"
            f"{eq_summary}\n"
            f"{sample_prompt}\n"
            f"Task: Write a high-converting post tailored for {platform}. "
            f"Incorporate the author's writing fingerprint and exact equalizer fine-tuning profile."
        )

        system_prompt = (
            f"You are a master copywriter fine-tuned with precision equalizer controls. "
            f"Adhere strictly to the requested style slider values and sample article voice."
        )

        content = self.llm.generate(prompt, system_prompt=system_prompt)
        headline = f"{news.headline} [{platform.upper()}]"

        return PostDraft(
            verified_news_id=news.id,
            platform=platform,
            persona_key=persona_key,
            headline=headline,
            content=content,
            status="draft"
        )
