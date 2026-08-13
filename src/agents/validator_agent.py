import re
from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import PostDraft
from src.core.llm_client import LLMClient
from src.agents.visual_agent import VisualAgent

# Phrases that mean the stored image_prompt is filler rather than a real scene description.
GENERIC_PROMPT_MARKERS = [
    "tech illustration",
    "vivid 16-bit rpg retro illustration concept",
    "generic",
]


class ValidatorAgent:
    """
    Final Content Manager QA Gate:
    1. Audits generated text for AI signatures. Rewrites text if AI score > 0.35.
    2. Validates image prompt relevance against the article topic. Repairs generic prompts.
    3. Approves passing drafts so the PublisherAgent has something to dispatch.
    """

    AI_SCORE_GATE = 0.35
    MIN_CONTENT_CHARS = 60

    def __init__(self):
        self.llm = LLMClient()

    def run(self) -> dict:
        log_event("ValidatorAgent", "Starting 2nd-pass Validation & QA Audit on post drafts...")
        text_fixes = 0
        prompt_fixes = 0
        approved = 0
        rejected = 0

        with Session(engine) as session:
            # Drafts that have completed humanization and are awaiting the QA gate.
            drafts = session.exec(
                select(PostDraft).where(PostDraft.status == "humanized")
            ).all()

            for draft in drafts:
                # Audit 1: AI Text Detection Check & Fix
                if draft.ai_detection_score > self.AI_SCORE_GATE or self._contains_ai_tropes(draft.content):
                    log_event("ValidatorAgent", f"Draft #{draft.id} flagged with elevated AI text score ({draft.ai_detection_score}). Rewriting for human voice...")

                    fix_prompt = (
                        f"Target Text:\n{draft.content}\n\n"
                        f"Problem: Text still sounds slightly robotic or AI-generated.\n"
                        f"Task: Rewrite into 100% natural, human-written text. Use sharp short sentences, "
                        f"vivid action verbs, punchy pacing, and remove all remaining AI filler. "
                        f"Preserve every fact and keep the post formatted for {draft.platform}."
                    )
                    system_prompt = "You are a master human editor. Make text sound completely human, organic, and punchy."
                    fixed_content = self.llm.generate(
                        fix_prompt,
                        system_prompt=system_prompt,
                        platform=draft.platform,
                        task="rewrite",
                    )

                    # Never let a failed rewrite blank out or replace a good draft.
                    if fixed_content and len(fixed_content) >= max(40, len(draft.content) * 0.4):
                        draft.content = fixed_content
                        draft.ai_detection_score = 0.12
                        text_fixes += 1
                    else:
                        log_event("ValidatorAgent", f"Rewrite for draft #{draft.id} rejected as unusable. Original copy retained.", level="WARNING")

                # Audit 2: Image Relevance Check & Prompt Enhancement
                if self._needs_image_prompt(draft.image_prompt):
                    log_event("ValidatorAgent", f"Draft #{draft.id} image prompt is generic. Upgrading prompt for visual relevance...")

                    prompt_req = (
                        f"Article Headline: {draft.headline}\n"
                        f"Post Content Summary: {draft.content[:400]}\n"
                        f"Task: Write one single-paragraph image generation prompt describing a "
                        f"16-bit RPG pixel art scene that depicts this exact story. Describe subject, "
                        f"setting, lighting and palette only. Output the prompt text and nothing else. "
                        f"Do not include hashtags, emoji, links, questions or marketing copy."
                    )
                    system_prompt = "You are a senior art director writing Flux/SDXL diffusion prompts. You output only the prompt."
                    new_prompt = self.llm.generate(
                        prompt_req,
                        system_prompt=system_prompt,
                        platform=draft.platform,
                        task="image_prompt",
                    )

                    if self._is_valid_image_prompt(new_prompt):
                        draft.image_prompt = new_prompt.strip()
                        prompt_fixes += 1
                    else:
                        # No usable model output: build the scene from the VisualAgent's
                        # subject-matter motifs rather than storing nothing.
                        draft.image_prompt = VisualAgent._build_vivid_comfy_prompt(
                            draft.headline, draft.content
                        )
                        prompt_fixes += 1
                        log_event("ValidatorAgent", f"Draft #{draft.id} image prompt built from story motifs (no model output).")

                # Audit 3: Final Content Manager approval gate
                if self._passes_quality_gate(draft):
                    draft.status = "approved"
                    approved += 1
                else:
                    draft.status = "needs_review"
                    rejected += 1
                    log_event("ValidatorAgent", f"Draft #{draft.id} held for manual review (QA gate not met).", level="WARNING")

                session.add(draft)
                session.commit()

        log_event(
            "ValidatorAgent",
            f"QA Audit complete: {text_fixes} text rewrites, {prompt_fixes} image prompts upgraded, "
            f"{approved} approved, {rejected} held for review.",
            level="SUCCESS",
        )
        return {
            "text_fixes": text_fixes,
            "prompt_fixes": prompt_fixes,
            "approved": approved,
            "held_for_review": rejected,
        }

    def _needs_image_prompt(self, image_prompt: str) -> bool:
        if not image_prompt or len(image_prompt.strip()) < 40:
            return True
        lowered = image_prompt.lower()
        if any(marker in lowered for marker in GENERIC_PROMPT_MARKERS):
            return True
        # A prompt carrying hashtags or links is a social post that leaked into the field.
        return not self._is_valid_image_prompt(image_prompt)

    @staticmethod
    def _is_valid_image_prompt(text: str) -> bool:
        """An image prompt must read as a scene description, not as a social post."""
        if not text or len(text.strip()) < 40:
            return False
        lowered = text.lower()
        if re.search(r'#\w+', text) or "http" in lowered:
            return False
        if text.count("?") > 0:
            return False
        return True

    def _passes_quality_gate(self, draft: PostDraft) -> bool:
        if not draft.content or len(draft.content.strip()) < self.MIN_CONTENT_CHARS:
            return False
        if draft.ai_detection_score > self.AI_SCORE_GATE:
            return False
        if self._contains_ai_tropes(draft.content):
            return False
        return True

    def _contains_ai_tropes(self, text: str) -> bool:
        tropes = ["delve", "testament", "tapestry", "in conclusion", "furthermore", "it is worth noting"]
        return any(t in (text or "").lower() for t in tropes)
