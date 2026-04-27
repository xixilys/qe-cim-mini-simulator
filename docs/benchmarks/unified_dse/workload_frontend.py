from __future__ import annotations

import json
from pathlib import Path

from .interfaces import WorkloadDescriptor


def load_workload_descriptor(path: Path | str) -> WorkloadDescriptor:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return WorkloadDescriptor.from_dict(payload)
