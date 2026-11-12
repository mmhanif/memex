"""The per-launch secret and one-time codes (SPEC §12, rules R5-R7).

The launcher opens `/auth?code=…`; redeeming the code sets the `memex_session`
cookie to the secret. The secret is never logged or sent in a response body.
"""

import secrets
import threading
from hmac import compare_digest

COOKIE = "memex_session"


class Session:
    def __init__(self) -> None:
        self.secret = secrets.token_hex(32)  # 256 bits
        self._codes: set[str] = set()
        self._lock = threading.Lock()

    def issue_code(self) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes.add(code)
        return code

    def redeem(self, code: str) -> bool:
        """True once per issued code; the code is burned on first use."""
        if not code.isascii():  # compare_digest only takes ASCII str
            return False
        with self._lock:
            # Compare against every outstanding code so timing reveals nothing.
            match = None
            for issued in self._codes:
                if compare_digest(issued, code):
                    match = issued
            if match is None:
                return False
            self._codes.discard(match)
            return True

    def is_valid_cookie(self, value: str | None) -> bool:
        return value is not None and value.isascii() and compare_digest(value, self.secret)
