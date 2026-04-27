from __future__ import annotations

from itertools import islice, product
from typing import Any, Mapping, Sequence


def bounded_cartesian_product(axes: Mapping[str, Sequence[Any]], limit: int) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    keys = tuple(axes)
    value_sets = tuple(tuple(axes[key]) for key in keys)
    return [dict(zip(keys, values)) for values in islice(product(*value_sets), limit)]
