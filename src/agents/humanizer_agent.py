import re
from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import PostDraft, PersonaProfile
from src.core.llm_client import LLMClient

class HumanizerAgent:
    def __init__(self):
        self.llm = LLMClient()
        # Words and phrases that trigger AI content detectors
        self.ai_trope_words = [
            "delve", "tapestry", "testament", "in conclusion", "furthermore", 
            "moreover", "it is worth noting", "spearhead", "beacon", "game-changer",
            "unlocking", "revolutionize", "pivotal", "in the realm of"
        ]

    def run(self) -> int:
        log_event("HumanizerAgent", "Running Humanizer & CTR/SEO Optimization Agent...")
        optimized_count = 0

        with Session(engine) as session:
            # Only untouched drafts. Re-humanizing an already-humanized post degrades it
            # a little more on every cycle and burns provider tokens for no gain.
            drafts = session.exec(
                select(PostDraft).where(PostDraft.status == "draft")
            ).all()

            for draft in drafts:
                # 1. Strip robotic AI tropes
                humanized_content = self._remove_ai_tropes(draft.content)

                # 2. Perplexity and burstiness refinement via LLM
                persona = session.exec(
                    select(PersonaProfile).where(PersonaProfile.key_name == draft.persona_key)
                ).first()
                
                sample_voice = persona.sample_posts if persona and persona.sample_posts else ""

                system_prompt = (
                    "You are an expert copy editor specializing in anti-AI detection humanization and CTR growth. "
                    "Rewrite text to sound 100% natural, conversational, and human. Vary sentence lengths dramatically. "
                    "Use active voice, colloquial rhythm, and relatable analogies."
                )
                
                prompt = (
                    f"Original Text:\n{humanized_content}\n\n"
                    f"Target Persona Voice Sample:\n{sample_voice[:300]}\n\n"
                    f"Task: Rewrite the text to eliminate all robotic patterns while preserving the core facts. "
                    f"Ensure high CTR engagement hooks."
                )

                # Pass the draft's own platform through, otherwise the client formats every
                # channel as a tweet. task="rewrite" keeps this a rewrite of the caller's
                # text rather than the generation of a brand new post.
                refined_text = self.llm.generate(
                    prompt,
                    system_prompt=system_prompt,
                    platform=draft.platform,
                    task="rewrite",
                )

                # A rewrite that came back empty or gutted is discarded - keep the original.
                if not refined_text or len(refined_text) < max(40, len(humanized_content) * 0.4):
                    log_event(
                        "HumanizerAgent",
                        f"Rewrite for draft #{draft.id} was too short to trust. Keeping original copy.",
                        level="WARNING",
                    )
                    refined_text = humanized_content

                # 3. Calculate scores
                ai_score = self._estimate_ai_score(refined_text)
                ctr_score = self._calculate_ctr_score(draft.headline, refined_text)

                # 4. Extract SEO Keywords
                seo_keywords = ", ".join(re.findall(r'\b[A-Z][a-z]{3,}\b', refined_text)[:5])

                # Update draft
                draft.content = refined_text
                draft.ai_detection_score = ai_score
                draft.ctr_score = ctr_score
                draft.seo_keywords = seo_keywords
                draft.status = "humanized"
                session.add(draft)
                session.commit()
                optimized_count += 1

        log_event("HumanizerAgent", f"Humanizer cycle complete. Optimized {optimized_count} drafts for CTR/SEO.", level="SUCCESS")
        return optimized_count

    def _remove_ai_tropes(self, text: str) -> str:
        cleaned = text
        replacements = {
            r"\bdelve into\b": "explore",
            r"\btestament to\b": "proof of",
            r"\bin conclusion\b": "bottom line",
            r"\bgame-changer\b": "major shift",
            r"\bin the realm of\b": "in",
            r"\bit is worth noting that\b": "note that"
        }
        for pattern, replacement in replacements.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned

    def _estimate_ai_score(self, text: str) -> float:
        """
        Estimates AI detection probability (0.0 = completely human, 1.0 = obvious ChatGPT bot).
        Checks trope frequency and sentence variance.
        """
        lowered = (text or "").lower()
        words = lowered.split()
        if not words:
            return 0.5

        # Match on the full text: most entries in the trope list are phrases, so token
        # membership testing could never fire for "in conclusion" or "in the realm of".
        trope_matches = sum(lowered.count(trope) for trope in self.ai_trope_words)
        trope_ratio = trope_matches / max(len(words), 1)

        sentences = [s for s in re.split(r'[.!?]', text) if s.strip()]
        sentence_lengths = [len(s.split()) for s in sentences]
        
        if len(sentence_lengths) > 1:
            mean_len = sum(sentence_lengths) / len(sentence_lengths)
            variance = sum((l - mean_len) ** 2 for l in sentence_lengths) / len(sentence_lengths)
            # Low variance (uniform sentence lengths) indicates AI text
            burstiness_factor = 1.0 / (1.0 + (variance ** 0.5))
        else:
            burstiness_factor = 0.5

        score = min(1.0, max(0.05, (trope_ratio * 10.0) + (burstiness_factor * 0.4)))
        return round(score, 2)

    def _calculate_ctr_score(self, headline: str, content: str) -> float:
        """
        Estimates Click-Through-Rate potential (0-100 score).
        Checks for curiosity words, power verbs, questions, numbers.
        """
        score = 60.0
        headline_lower = headline.lower()

        power_words = ["secret", "breakthrough", "stop", "why", "how", "future", "new", "truth", "warning", "benchmark"]
        for pw in power_words:
            if pw in headline_lower:
                score += 5.0
        
        if "?" in headline or "!" in headline:
            score += 4.0
        if any(char.isdigit() for char in headline):
            score += 5.0

        return min(99.0, round(score, 1))
