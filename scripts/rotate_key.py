#!/usr/bin/env python
"""
Rotate the SocialMediaMonster credential master key.

Why this exists
---------------
`.env.secret` was committed to git in an earlier release, so the key it held must be
considered public. Anyone with the repository history can derive it. Rotating replaces
that key with a fresh one and re-encrypts every stored credential under it, which makes
the leaked key useless against current data.

What it does
------------
1. Reads the current key and decrypts every `ENC:` value held in the database.
2. Generates a new 256-bit key.
3. Re-encrypts every credential under the new key and writes it back in one transaction.
4. Writes the new key to `.env.secret` and preserves the old one as
   `.env.secret.revoked-<timestamp>` (git-ignored) so nothing is lost if a step fails.
5. Verifies that the new key decrypts the stored values and that the old key does not.

This does NOT rewrite git history. The old key stays in past commits; rotation is what
makes it worthless. Any credential that was encrypted under the old key and also exists
outside this database (the provider dashboards themselves) should still be regenerated
at the provider.

Usage
-----
    python scripts/rotate_key.py             # rotate, with confirmation
    python scripts/rotate_key.py --yes       # non-interactive
    python scripts/rotate_key.py --dry-run   # report what would change
"""
import os
import sys
import json
import argparse
from datetime import datetime

# Allow running as `python scripts/rotate_key.py` from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select  # noqa: E402
from src.core.db import engine, log_event  # noqa: E402
from src.core.models import SystemSetting  # noqa: E402
from src.core.security import SecurityManager, LEGACY_PREFIX  # noqa: E402

def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(LEGACY_PREFIX)


def transform(node, fn):
    """Walk a JSON structure and apply fn to every encrypted string in place."""
    if isinstance(node, dict):
        return {k: transform(v, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [transform(v, fn) for v in node]
    if is_encrypted(node):
        return fn(node)
    return node


def count_encrypted(node) -> int:
    total = 0
    if isinstance(node, dict):
        for v in node.values():
            total += count_encrypted(v)
    elif isinstance(node, list):
        for v in node:
            total += count_encrypted(v)
    elif is_encrypted(node):
        total = 1
    return total


def collect_rows(session):
    """Every SystemSetting row that holds at least one encrypted value."""
    found = []
    for row in session.exec(select(SystemSetting)).all():
        if not row.value or LEGACY_PREFIX not in row.value:
            continue
        try:
            parsed = json.loads(row.value)
            found.append((row, parsed, True))
        except (json.JSONDecodeError, TypeError):
            if is_encrypted(row.value):
                found.append((row, row.value, False))
    return found


def main():
    parser = argparse.ArgumentParser(description="Rotate the credential master key.")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="report without changing anything")
    parser.add_argument("--secret-file", default=os.environ.get("SMM_SECRET_FILE", ".env.secret"))
    args = parser.parse_args()

    secret_path = args.secret_file
    print("=" * 65)
    print(" SOCIAL MEDIA MONSTER - MASTER KEY ROTATION")
    print("=" * 65)

    if not os.path.exists(secret_path):
        print(f"\nNo existing key at {secret_path}.")
        print("Nothing to rotate - a fresh key is created automatically on first run.")
        return 0

    with open(secret_path, "rb") as f:
        old_key = f.read().strip()
    if not old_key:
        print(f"\nERROR: {secret_path} is empty. Refusing to proceed.")
        return 1

    old_sec = SecurityManager(secret_file=secret_path, master_key=old_key)

    # ---------------------------------------------------------------- survey
    with Session(engine) as session:
        rows = collect_rows(session)
        total = sum(count_encrypted(payload) for _, payload, _ in rows)

    print(f"\n  Key file          : {secret_path}")
    print(f"  Rows to re-encrypt: {len(rows)}")
    print(f"  Encrypted values  : {total}")

    # Confirm every value is readable before touching anything.
    unreadable = []
    for row, payload, _ in rows:
        def check(v):
            if not old_sec.decrypt_credential(v):
                unreadable.append(row.key_name)
            return v
        transform(payload, check)

    if unreadable:
        print(f"\nERROR: {len(unreadable)} value(s) could not be decrypted with the current key:")
        for name in sorted(set(unreadable)):
            print(f"    - {name}")
        print("Rotating now would destroy them. Restore the correct .env.secret first.")
        return 1

    if total:
        print("  All existing values decrypt cleanly with the current key.")

    if args.dry_run:
        print("\n[dry run] No changes written.")
        return 0

    if not args.yes:
        print("\n  The current key will be REVOKED and replaced.")
        print("  The old key is kept as a timestamped backup.")
        reply = input("\n  Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("  Aborted. Nothing changed.")
            return 1

    # ---------------------------------------------------------------- rotate
    new_key = SecurityManager.generate_master_key()
    new_sec = SecurityManager(secret_file=secret_path, master_key=new_key)

    rewritten = 0
    with Session(engine) as session:
        for row, payload, was_json in collect_rows(session):
            def reencrypt(v):
                nonlocal rewritten
                plain = old_sec.decrypt_credential(v)
                rewritten += 1
                return new_sec.encrypt_credential(plain)

            updated = transform(payload, reencrypt)
            row.value = json.dumps(updated) if was_json else updated
            session.add(row)
        # Single commit: either every credential moves to the new key, or none do.
        session.commit()

    # Preserve the old key before overwriting, in case anything needs recovery.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{secret_path}.revoked-{stamp}"
    with open(backup_path, "wb") as f:
        f.write(old_key)

    with open(secret_path, "wb") as f:
        f.write(new_key)
    try:
        os.chmod(secret_path, 0o600)
    except (OSError, NotImplementedError):
        pass

    # ---------------------------------------------------------------- verify
    print("\n  Verifying...")
    probe = "rotation-verification-canary"
    token = new_sec.encrypt_credential(probe)

    ok_new = new_sec.decrypt_credential(token) == probe
    ok_old_fails = old_sec.decrypt_credential(token) != probe

    reread = SecurityManager(secret_file=secret_path)
    ok_persisted = reread.decrypt_credential(token) == probe

    ok_stored = True
    with Session(engine) as session:
        for row, payload, _ in collect_rows(session):
            def check(v):
                nonlocal ok_stored
                if not reread.decrypt_credential(v):
                    ok_stored = False
                return v
            transform(payload, check)

    print(f"    new key decrypts new data      : {'PASS' if ok_new else 'FAIL'}")
    print(f"    old key CANNOT decrypt new data: {'PASS' if ok_old_fails else 'FAIL'}")
    print(f"    key persisted to disk          : {'PASS' if ok_persisted else 'FAIL'}")
    print(f"    stored credentials readable    : {'PASS' if ok_stored else 'FAIL'}")

    if not all([ok_new, ok_old_fails, ok_persisted, ok_stored]):
        print(f"\nERROR: verification failed. Old key preserved at {backup_path}")
        return 1

    log_event("SecurityManager", f"Master key rotated. {rewritten} credential(s) re-encrypted.", level="SUCCESS")

    print("\n" + "=" * 65)
    print(" ROTATION COMPLETE")
    print("=" * 65)
    print(f"\n  Credentials re-encrypted : {rewritten}")
    print(f"  Old key archived at      : {backup_path}")
    print("\n  The key exposed in git history no longer decrypts anything.")
    print("  Delete the archived key once you have confirmed everything works:")
    print(f"      rm {backup_path}")
    if rewritten == 0:
        print("\n  Note: no credentials were stored, so nothing needed re-encrypting.")
        print("  Any API keys you enter from now on use the new key.")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
