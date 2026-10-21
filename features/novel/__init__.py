"""Novel-writing domain integration."""

from features.novel.jobs import build_novel_job_handler, run_novel_job

__all__ = ["build_novel_job_handler", "run_novel_job"]
