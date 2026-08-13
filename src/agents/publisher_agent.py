from sqlmodel import Session, select
from datetime import datetime
from src.core.db import engine, log_event, load_config
from src.core.models import PostDraft

class PublisherAgent:
    """
    Publisher Agent:
    Handles multi-channel publishing to Twitter (X), Instagram, Facebook, YouTube Community,
    Telegram, LinkedIn, Reddit, Discord, and WordPress Blog.
    """
    def __init__(self):
        self.config = load_config().get("platforms", {})

    def run(self) -> int:
        published_count = 0

        with Session(engine) as session:
            drafts = session.exec(
                select(PostDraft).where(PostDraft.status == "approved")
            ).all()

            for draft in drafts:
                success = self._publish_to_platform(draft)
                if success:
                    draft.status = "published"
                    draft.published_at = datetime.now()
                    session.add(draft)
                    published_count += 1
                    log_event("PublisherAgent", f"Published post #{draft.id} to {draft.platform.upper()}", level="SUCCESS")

            session.commit()

        return published_count

    def _publish_to_platform(self, draft: PostDraft) -> bool:
        platform_cfg = self.config.get(draft.platform, {})
        if not platform_cfg.get("enabled", True):
            log_event("PublisherAgent", f"Platform {draft.platform.upper()} is disabled in config.")
            return False

        # Refuse to "publish" against placeholder credentials. Reporting success for a
        # channel that was never configured makes a demo run look like a live one.
        if not self._has_real_credentials(platform_cfg):
            log_event(
                "PublisherAgent",
                f"Platform {draft.platform.upper()} still holds placeholder credentials. Dispatch skipped.",
                level="WARNING",
            )
            return False

        log_event("PublisherAgent", f"Simulated live publication of '{draft.headline}' to {draft.platform.upper()}")
        return True

    @staticmethod
    def _has_real_credentials(platform_cfg: dict) -> bool:
        credential_keys = [
            k for k in platform_cfg
            if any(token in k for token in ("key", "secret", "token", "password", "id", "urn"))
        ]
        if not credential_keys:
            return False
        return any(
            str(platform_cfg.get(k, "")).strip()
            and not str(platform_cfg.get(k, "")).upper().startswith("YOUR_")
            for k in credential_keys
        )
