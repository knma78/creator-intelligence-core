# Advanced Research Stack

This project uses official releases from the following upstream repositories:

| Library | Official repository | Project role |
| --- | --- | --- |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | Local ASR with CTranslate2 and VAD |
| yt-dlp | https://github.com/yt-dlp/yt-dlp | Bilibili metadata, subtitles, and media acquisition |
| spaCy | https://github.com/explosion/spaCy | Sentence boundaries, entities, and NLP statistics |
| Sentence Transformers | https://github.com/huggingface/sentence-transformers | Chinese semantic embeddings |
| ChromaDB | https://github.com/chroma-core/chroma | Persistent vector index |
| LangGraph | https://github.com/langchain-ai/langgraph | Stateful knowledge-build orchestration |
| PySceneDetect | https://github.com/Breakthrough/PySceneDetect | Content-aware scene cut detection |
| OpenCV | https://github.com/opencv/opencv | Video decoding and frame metadata |
| DuckDB | https://github.com/duckdb/duckdb | Local cross-video analytical warehouse |
| OpenCLIP | https://github.com/mlfoundations/open_clip | Cover and key-image semantic embeddings |
| librosa | https://github.com/librosa/librosa | Audio rhythm and acoustic features |

## Data Flow

```text
yt-dlp -> platform subtitles or media -> faster-whisper
       -> transcript -> spaCy + local/LLM analysis
       -> video -> PySceneDetect + OpenCV
       -> lexical chunks -> Sentence Transformers -> ChromaDB
       -> LangGraph -> lexical KB -> vector KB -> Creator KB -> project report
       -> DuckDB -> cross-video SQL analytics
       -> cover -> OpenCLIP labels + embedding
       -> audio -> librosa rhythm features
```

All advanced modules are fail-soft. Missing models, unavailable video files, or an absent vector index do not disable the existing local analysis and TF-IDF search.

## Configuration

```env
RAG_SEARCH_BACKEND=hybrid
SENTENCE_TRANSFORMER_MODEL=BAAI/bge-small-zh-v1.5
SENTENCE_TRANSFORMER_BATCH_SIZE=32
SPACY_MODEL=zh_core_web_sm
NLP_MAX_CHARS=120000
SCENE_DETECTION_ENABLED=true
SCENE_THRESHOLD=27.0
SCENE_MIN_SECONDS=0.6
ANALYTICS_STORE_ENABLED=true
OPENCLIP_ENABLED=true
OPENCLIP_MODEL=ViT-B-32
OPENCLIP_PRETRAINED=laion2b_s34b_b79k
AUDIO_RHYTHM_ENABLED=true
AUDIO_RHYTHM_BACKEND=auto
AUDIO_RHYTHM_MAX_SECONDS=1800
```

The dependency list installs the official `zh_core_web_sm` 3.8.0 model from the spaCy GitHub releases. If the model is unavailable, the integration falls back to `spacy.blank("zh")` with Chinese punctuation-aware sentence splitting; sentence statistics remain available, but named entities and trained linguistic annotations do not.

Existing `output/*/analysis.json` results are incrementally synchronized into
DuckDB before a lexical knowledge-base build. The synchronization ledger uses
content fingerprints and ignores derived creator-knowledge copies.

Vector manifests are bound to the SHA-256 of the lexical index. If the lexical
index or embedding model changes, vector search is marked stale and excluded
from hybrid ranking until the advanced knowledge build regenerates it.
