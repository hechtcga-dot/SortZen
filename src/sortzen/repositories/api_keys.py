"""API keys, stored in Windows Credential Manager (encrypted for the Windows user).

Keys never go into the program folder, the settings file or the repository. When no key is
saved, the service's environment variable is used (handy for development).
"""
from __future__ import annotations

import os

KEYRING_SERVICE = "SortZen"


class KeyStorageError(RuntimeError):
    """The system's secure key storage could not be used."""


def _system_backend():
    import keyring

    return keyring


class ApiKeyStore:
    def __init__(self, backend=None):
        self._backend = backend

    @property
    def backend(self):
        if self._backend is None:
            self._backend = _system_backend()
        return self._backend

    def load(self, service: str, env_var: str = "") -> str:
        try:
            value = self.backend.get_password(KEYRING_SERVICE, service) or ""
        except Exception:
            value = ""
        value = value.strip()
        if not value and env_var:
            value = os.getenv(env_var, "").strip()
        return value

    def save(self, service: str, key: str) -> None:
        key = (key or "").strip()
        if not key:
            raise ValueError("Enter an API key first.")
        try:
            self.backend.set_password(KEYRING_SERVICE, service, key)
        except Exception as exc:
            raise KeyStorageError(f"Windows couldn't save the key securely: {exc}") from exc

    def clear(self, service: str) -> None:
        try:
            self.backend.delete_password(KEYRING_SERVICE, service)
        except Exception:
            pass

    @staticmethod
    def masked(key: str) -> str:
        key = (key or "").strip()
        if len(key) <= 8:
            return "•" * len(key)
        return f"{key[:4]}…{key[-4:]}"
