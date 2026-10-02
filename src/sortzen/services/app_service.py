"""Program-wide service: settings, AI service choice, API keys, scanning and background jobs."""
from __future__ import annotations

import os
from typing import Callable

from ..ai.services import DEFAULT_SERVICE, OLLAMA_URL, SERVICES, make_provider
from ..config import AppPaths, default_paths
from ..repositories.api_keys import ApiKeyStore
from ..repositories.file_index import FileIndex, path_key
from ..repositories.settings import SettingsRepository
from ..scanning.records import ScanSummary
from ..scanning.scanner import Scanner
from ..tasks import JobRunner


class AppService:
    def __init__(self, paths: AppPaths | None = None, keys: ApiKeyStore | None = None):
        self.paths = paths or default_paths()
        self.settings = SettingsRepository(self.paths.settings_path)
        self.keys = keys or ApiKeyStore()
        self.jobs = JobRunner()
        self.index = FileIndex(self.paths.database_path)
        self.scanner = Scanner(self.index)

    # ---------------------------------------------------------------- AI service
    def ai_service(self) -> str:
        service = self.settings.get("ai_service", DEFAULT_SERVICE)
        return service if service in SERVICES else DEFAULT_SERVICE

    def set_ai_service(self, service: str) -> None:
        if service not in SERVICES:
            raise ValueError(f"Unknown AI service: {service}")
        self.settings.set("ai_service", service)

    def model(self, service: str | None = None) -> str:
        service = service or self.ai_service()
        models = self.settings.get("ai_models") or {}
        return str(models.get(service) or SERVICES[service].default_model)

    def set_model(self, model: str, service: str | None = None) -> None:
        service = service or self.ai_service()
        models = dict(self.settings.get("ai_models") or {})
        model = (model or "").strip()
        if model and model != SERVICES[service].default_model:
            models[service] = model
        else:
            models.pop(service, None)
        self.settings.set("ai_models", models)

    def ollama_url(self) -> str:
        return str(self.settings.get("ollama_url") or OLLAMA_URL)

    # ---------------------------------------------------------------- API keys
    def api_key(self, service: str | None = None) -> str:
        service = service or self.ai_service()
        info = SERVICES[service]
        return self.keys.load(service, info.key_env) if info.needs_key else ""

    def has_api_key(self, service: str | None = None) -> bool:
        service = service or self.ai_service()
        return not SERVICES[service].needs_key or bool(self.api_key(service))

    def save_api_key(self, key: str, service: str | None = None) -> None:
        self.keys.save(service or self.ai_service(), key)

    def clear_api_key(self, service: str | None = None) -> None:
        self.keys.clear(service or self.ai_service())

    def provider(self):
        service = self.ai_service()
        return make_provider(service, self.api_key(service), self.ollama_url())

    # ---------------------------------------------------------------- scanning
    def scan_folders(self, sources, destinations, emit=None, token=None) -> list[ScanSummary]:
        """Scan source folders (their own files) and destination folders (with subfolders).

        A destination inside another destination is scanned once, as part of the outer one,
        and source folders inside a destination are left out of the destination's scan.
        """
        summaries = []
        for root in sources:
            summaries.append(self.scanner.scan(root, "source", recursive=False, emit=emit, token=token))
            if summaries[-1].cancelled:
                return summaries
        for root in _outermost(destinations):
            summaries.append(self.scanner.scan(root, "destination", recursive=True, exclude=sources,
                                               emit=emit, token=token))
            if summaries[-1].cancelled:
                return summaries
        return summaries

    # ---------------------------------------------------------------- background jobs
    def run_job(self, name: str, work: Callable, on_event: Callable):
        return self.jobs.start(name, work, on_event)

    def stop_job(self) -> None:
        self.jobs.cancel()


def _outermost(folders) -> list:
    keys = {path_key(f): f for f in folders}

    def inside(key, other):
        return key.startswith(other.rstrip(os.sep) + os.sep)

    return [f for k, f in keys.items() if not any(inside(k, other) for other in keys if other != k)]
