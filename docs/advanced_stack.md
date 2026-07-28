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

## Data Flow

```text
yt-dlp -> platform subtitles or media -> faster-whisper
       -> transcript -> spaCy + local/LLM analysis
       -> video -> PySceneDetect + OpenCV
       -> lexical chunks -> Sentence Transformers -> ChromaDB
       -> LangGraph -> lexical KB -> vector KB -> Creator KB -> project report
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
```

The dependency list installs the official `zh_core_web_sm` 3.8.0 model from the spaCy GitHub releases. If the model is unavailable, the integration falls back to `spacy.blank("zh")` with Chinese punctuation-aware sentence splitting; sentence statistics remain available, but named entities and trained linguistic annotations do not.
