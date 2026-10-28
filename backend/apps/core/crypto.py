"""Encryption for sensitive values stored in the database (e.g. authenticator secrets).

The key comes from the FIELD_ENCRYPTION_KEY environment variable and is never stored in the
repository or the database.
"""

from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
