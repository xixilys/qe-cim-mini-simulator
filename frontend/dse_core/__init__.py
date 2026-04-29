"""Domain-neutral DSE frontend core.

This package is the stable pro-manual frontend surface.  The historical
``docs.benchmarks.unified_dse`` modules remain as compatibility wrappers and
share the same implementation contracts.
"""

from docs.benchmarks.unified_dse import domain_contracts

__all__ = ["domain_contracts"]

from . import interfaces

__all__.append("interfaces")
