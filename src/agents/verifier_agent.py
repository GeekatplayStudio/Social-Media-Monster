from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import TrendItem, VerifiedNews
from src.core.llm_client import LLMClient

class VerifierAgent:
    def __init__(self):
        self.llm = LLMClient()

    def run(self) -> int:
        log_event("VerifierAgent", "Starting verification cycle on unverified trend items...")
        verified_count = 0

        with Session(engine) as session:
            unprocessed_items = session.exec(
                select(TrendItem).where(TrendItem.processed == False)
            ).all()

            for item in unprocessed_items:
                prompt = (
                    f"Headline: {item.title}\n"
                    f"Source: {item.source}\n"
                    f"Summary: {item.summary}\n\n"
                    f"Task: Verify this AI news item. Extract 3 clear technical facts/takeaways. "
                    f"Rate authority from 0.0 to 1.0. Format: FACTS: [bullet points]"
                )
                system_prompt = "You are a senior AI research fact-verifier. Filter out hype and verify technical accuracy."

                response = self.llm.generate(prompt, system_prompt=system_prompt)
                
                verified = VerifiedNews(
                    trend_id=item.id,
                    headline=item.title,
                    verified_facts=response,
                    source_reliability_score=0.9 if "RSS" in item.source else 0.75,
                    key_takeaways=response,
                    status="verified"
                )
                session.add(verified)
                item.processed = True
                session.add(item)
                session.commit()
                verified_count += 1
                log_event("VerifierAgent", f"Verified news item #{verified.id}: '{item.title[:60]}...'")

        log_event("VerifierAgent", f"Verification cycle complete. Processed {verified_count} news items.", level="SUCCESS")
        return verified_count
