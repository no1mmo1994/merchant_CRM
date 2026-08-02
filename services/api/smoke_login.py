"""Smoke-test: encrypt_token + decrypt_token with the loaded Fernet key.

Proves the runtime path that was 500-ing is now alive, without needing
to clear SlowAPI's 60/min sliding window.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure we're running as if from services/api/ (uvicorn's cwd).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import settings  # noqa: E402
from app.core.security import (  # noqa: E402
    TokenEncryptionNotConfigured,
    decrypt_token,
    encrypt_token,
)

assert settings.token_encryption_key, "token_encryption_key still empty!"
sample = "eyJhbGciOiJIUzI1NiJ9." + ("X" * 256)
cipher = encrypt_token(sample)
recovered = decrypt_token(cipher)
assert recovered == sample, "round-trip failed"
print(f"OK: key_prefix={settings.token_encryption_key[:8]!r}")
print(f"OK: cipher_len={len(cipher)} plaintext_len={len(recovered)}")
