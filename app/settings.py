"""Explicit application storage settings; model configuration remains deployment-wide."""
from dataclasses import dataclass
from pathlib import Path

from core.config import DATA


@dataclass(frozen=True)
class Settings:
    data_root: Path = DATA

    def __post_init__(self):
        object.__setattr__(self, 'data_root', Path(self.data_root).resolve())
