from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_language(name: str, default: str | None) -> str | None:
    value = os.getenv(name)
    selected = default if value is None else value.strip()
    if selected is None or str(selected).strip().lower() in {"", "auto", "none", "null"}:
        return None
    return str(selected).strip()


def _detect_ffmpeg_path() -> str:
    configured = os.getenv("FFMPEG_PATH")
    if configured:
        return configured

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    output_dir: Path = _env_path("OUTPUT_DIR", BASE_DIR / "output")
    cache_dir: Path = _env_path("CACHE_DIR", BASE_DIR / "cache")
    logs_dir: Path = _env_path("LOGS_DIR", BASE_DIR / "logs")

    whisper_model: str = os.getenv("WHISPER_MODEL", "small")
    whisper_engine: str = os.getenv("WHISPER_ENGINE", "faster-whisper")
    whisper_language: str | None = _env_language("WHISPER_LANGUAGE", "zh")
    youtube_whisper_language: str | None = _env_language(
        "YOUTUBE_WHISPER_LANGUAGE",
        None,
    )
    douyin_whisper_language: str | None = _env_language(
        "DOUYIN_WHISPER_LANGUAGE",
        "zh",
    )
    whisper_device: str = os.getenv("WHISPER_DEVICE", "auto")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
    whisper_batch_size: int = int(os.getenv("WHISPER_BATCH_SIZE", "8"))
    whisper_beam_size: int = int(os.getenv("WHISPER_BEAM_SIZE", "3"))
    whisper_vad_min_silence_ms: int = int(os.getenv("WHISPER_VAD_MIN_SILENCE_MS", "700"))
    whisper_min_free_vram_mb: int = int(os.getenv("WHISPER_MIN_FREE_VRAM_MB", "4096"))
    whisper_gpu_max_utilization: int = int(os.getenv("WHISPER_GPU_MAX_UTILIZATION", "60"))
    whisper_cpu_threads: int = int(os.getenv("WHISPER_CPU_THREADS", "0"))
    whisper_num_workers: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    whisper_gpu_fallback: bool = _env_bool("WHISPER_GPU_FALLBACK", True)
    whisper_release_after_job: bool = _env_bool("WHISPER_RELEASE_AFTER_JOB", True)
    whisper_cuda_path: str | None = os.getenv("WHISPER_CUDA_PATH")

    llm_api_key: str | None = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_base_url: str | None = os.getenv("LLM_BASE_URL")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "120"))
    llm_max_chars: int = int(os.getenv("LLM_MAX_CHARS", "60000"))

    ffmpeg_path: str = _detect_ffmpeg_path()
    bilibili_cookie_file: str | None = os.getenv("BILIBILI_COOKIE_FILE")
    bilibili_cookies_from_browser: str | None = os.getenv("BILIBILI_COOKIES_FROM_BROWSER")
    youtube_cookie_file: str | None = os.getenv("YOUTUBE_COOKIE_FILE")
    youtube_cookies_from_browser: str | None = os.getenv("YOUTUBE_COOKIES_FROM_BROWSER")
    douyin_cookie_file: str | None = os.getenv("DOUYIN_COOKIE_FILE")
    douyin_cookies_from_browser: str | None = os.getenv("DOUYIN_COOKIES_FROM_BROWSER")
    douyin_adapter_root: str | None = os.getenv("DOUYIN_ADAPTER_ROOT")
    douyin_adapter_enabled: bool = _env_bool("DOUYIN_ADAPTER_ENABLED", True)
    douyin_adapter_timeout: int = int(os.getenv("DOUYIN_ADAPTER_TIMEOUT", "900"))
    douyin_auth_timeout: int = int(os.getenv("DOUYIN_AUTH_TIMEOUT", "600"))
    xiaohongshu_cookie_file: str | None = os.getenv("XIAOHONGSHU_COOKIE_FILE")
    xiaohongshu_cookies_from_browser: str | None = os.getenv("XIAOHONGSHU_COOKIES_FROM_BROWSER")
    yt_dlp_cookie_file: str | None = os.getenv("YTDLP_COOKIE_FILE")
    yt_dlp_cookies_from_browser: str | None = os.getenv("YTDLP_COOKIES_FROM_BROWSER")
    yt_dlp_proxy: str | None = os.getenv("YTDLP_PROXY")
    batch_limit: int = int(os.getenv("BATCH_LIMIT", "20"))
    comment_limit: int = int(os.getenv("COMMENT_LIMIT", "100"))
    rag_chunk_chars: int = int(os.getenv("RAG_CHUNK_CHARS", "900"))
    rag_search_backend: str = os.getenv("RAG_SEARCH_BACKEND", "hybrid")
    sentence_transformer_model: str = os.getenv(
        "SENTENCE_TRANSFORMER_MODEL",
        "BAAI/bge-small-zh-v1.5",
    )
    sentence_transformer_batch_size: int = int(os.getenv("SENTENCE_TRANSFORMER_BATCH_SIZE", "32"))
    sentence_transformer_local_only: bool = _env_bool("SENTENCE_TRANSFORMER_LOCAL_ONLY", True)
    spacy_model: str = os.getenv("SPACY_MODEL", "zh_core_web_sm")
    nlp_max_chars: int = int(os.getenv("NLP_MAX_CHARS", "120000"))
    scene_detection_enabled: bool = _env_bool("SCENE_DETECTION_ENABLED", True)
    scene_threshold: float = float(os.getenv("SCENE_THRESHOLD", "27.0"))
    scene_min_seconds: float = float(os.getenv("SCENE_MIN_SECONDS", "0.6"))

    overwrite_cache: bool = _env_bool("CONTENT_RESEARCH_OVERWRITE", False)

    @property
    def video_cache_dir(self) -> Path:
        return self.cache_dir / "videos"

    @property
    def transcript_cache_dir(self) -> Path:
        return self.cache_dir / "transcripts"

    @property
    def analysis_cache_dir(self) -> Path:
        return self.cache_dir / "analysis"

    @property
    def up_cache_dir(self) -> Path:
        return self.cache_dir / "up"

    @property
    def comments_cache_dir(self) -> Path:
        return self.cache_dir / "comments"

    @property
    def covers_cache_dir(self) -> Path:
        return self.cache_dir / "covers"

    @property
    def knowledge_base_dir(self) -> Path:
        return self.cache_dir / "knowledge_base"

    @property
    def douyin_cache_dir(self) -> Path:
        return self.cache_dir / "douyin"

    @property
    def platform_auth_dir(self) -> Path:
        return self.cache_dir / "platform_auth"

    @property
    def douyin_adapter_dir(self) -> Path:
        if self.douyin_adapter_root:
            value = Path(self.douyin_adapter_root).expanduser()
            return value if value.is_absolute() else self.base_dir / value
        return self.base_dir / "integrations" / "douyin-downloader"

    @property
    def vector_knowledge_base_dir(self) -> Path:
        return self.knowledge_base_dir / "chroma"

    @property
    def model_cache_dir(self) -> Path:
        return self.cache_dir / "models"


SETTINGS = Settings()


def ensure_directories(settings: Settings = SETTINGS) -> None:
    for path in (
        settings.output_dir,
        settings.cache_dir,
        settings.logs_dir,
        settings.video_cache_dir,
        settings.transcript_cache_dir,
        settings.analysis_cache_dir,
        settings.up_cache_dir,
        settings.comments_cache_dir,
        settings.covers_cache_dir,
        settings.knowledge_base_dir,
        settings.vector_knowledge_base_dir,
        settings.model_cache_dir,
        settings.douyin_cache_dir,
        settings.platform_auth_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def setup_logging(settings: Settings = SETTINGS) -> None:
    ensure_directories(settings)
    log_path = settings.logs_dir / "pipeline.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
