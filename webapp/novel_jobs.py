"""Compatibility import for the novel feature moved out of the Web layer."""

from features.novel.jobs import run_novel_job

__all__ = ["run_novel_job"]
