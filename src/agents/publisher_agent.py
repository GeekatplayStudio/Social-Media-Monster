from sqlmodel import Session, select
from datetime import datetime
from src.core.db import engine, log_event, load_config
from src.core.models import PostDraft
from src.core.platforms import PlatformCredentialStore, PLATFORM_SPECS
from src.core.channel_clients import publish_to_channel


class PublisherAgent:
    """
    Publisher Agent:
    Dispatches approved drafts to X (Twitter), Instagram, Facebook, YouTube Community,
    Telegram, LinkedIn, Reddit, Discord and WordPress using the credentials stored
    (encrypted) via the dashboard's Channel Connections panel.

    A channel is only contacted when it is enabled and fully configured. Nothing is ever
    reported as published unless the remote service confirmed it.
    """

    def __init__(self):
        self.config = load_config().get("platforms", {})
        self.store = PlatformCredentialStore()

    def run(self, dry_run: bool = False) -> int:
        published_count = 0
        results = []

        with Session(engine) as session:
            drafts = session.exec(
                select(PostDraft).where(PostDraft.status == "approved")
            ).all()

            if not drafts:
                log_event("PublisherAgent", "No approved drafts are waiting to be published.")
                return 0

            for draft in drafts:
                outcome = self._publish_draft(draft, dry_run=dry_run)
                results.append((draft.platform, outcome))

                if outcome.ok and not dry_run:
                    draft.status = "published"
                    draft.published_at = datetime.now()
                    draft.external_post_id = outcome.external_id or None
                    session.add(draft)
                    published_count += 1
                    log_event("PublisherAgent",
                              f"Published post #{draft.id} to {draft.platform.upper()}"
                              + (f" ({outcome.url})" if outcome.url else ""),
                              level="SUCCESS")
                elif not outcome.ok:
                    log_event("PublisherAgent",
                              f"Post #{draft.id} not sent to {draft.platform.upper()}: {outcome.message}",
                              level="WARNING")

            session.commit()

        skipped = len(results) - published_count
        log_event("PublisherAgent",
                  f"Publish cycle complete: {published_count} sent, {skipped} skipped.",
                  level="SUCCESS" if published_count else "INFO")
        return published_count

    def _publish_draft(self, draft: PostDraft, dry_run: bool = False):
        from src.core.channel_clients import ChannelResult

        platform = draft.platform
        spec = PLATFORM_SPECS.get(platform)
        if not spec:
            return ChannelResult(False, f"No connection spec for '{platform}'.")

        summary = self.store.describe(platform)

        if not summary["enabled"]:
            return ChannelResult(False, "Channel is switched off in Channel Connections.")

        if not spec["can_post"]:
            return ChannelResult(False, spec["setup"])

        if not summary["configured"]:
            return ChannelResult(
                False,
                f"{spec['label']} has no credentials yet. Add them under Channel Connections.",
            )

        creds = self.store.get_credentials(platform)
        payload = {
            "headline": draft.headline or "",
            "content": draft.content or "",
            "image_path": draft.image_path or "",
            "public_image_url": self._public_image_url(creds, draft),
        }

        if dry_run:
            return ChannelResult(True, f"Dry run: {spec['label']} is connected and would receive this post.")

        return publish_to_channel(platform, creds, payload)

    @staticmethod
    def _public_image_url(creds: dict, draft: PostDraft) -> str:
        """
        Instagram fetches the image itself, so it needs a publicly reachable URL. This is
        only produced when the operator has configured a public base URL.
        """
        base = str(creds.get("public_image_base_url", "")).strip().rstrip("/")
        if not base or not draft.image_path:
            return ""
        return f"{base}/{draft.image_path}"

    def connection_report(self) -> list:
        """Per-channel readiness, used by the dashboard before a production run."""
        report = []
        for platform, spec in PLATFORM_SPECS.items():
            summary = self.store.describe(platform)
            report.append({
                "platform": platform,
                "label": spec["label"],
                "can_post": spec["can_post"],
                "enabled": summary["enabled"],
                "configured": summary["configured"],
                "status": summary["status"],
                "account": summary["account"],
            })
        return report
