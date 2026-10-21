from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
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


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


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


def _detect_video_ffmpeg_path() -> str:
    configured = os.getenv("VIDEO_FFMPEG_PATH")
    if configured:
        return configured
    return _detect_ffmpeg_path()


def _detect_ffprobe_path() -> str:
    configured = os.getenv("FFPROBE_PATH")
    if configured:
        return configured
    video_ffmpeg = Path(_detect_video_ffmpeg_path())
    sibling = video_ffmpeg.with_name(
        "ffprobe.exe" if os.name == "nt" else "ffprobe"
    )
    if sibling.is_file():
        return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


def _detect_optional_tool(
    env_name: str,
    executable: str,
    candidates: tuple[Path, ...],
) -> str | None:
    configured = os.getenv(env_name)
    if configured:
        return configured
    system_path = shutil.which(executable)
    if system_path:
        return system_path
    return next(
        (str(path) for path in candidates if path.is_file()),
        None,
    )


def _detect_video_factory_root() -> Path:
    configured = os.getenv("VIDEO_FACTORY_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return BASE_DIR / "integrations" / "video-factory"


@dataclass(frozen=True)
class Settings:
    base_dir: Path = field(default_factory=lambda: BASE_DIR)
    output_dir: Path = field(default_factory=lambda: _env_path("OUTPUT_DIR", BASE_DIR / "output"))
    cache_dir: Path = field(default_factory=lambda: _env_path("CACHE_DIR", BASE_DIR / "cache"))
    logs_dir: Path = field(default_factory=lambda: _env_path("LOGS_DIR", BASE_DIR / "logs"))

    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    whisper_engine: str = field(default_factory=lambda: os.getenv("WHISPER_ENGINE", "faster-whisper"))
    whisper_language: str | None = field(default_factory=lambda: _env_language("WHISPER_LANGUAGE", "zh"))
    youtube_whisper_language: str | None = field(default_factory=lambda: _env_language("YOUTUBE_WHISPER_LANGUAGE", None))
    douyin_whisper_language: str | None = field(default_factory=lambda: _env_language("DOUYIN_WHISPER_LANGUAGE", "zh"))
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "auto"))
    whisper_compute_type: str = field(default_factory=lambda: os.getenv("WHISPER_COMPUTE_TYPE", "auto"))
    whisper_batch_size: int = field(default_factory=lambda: int(os.getenv("WHISPER_BATCH_SIZE", "8")))
    whisper_beam_size: int = field(default_factory=lambda: int(os.getenv("WHISPER_BEAM_SIZE", "3")))
    whisper_vad_min_silence_ms: int = field(default_factory=lambda: int(os.getenv("WHISPER_VAD_MIN_SILENCE_MS", "700")))
    whisper_min_free_vram_mb: int = field(default_factory=lambda: int(os.getenv("WHISPER_MIN_FREE_VRAM_MB", "4096")))
    whisper_gpu_max_utilization: int = field(default_factory=lambda: int(os.getenv("WHISPER_GPU_MAX_UTILIZATION", "60")))
    whisper_cpu_threads: int = field(default_factory=lambda: int(os.getenv("WHISPER_CPU_THREADS", "0")))
    whisper_num_workers: int = field(default_factory=lambda: int(os.getenv("WHISPER_NUM_WORKERS", "1")))
    whisper_gpu_fallback: bool = field(default_factory=lambda: _env_bool("WHISPER_GPU_FALLBACK", True))
    whisper_release_after_job: bool = field(default_factory=lambda: _env_bool("WHISPER_RELEASE_AFTER_JOB", True))
    whisper_cuda_path: str | None = field(default_factory=lambda: os.getenv("WHISPER_CUDA_PATH"))

    llm_api_key: str | None = field(default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    llm_base_url: str | None = field(default_factory=lambda: os.getenv("LLM_BASE_URL"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4.1-mini"))
    llm_timeout: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT", "120")))
    llm_max_chars: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_CHARS", "60000")))
    novel_writing_skill_path: Path = field(
        default_factory=lambda: _env_path(
            "NOVEL_WRITING_SKILL_PATH",
            Path.home() / ".codex" / "skills" / "novel-writing",
        )
    )
    native_english_review_skill_path: Path = field(
        default_factory=lambda: _env_path(
            "NATIVE_ENGLISH_REVIEW_SKILL_PATH",
            Path.home() / ".codex" / "skills" / "native-english-fiction-review",
        )
    )
    novel_review_model: str = field(
        default_factory=lambda: os.getenv("NOVEL_REVIEW_MODEL")
        or os.getenv("LLM_MODEL", "gpt-4.1-mini")
    )
    english_review_harper_cli_path: str | None = field(
        default_factory=lambda: os.getenv("ENGLISH_REVIEW_HARPER_CLI_PATH")
    )

    ffmpeg_path: str = field(default_factory=_detect_ffmpeg_path)
    video_ffmpeg_path: str = field(default_factory=_detect_video_ffmpeg_path)
    ffprobe_path: str = field(default_factory=_detect_ffprobe_path)
    video_factory_root: Path = field(default_factory=_detect_video_factory_root)
    edge_tts_path: str | None = field(
        default_factory=lambda: _detect_optional_tool(
            "EDGE_TTS_PATH",
            "edge-tts",
            (),
        )
    )
    blender_path: str | None = field(
        default_factory=lambda: _detect_optional_tool(
            "BLENDER_PATH",
            "blender",
            (),
        )
    )
    aerender_path: str | None = field(
        default_factory=lambda: _detect_optional_tool(
            "AERENDER_PATH",
            "aerender",
            (),
        )
    )
    bilibili_cookie_file: str | None = field(default_factory=lambda: os.getenv("BILIBILI_COOKIE_FILE"))
    bilibili_cookies_from_browser: str | None = field(default_factory=lambda: os.getenv("BILIBILI_COOKIES_FROM_BROWSER"))
    bilibili_download_attempts: int = field(default_factory=lambda: int(os.getenv("BILIBILI_DOWNLOAD_ATTEMPTS", "2")))
    bilibili_download_retries: int = field(default_factory=lambda: int(os.getenv("BILIBILI_DOWNLOAD_RETRIES", "8")))
    bilibili_fragment_retries: int = field(default_factory=lambda: int(os.getenv("BILIBILI_FRAGMENT_RETRIES", "12")))
    bilibili_socket_timeout: int = field(default_factory=lambda: int(os.getenv("BILIBILI_SOCKET_TIMEOUT", "30")))
    bilibili_http_chunk_size: int = field(default_factory=lambda: int(os.getenv("BILIBILI_HTTP_CHUNK_SIZE", "10485760")))
    youtube_cookie_file: str | None = field(default_factory=lambda: os.getenv("YOUTUBE_COOKIE_FILE"))
    youtube_cookies_from_browser: str | None = field(default_factory=lambda: os.getenv("YOUTUBE_COOKIES_FROM_BROWSER"))
    douyin_cookie_file: str | None = field(default_factory=lambda: os.getenv("DOUYIN_COOKIE_FILE"))
    douyin_cookies_from_browser: str | None = field(default_factory=lambda: os.getenv("DOUYIN_COOKIES_FROM_BROWSER"))
    douyin_adapter_root: str | None = field(default_factory=lambda: os.getenv("DOUYIN_ADAPTER_ROOT"))
    douyin_adapter_enabled: bool = field(default_factory=lambda: _env_bool("DOUYIN_ADAPTER_ENABLED", True))
    douyin_adapter_timeout: int = field(default_factory=lambda: int(os.getenv("DOUYIN_ADAPTER_TIMEOUT", "900")))
    douyin_auth_timeout: int = field(default_factory=lambda: int(os.getenv("DOUYIN_AUTH_TIMEOUT", "600")))
    platform_auth_timeout: int = field(default_factory=lambda: int(os.getenv("PLATFORM_AUTH_TIMEOUT", "600")))
    xiaohongshu_cookie_file: str | None = field(default_factory=lambda: os.getenv("XIAOHONGSHU_COOKIE_FILE"))
    xiaohongshu_cookies_from_browser: str | None = field(default_factory=lambda: os.getenv("XIAOHONGSHU_COOKIES_FROM_BROWSER"))
    yt_dlp_cookie_file: str | None = field(default_factory=lambda: os.getenv("YTDLP_COOKIE_FILE"))
    yt_dlp_cookies_from_browser: str | None = field(default_factory=lambda: os.getenv("YTDLP_COOKIES_FROM_BROWSER"))
    yt_dlp_proxy: str | None = field(default_factory=lambda: os.getenv("YTDLP_PROXY"))
    batch_limit: int = field(default_factory=lambda: int(os.getenv("BATCH_LIMIT", "20")))
    comment_limit: int = field(default_factory=lambda: int(os.getenv("COMMENT_LIMIT", "100")))
    rag_chunk_chars: int = field(default_factory=lambda: int(os.getenv("RAG_CHUNK_CHARS", "900")))
    rag_search_backend: str = field(default_factory=lambda: os.getenv("RAG_SEARCH_BACKEND", "hybrid"))
    sentence_transformer_model: str = field(default_factory=lambda: os.getenv("SENTENCE_TRANSFORMER_MODEL", "BAAI/bge-small-zh-v1.5"))
    sentence_transformer_batch_size: int = field(default_factory=lambda: int(os.getenv("SENTENCE_TRANSFORMER_BATCH_SIZE", "32")))
    sentence_transformer_local_only: bool = field(default_factory=lambda: _env_bool("SENTENCE_TRANSFORMER_LOCAL_ONLY", True))
    spacy_model: str = field(default_factory=lambda: os.getenv("SPACY_MODEL", "zh_core_web_sm"))
    nlp_max_chars: int = field(default_factory=lambda: int(os.getenv("NLP_MAX_CHARS", "120000")))
    scene_detection_enabled: bool = field(default_factory=lambda: _env_bool("SCENE_DETECTION_ENABLED", True))
    scene_threshold: float = field(default_factory=lambda: float(os.getenv("SCENE_THRESHOLD", "27.0")))
    scene_min_seconds: float = field(default_factory=lambda: float(os.getenv("SCENE_MIN_SECONDS", "0.6")))
    scene_sample_seconds: float = field(default_factory=lambda: float(os.getenv("SCENE_SAMPLE_SECONDS", "2.0")))
    scene_max_samples: int = field(default_factory=lambda: int(os.getenv("SCENE_MAX_SAMPLES", "900")))
    scene_downscale_width: int = field(default_factory=lambda: int(os.getenv("SCENE_DOWNSCALE_WIDTH", "640")))
    analytics_store_enabled: bool = field(default_factory=lambda: _env_bool("ANALYTICS_STORE_ENABLED", True))
    openclip_enabled: bool = field(default_factory=lambda: _env_bool("OPENCLIP_ENABLED", True))
    openclip_allow_download: bool = field(default_factory=lambda: _env_bool("OPENCLIP_ALLOW_DOWNLOAD", False))
    openclip_model: str = field(default_factory=lambda: os.getenv("OPENCLIP_MODEL", "ViT-B-32"))
    openclip_pretrained: str = field(default_factory=lambda: os.getenv("OPENCLIP_PRETRAINED", "laion2b_s34b_b79k"))
    openclip_device: str = field(default_factory=lambda: os.getenv("OPENCLIP_DEVICE", "auto"))
    openclip_top_k: int = field(default_factory=lambda: int(os.getenv("OPENCLIP_TOP_K", "5")))
    openclip_store_embedding: bool = field(default_factory=lambda: _env_bool("OPENCLIP_STORE_EMBEDDING", True))
    openclip_labels: tuple[str, ...] = field(
        default_factory=lambda: _env_list(
            "OPENCLIP_LABELS",
            (
                "talking head",
                "anime illustration",
                "movie scene",
                "gameplay",
                "tutorial screen",
                "product close-up",
                "text-heavy poster",
                "emotional face",
                "action scene",
                "landscape",
                "infographic",
                "meme",
            ),
        )
    )
    audio_rhythm_enabled: bool = field(default_factory=lambda: _env_bool("AUDIO_RHYTHM_ENABLED", True))
    audio_rhythm_backend: str = field(default_factory=lambda: os.getenv("AUDIO_RHYTHM_BACKEND", "auto"))
    audio_rhythm_sample_rate: int = field(default_factory=lambda: int(os.getenv("AUDIO_RHYTHM_SAMPLE_RATE", "16000")))
    audio_rhythm_max_seconds: int = field(default_factory=lambda: int(os.getenv("AUDIO_RHYTHM_MAX_SECONDS", "1800")))
    job_worker_count: int = field(default_factory=lambda: int(os.getenv("JOB_WORKER_COUNT", "1")))
    job_queue_capacity: int = field(default_factory=lambda: int(os.getenv("JOB_QUEUE_CAPACITY", "100")))
    job_history_limit: int = field(default_factory=lambda: int(os.getenv("JOB_HISTORY_LIMIT", "20")))
    job_log_limit: int = field(default_factory=lambda: int(os.getenv("JOB_LOG_LIMIT", "500")))
    resource_network_slots: int = field(default_factory=lambda: int(os.getenv("RESOURCE_NETWORK_SLOTS", "3")))
    resource_cpu_heavy_slots: int = field(default_factory=lambda: int(os.getenv("RESOURCE_CPU_HEAVY_SLOTS", "2")))
    resource_gpu_slots: int = field(default_factory=lambda: int(os.getenv("RESOURCE_GPU_SLOTS", "1")))
    resource_realtime_audio_slots: int = field(default_factory=lambda: int(os.getenv("RESOURCE_REALTIME_AUDIO_SLOTS", "1")))
    resource_acquire_timeout: float = field(default_factory=lambda: float(os.getenv("RESOURCE_ACQUIRE_TIMEOUT", "3600")))
    playback_capture_enabled: bool = field(default_factory=lambda: _env_bool("PLAYBACK_CAPTURE_ENABLED", True))
    playback_capture_default_seconds: int = field(default_factory=lambda: int(os.getenv("PLAYBACK_CAPTURE_DEFAULT_SECONDS", "300")))
    playback_capture_max_seconds: int = field(default_factory=lambda: int(os.getenv("PLAYBACK_CAPTURE_MAX_SECONDS", "14400")))
    playback_capture_warmup_seconds: int = field(default_factory=lambda: int(os.getenv("PLAYBACK_CAPTURE_WARMUP_SECONDS", "8")))
    playback_capture_open_browser: bool = field(default_factory=lambda: _env_bool("PLAYBACK_CAPTURE_OPEN_BROWSER", True))
    playback_capture_silence_threshold: float = field(default_factory=lambda: float(os.getenv("PLAYBACK_CAPTURE_SILENCE_THRESHOLD", "0.001")))

    overwrite_cache: bool = field(default_factory=lambda: _env_bool("CONTENT_RESEARCH_OVERWRITE", False))

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
    def acquisition_cache_dir(self) -> Path:
        return self.cache_dir / "acquisitions"

    @property
    def playback_capture_dir(self) -> Path:
        return self.cache_dir / "playback_capture"

    @property
    def video_production_dir(self) -> Path:
        configured = os.getenv("VIDEO_PRODUCTION_DIR")
        if configured:
            value = Path(configured).expanduser()
            return (
                value.resolve()
                if value.is_absolute()
                else (self.base_dir / value).resolve()
            )
        return self.output_dir / "video_production"

    @property
    def novel_writing_output_dir(self) -> Path:
        return self.output_dir / "novel_writing"

    @property
    def english_review_harper_cli(self) -> Path:
        if self.english_review_harper_cli_path:
            value = Path(self.english_review_harper_cli_path).expanduser()
            return value if value.is_absolute() else (self.base_dir / value).resolve()
        return self.base_dir / "integrations" / "english_review" / "bin" / "harper-cli.exe"

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

    @property
    def analytics_database_path(self) -> Path:
        configured = os.getenv("ANALYTICS_DB_PATH")
        if configured:
            value = Path(configured).expanduser()
            return value.resolve() if value.is_absolute() else (self.base_dir / value).resolve()
        return self.cache_dir / "analytics" / "content_research.duckdb"

    @property
    def job_database_path(self) -> Path:
        configured = os.getenv("JOB_DB_PATH")
        if configured:
            value = Path(configured).expanduser()
            return value.resolve() if value.is_absolute() else (self.base_dir / value).resolve()
        return self.cache_dir / "jobs" / "jobs.sqlite3"

    @property
    def creator_progress_database_path(self) -> Path:
        configured = os.getenv("CREATOR_PROGRESS_DB_PATH")
        if configured:
            value = Path(configured).expanduser()
            return value.resolve() if value.is_absolute() else (self.base_dir / value).resolve()
        # Deliberately outside cache/ and output/: clearing media or analysis
        # artifacts must not reset the creator-learning cursor.
        return self.base_dir / "state" / "creator_progress.sqlite3"


def load_settings(*, reload_env: bool = False) -> Settings:
    if reload_env and load_dotenv:
        load_dotenv(BASE_DIR / ".env", override=True)
    return Settings()


SETTINGS = load_settings()


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
        settings.analytics_database_path.parent,
        settings.job_database_path.parent,
        settings.douyin_cache_dir,
        settings.platform_auth_dir,
        settings.acquisition_cache_dir,
        settings.playback_capture_dir,
        settings.video_production_dir,
        settings.novel_writing_output_dir,
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
