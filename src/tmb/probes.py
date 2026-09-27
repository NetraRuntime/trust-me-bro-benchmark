"""Small public starter suite; selection is fixed, not calibrated on evaluation data."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import Field

from .config import Strict

SUITE_VERSION = "starter-1"


class Probe(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    level: int = Field(ge=0, le=3)
    prompt: str = Field(min_length=1, max_length=10000)
    role: str = Field(default="user", pattern=r"^(user|system)$")


PUBLIC = [
    Probe(id="sanity", level=0, prompt="Reply with exactly OK."),
    Probe(id="digit-en", level=1, prompt="Choose one digit from 0 to 9. Reply with only that digit."),
    Probe(id="digit-zh", level=1, prompt="从0到9中选一个数字。只回答这个数字。"),
    Probe(id="digit-es", level=1, prompt="Elige un dígito del 0 al 9. Responde solo con ese dígito."),
    Probe(id="digit-ru", level=1, prompt="Выбери одну цифру от 0 до 9. Ответь только этой цифрой."),
]
TASKS = [
    ("format", "Return exactly this string, preserving punctuation: [a::B|03]"),
    ("json", 'Output only JSON with keys "b" then "a", values 2 and 1, without spaces.'),
    ("logic", "All dax are wug. No wug is pem. Can a dax be pem? Reply YES or NO."),
    ("unicode", "Return only the number of Unicode code points in: Aé中"),
    ("multilingual", "Translate 'blue' into Indonesian. Reply with only the translated word."),
    ("revision", "In Python 3.12, is 'type Alias = int' valid syntax? Reply YES or NO."),
]
PUBLIC += [
    Probe(id=f"l{level}-{name}", level=level, prompt=prompt) for level in (2, 3) for name, prompt in TASKS
]


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_probes(config, config_path):
    if config.probes_file:
        path = Path(config_path).parent / config.probes_file
        probes = [Probe.model_validate(p) for p in yaml.safe_load(path.read_text(encoding="utf-8"))]
    else:
        probes = PUBLIC
    if len({p.id for p in probes}) != len(probes):
        raise ValueError("Probe IDs must be unique")
    if {p.level for p in probes} != {0, 1, 2, 3}:
        raise ValueError("Probe suite must include levels 0,1,2,3")
    return probes, digest([p.model_dump() for p in probes])
