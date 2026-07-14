from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class ASRTranscriber(ABC):
    @abstractmethod
    def add_listener(self, cb: Callable[[str], None]) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
