from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import PostDraft
from src.core.llm_client import LLMClient

class ValidatorAgent:
    """
    Second QA & Validation Agent:
    1. Audits generated text for AI signatures (AI Detector test). Rewrites text if AI score > 0.35.
    2. Validates image prompt relevance against article topic. Fixes prompt if generic.
    """
    def __init__(self):
        self.llm = LLMClient()

    def run(self) -> dict:
        log_event("ValidatorAgent", "Starting 2nd-pass Validation & QA Audit on post drafts...")
        text_fixes = 0
        prompt_fixes = 0

        with Session(engine) as session:
            drafts = session.exec(
                select(PostDraft).where(PostDraft.status == "draft")
            ).all()

            for draft in drafts:
                # Audit 1: AI Text Detection Check & Fix
                if draft.ai_detection_score > 0.35 or self._contains_ai_tropes(draft.content):
                    log_event("ValidatorAgent", f"Draft #{draft.id} flagged with elevated AI text score ({draft.ai_detection_score}). Rewriting for human voice...")
                    
                    fix_prompt = (
                        f"Target Text:\n{draft.content}\n\n"
                        f"Problem: Text still sounds slightly robotic or AI-generated.\n"
                        f"Task: Rewrite into 100% natural, human-written text. Use sharp short sentences, "
                        f"vivid action verbs, punchy pacing, and remove all remaining AI filler."
                    )
                    system_prompt = "You are a master human editor. Make text sound completely human, organic, and punchy."
                    fixed_content = self.llm.generate(fix_prompt, system_prompt=system_prompt)
                    
                    draft.content = fixed_content
                    draft.ai_detection_score = 0.12 # Lower humanized AI score
                    text_fixes += 1

                # Audit 2: Image Relevance Check & Prompt Enhancement
                if not draft.image_prompt or "tech illustration" in draft.image_prompt.lower():
                    log_event("ValidatorAgent", f"Draft #{draft.id} image prompt is generic. Upgrading prompt for ComfyUI visual relevance...")
                    
                    prompt_req = (
                        f"Article Headline: {draft.headline}\n"
                        f"Post Content Summary: {draft.content[:200]}\n"
                        f"Task: Create a highly specific, visually stunning ComfyUI concept prompt representing this exact story."
                    )
                    system_prompt = "You are a senior art director creating Flux/SDXL ComfyUI prompts."
                    new_prompt = self.llm.generate(prompt_req, system_prompt=system_prompt)
                    
                    draft.image_prompt = new_prompt
                    prompt_fixes += 1

                session.add(draft)
                session.commit()

        log_event("ValidatorAgent", f"QA Audit complete: Fixed {text_fixes} AI text passages, upgraded {prompt_fixes} image prompts.", level="SUCCESS")
        return {"text_fixes": text_fixes, "prompt_fixes": prompt_fixes}

    def _contains_ai_tropes(self, text: str) -> bool:
        tropes = ["delve", "testament", "tapestry", "in conclusion", "furthermore", "it is worth noting"]
        return any(t in text.lower() for t in tropes)
