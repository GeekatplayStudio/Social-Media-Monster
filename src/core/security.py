import os
import re
import base64
import hashlib

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _FERNET_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only where cryptography is absent
    Fernet = None
    InvalidToken = Exception
    _FERNET_AVAILABLE = False

# Fernet-encrypted values carry this marker. Values written before the upgrade use the
# bare "ENC:" prefix and are still readable through the legacy XOR path.
V2_PREFIX = "ENC:v2:"
LEGACY_PREFIX = "ENC:"
PBKDF2_SALT = b"socialmediamonster.credential.v2"
PBKDF2_ITERATIONS = 480_000


class SecurityManager:
    """
    Credential & Payload Security Module:
    1. PBKDF2-HMAC-SHA256 derived Fernet (AES-128-CBC + HMAC-SHA256) credential encryption.
       Values encrypted by the previous XOR build still decrypt transparently.
    2. Input/Output payload sanitization and prompt-injection defense for the Abstract API Layer.
    3. Redaction of sensitive credentials and API keys in outbound responses.
    """

    def __init__(self, secret_file: str = None):
        self.secret_file = secret_file or os.environ.get("SMM_SECRET_FILE", ".env.secret")
        self.master_key = self._get_or_create_master_key()
        self._fernet = self._build_fernet()

    # ------------------------------------------------------------------ key material

    def _get_or_create_master_key(self) -> bytes:
        env_key = os.environ.get("SMM_MASTER_KEY", "").strip()
        if env_key:
            return env_key.encode("utf-8")

        if os.path.exists(self.secret_file):
            try:
                with open(self.secret_file, "rb") as f:
                    existing = f.read().strip()
                    if existing:
                        return existing
            except Exception:
                pass

        # Generate random 256-bit key
        key = base64.urlsafe_b64encode(os.urandom(32))
        try:
            with open(self.secret_file, "wb") as f:
                f.write(key)
            # Best effort: keep the key readable by its owner only (no-op on some filesystems).
            try:
                os.chmod(self.secret_file, 0o600)
            except (OSError, NotImplementedError):
                pass
        except Exception:
            pass
        return key

    def _build_fernet(self):
        if not _FERNET_AVAILABLE:
            return None
        try:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=PBKDF2_SALT,
                iterations=PBKDF2_ITERATIONS,
            )
            derived = base64.urlsafe_b64encode(kdf.derive(self.master_key))
            return Fernet(derived)
        except Exception:
            return None

    # ------------------------------------------------------------------ legacy cipher

    def _legacy_cipher(self, data: str, decrypt: bool = False) -> str:
        """XOR stream used by the previous build. Retained for reading old records only."""
        if not data:
            return ""

        key_bytes = hashlib.sha256(self.master_key).digest()
        if not decrypt:
            raw = data.encode('utf-8')
            xored = bytes(raw[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(raw)))
            return LEGACY_PREFIX + base64.urlsafe_b64encode(xored).decode('utf-8')

        if not data.startswith(LEGACY_PREFIX):
            return data  # Return plain text if not encrypted yet
        try:
            xored = base64.urlsafe_b64decode(data[len(LEGACY_PREFIX):].encode('utf-8'))
            raw = bytes(xored[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(xored)))
            return raw.decode('utf-8')
        except Exception:
            return data

    # ------------------------------------------------------------------ public API

    def encrypt_credential(self, plain_text: str) -> str:
        if not plain_text or plain_text.startswith(LEGACY_PREFIX):
            return plain_text
        if self._fernet is not None:
            try:
                token = self._fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")
                return V2_PREFIX + token
            except Exception:
                pass
        # cryptography unavailable - fall back so credentials are still not stored in clear.
        return self._legacy_cipher(plain_text, decrypt=False)

    def decrypt_credential(self, cipher_text: str) -> str:
        if not cipher_text:
            return ""
        if cipher_text.startswith(V2_PREFIX):
            if self._fernet is None:
                return ""
            try:
                return self._fernet.decrypt(cipher_text[len(V2_PREFIX):].encode("utf-8")).decode("utf-8")
            except InvalidToken:
                return ""
            except Exception:
                return ""
        return self._legacy_cipher(cipher_text, decrypt=True)

    def sanitize_input_payload(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return ""

        # Strip dangerous HTML script tags, control chars, recursive prompts
        clean = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<\s*/?\s*(script|iframe|object|embed)[^>]*>', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'(?:Key Technical Insights:\s*|Original Text:\s*)+', '', clean)
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean)
        return clean.strip()

    def sanitize_output_payload(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return ""

        # Redact API keys matching common provider patterns. Longest/most specific first,
        # otherwise a generic rule consumes the prefix of a more specific one.
        redacted = re.sub(r'sk-ant-[A-Za-z0-9_\-]{20,}', '[REDACTED_CLAUDE_KEY]', text)
        redacted = re.sub(r'tvly-[A-Za-z0-9_\-]{16,}', '[REDACTED_TAVILY_KEY]', redacted)
        redacted = re.sub(r'sk-[A-Za-z0-9_\-]{20,}', '[REDACTED_API_KEY]', redacted)
        redacted = re.sub(r'AIzaSy[A-Za-z0-9_\-]{20,}', '[REDACTED_GEMINI_KEY]', redacted)
        redacted = re.sub(r'\bxox[baprs]-[A-Za-z0-9\-]{10,}', '[REDACTED_TOKEN]', redacted)
        return redacted
