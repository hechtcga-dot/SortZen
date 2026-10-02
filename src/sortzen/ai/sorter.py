"""Asking an AI service about files SortZen couldn't place by itself.

Two passes, in batches: first the AI sees names and folders only; files it is still unsure
about are asked again with the beginning of the file (and a small picture preview, when
allowed). Every batch carries the numbered folder list, a few example names per folder and
the house rules. Spending is counted from each reply's token usage and stops at the cap.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..config import AI_BATCH_SIZE, TRANSIENT_BACKOFFS
from ..repositories.ai_answers import AIAnswer
from ..tasks import Progress, Status
from .costs import cost, tokens
from .errors import explain
from .parsing import extract_json
from .services import SERVICES
from .privacy import image_preview
from .provider import ImagePayload, is_transient_api_error

SECOND_PASS_BELOW = 70              # files the AI is less sure about than this are asked again with content
REPLY_TOKENS_PER_FILE = 30


@dataclass
class AIFolder:
    path: str
    shown: str                      # as users see it, e.g. "Sorted/Documents/Work"
    examples: list[str] = field(default_factory=list)


@dataclass
class AIFile:
    key: str                        # remembered-answer key
    path: str
    name: str                       # as sent (long numbers removed)
    folder: str                     # where it is now, as users see it
    text: str = ""                  # the beginning of the file, scrubbed; "" when only the name may be sent
    wants_preview: bool = False     # a picture, and previews are allowed
    preview: bytes | None = None    # made when it is first sent

    @property
    def has_content(self) -> bool:
        return bool(self.text or self.wants_preview)

    def picture(self) -> bytes | None:
        if self.wants_preview and self.preview is None:
            self.preview = image_preview(self.path) or b""
        return self.preview or None


@dataclass
class AIRun:
    asked: int = 0
    answered: int = 0
    second_pass: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    spent: float = 0.0
    stopped: str = ""               # why it stopped early, if it did
    failed: bool = False            # stopped by an error from the service (not the cap or Stop safely)


class AISorter:
    def __init__(self, provider, service: str, model: str, house_rules: str = "", batch_size: int = AI_BATCH_SIZE,
                 sleep=time.sleep):
        self.provider = provider
        self.service = service
        self.model = model
        self.house_rules = house_rules.strip()
        self.batch_size = batch_size
        self.sleep = sleep

    # ---------------------------------------------------------------- the request
    def _header(self, folders: list[AIFolder]) -> str:
        lines = ["You help one person sort their files into their own folders. For each file, choose the best "
                 "folder from the numbered list, or null when none fits. Prefer null over a guess."]
        if self.house_rules:
            lines += ["", "House rules (always follow these):", self.house_rules]
        lines += ["", "Folders:"]
        for number, f in enumerate(folders, start=1):
            examples = "; ".join(f.examples)
            lines.append(f"{number}: {f.shown}" + (f" (e.g. {examples})" if examples else ""))
        return "\n".join(lines)

    def request(self, folders: list[AIFolder], batch: list[AIFile], with_content: bool, pictures: bool = True) -> list:
        parts = [self._header(folders), "\nFiles:"]
        for number, f in enumerate(batch, start=1):
            line = f"f{number}: “{f.name}” now in {f.folder}"
            if with_content and f.text:
                line += f"\n   Beginning of the file: {f.text}"
            parts.append(line)
            if with_content and pictures and f.wants_preview and (picture := f.picture()):
                parts.append(ImagePayload(picture))
        parts.append('\nReply with JSON only: {"files": [{"id": "f1", "folder": 3, "sure": 85, '
                     '"why": "a few words"}]}. "folder" is a number from the list or null; "sure" is 0 to 100.')
        return parts

    def estimate(self, folders: list[AIFolder], files: list[AIFile]) -> float:
        """Dollars for both passes, assuming every file with content is asked a second time."""
        total = 0.0
        for with_content, group in ((False, files), (True, [f for f in files if f.has_content])):
            for start in range(0, len(group), self.batch_size):
                total += self._batch_cost(folders, group[start:start + self.batch_size], with_content)
        return total

    def _batch_cost(self, folders, batch, with_content) -> float:
        text = "\n".join(self.request(folders, batch, with_content, pictures=False))
        images = sum(1 for f in batch if with_content and f.wants_preview)
        return cost(self.service, tokens(text) + 300 * images, REPLY_TOKENS_PER_FILE * len(batch))

    # ---------------------------------------------------------------- asking
    def run(self, folders: list[AIFolder], files: list[AIFile], cap: float, emit=None, token=None,
            on_answers=None) -> tuple[dict[str, AIAnswer], AIRun]:
        emit = emit or (lambda event: None)
        run = AIRun()
        answers: dict[str, AIAnswer] = {}

        def finish():
            run.answered = sum(1 for a in answers.values() if a.destination)
            return answers, run

        second = [f for f in files if f.has_content]
        total = len(files) + len(second)            # progress: pass two counted at most
        done = 0
        for with_content in (False, True):
            todo = files if not with_content else [f for f in second
                                                   if f.key not in answers or answers[f.key].sure < SECOND_PASS_BELOW]
            if with_content:
                total = len(files) + len(todo)
            for start in range(0, len(todo), self.batch_size):
                if token is not None and token.cancelled:
                    run.stopped = "Stopped safely"
                    return finish()
                batch = todo[start:start + self.batch_size]
                if run.spent + self._batch_cost(folders, batch, with_content) > cap:
                    run.stopped = f"The spending cap (${cap:.2f}) was reached"
                    return finish()
                emit(Status("Asking the AI service", f"{'with the beginning of each file' if with_content else 'names'}"
                                                     f": {done + 1:,}–{done + len(batch):,} of {total:,}"))
                try:
                    reply = self._ask(self.request(folders, batch, with_content), token)
                except Exception as exc:
                    run.stopped = explain(exc, SERVICES[self.service].name if self.service in SERVICES
                                          else self.service, self.model)
                    run.failed = True
                    return finish()
                run.input_tokens += reply.usage.input_tokens
                run.output_tokens += reply.usage.output_tokens
                run.spent += cost(self.service, reply.usage.input_tokens, reply.usage.output_tokens)
                found = self._parse(reply.text, folders, batch, with_content)
                answers.update(found)
                if on_answers:
                    on_answers(found)
                run.asked += 0 if with_content else len(batch)
                run.second_pass += len(batch) if with_content else 0
                done += len(batch)
                emit(Progress(done, total))
        return finish()

    def _ask(self, contents, token):
        for attempt, wait in enumerate((*TRANSIENT_BACKOFFS, None)):
            try:
                return self.provider.generate_json(self.model, contents)
            except Exception as exc:
                if wait is None or not is_transient_api_error(exc):
                    raise
                for _ in range(int(wait * 10)):
                    if token is not None and token.cancelled:
                        raise RuntimeError("Stopped safely") from exc
                    self.sleep(0.1)
        raise RuntimeError("unreachable")

    def _parse(self, text: str, folders, batch, with_content) -> dict[str, AIAnswer]:
        try:
            data = extract_json(text)
        except ValueError:
            return {}
        items = data.get("files") if isinstance(data, dict) else data
        found = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                f = batch[int(str(item.get("id", "")).lstrip("fF")) - 1]
            except (ValueError, IndexError):
                continue
            folder = item.get("folder")
            try:
                number = int(folder) if folder is not None else None
            except (TypeError, ValueError):
                number = None
            destination = folders[number - 1].path if number is not None and 1 <= number <= len(folders) else None
            try:
                sure = max(0, min(100, int(item.get("sure", 50))))
            except (TypeError, ValueError):
                sure = 50
            found[f.key] = AIAnswer(destination, sure if destination else 0, str(item.get("why") or "")[:140],
                                    with_content, self.service)
        return found
