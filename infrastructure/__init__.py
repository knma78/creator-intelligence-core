"""Shared infrastructure helpers with no business-domain dependencies."""

from .atomic_io import atomic_write_json, atomic_write_text

__all__ = ["atomic_write_json", "atomic_write_text"]
