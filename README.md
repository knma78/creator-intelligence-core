# Creator Intelligence Core

> Content Research Pipeline and local Creator Intelligence System

本地运行的内容研究流水线。支持输入 B站、YouTube、抖音、小红书公开视频链接、本地视频文件、B站 UP 主页、YouTube 频道主页、抖音创作者主页，或自然语言研究问题，自动完成字幕获取、Whisper 转录、内容分析、批量画像、知识库检索和 V4 研究报告。

## V1.0 流程

```text
输入公开视频链接
  ↓
检查是否存在官方字幕
  ↓
有字幕：只下载字幕 → LLM/本地分析 → 导出
  ↓
无字幕：下载视频 → FFmpeg 提取音频 → Whisper 识别 → LLM/本地分析 → 导出
```

### 抖音 / 小红书

抖音已接入单视频和创作者主页批量流水线，小红书已接入单视频流水线：

```bash
python main.py "抖音公开视频分享链接" --v3 --build-kb
python main.py "https://www.douyin.com/user/<sec_uid>" --up --limit 10
python main.py "小红书视频笔记分享链接" --v3 --build-kb
```

处理结果会缓存到 `cache/videos/DY_<视频ID>` 或 `cache/videos/XHS_<笔记ID>`，重复分析不会重新下载或重复执行 Whisper。

平台限制：

- 支持公开的抖音单视频、抖音创作者主页和小红书视频笔记。
- 小红书纯图文笔记没有音视频流，不能进入 Whisper。
- 抖音首次使用时，在本地网页点击“登录抖音”并完成一次网页登录；Cookie 仅保存在 `cache/douyin/cookies.json`。
- 抖音下载由 `integrations/douyin-downloader` 隔离适配器完成，媒体获取后继续复用本项目的 Whisper、分析和知识库流程。
- 小红书创作者主页批量抓取暂未接入；Discovery 候选人需要保存一个公开视频链接。
- 小红书登录可见内容可配置 `XIAOHONGSHU_COOKIES_FROM_BROWSER` 或 `XIAOHONGSHU_COOKIE_FILE`。
- 使用浏览器 Cookie 前应先关闭对应浏览器，避免 Cookie 数据库被占用。

## V2.0

支持 B站 UP 主页、YouTube 频道主页和抖音创作者主页批量分析：

```bash
python main.py "https://space.bilibili.com/123456/video" --up --limit 20
```

也可以直接输入 UP 的 mid：

```bash
python main.py 123456 --up --limit 20
```

YouTube 频道可以直接使用 `@频道名` 主页：

```bash
python main.py "https://www.youtube.com/@veritasium" --up --limit 10
```

输出：

```text
output/up_<mid>/
  batch_manifest.json
  up_profile.json
  up_profile.md
```

YouTube 频道输出到 `output/channel_youtube_<频道缓存键>/`，每条视频仍使用统一的 `output/YT_<视频ID>/` 目录。

抖音创作者输出到 `output/creator_douyin_<主页缓存键>/`，每条视频使用统一的 `output/DY_<视频ID>/` 目录。

单个视频仍会分别输出到：

```text
output/<视频ID>/
```

## V3.0

开启评论、封面、OCR、标题统计增强分析：

```bash
python main.py "https://www.bilibili.com/video/BVxxxx" --v3
```

批量 UP 分析时开启 V3：

```bash
python main.py "https://space.bilibili.com/123456/video" --up --limit 20 --v3
```

每个视频额外输出：

```text
output/<视频ID>/
  v3.json
  v3.md
  cover.jpg / cover.png
```

V3 包含：

- 评论区抓取与关键词/情绪分析
- 封面下载与基础视觉分析
- 封面 OCR，优先使用 `rapidocr_onnxruntime`，其次尝试 `pytesseract`
- 标题统计
- 本地 RAG 知识库构建与检索

构建知识库：

```bash
python main.py --build-kb
```

分析后顺便构建知识库：

```bash
python main.py "https://space.bilibili.com/123456/video" --up --limit 20 --v3 --build-kb
```

检索知识库：

```bash
python main.py --search "这个UP为什么播放高" --top-k 5
```

知识库位置：

```text
cache/knowledge_base/index.json
```

## V4.0

V4 支持输入自然语言研究问题，自动读取本地知识库并生成 Markdown 报告。

```bash
python main.py --report "分析这个UP为什么播放高" --top-k 8
```

先重建知识库再生成报告：

```bash
python main.py --report "分析这个UP为什么播放高" --top-k 8 --build-kb
```

也可以直接运行 V4 模块：

```bash
python -m rag.report "分析这个UP为什么播放高" --top-k 8
```

输出：

```text
output/v4_reports/<时间>_<问题>/
  report.md
  report.json
```

报告优先调用配置好的 LLM；如果没有 `LLM_API_KEY`，会使用本地规则基于知识库证据生成兜底报告。

## Advanced Research Stack

高级栈在保留原有回退路径的基础上增加以下能力：

- `yt-dlp`：抓取视频、字幕和 UP 视频列表。
- `faster-whisper`：没有平台字幕时执行本地语音转录。
- `spaCy`：中文分句、实体和文本统计，写入 V3 分析。
- `Sentence Transformers + ChromaDB`：构建持久化语义向量索引，并与原 TF-IDF 结果做混合检索。
- `PySceneDetect + OpenCV`：检测镜头切点、平均镜头时长和视觉节奏，写入 V3 分析。
- `LangGraph`：按词法索引、向量索引、Creator KB、模板和项目报告的顺序编排完整知识库更新。

构建语义向量库：

```bash
python main.py --build-vector-kb
```

只使用语义向量检索：

```bash
python main.py --semantic-search "如何用镜头变化提升解释节奏" --top-k 8
```

普通 `--search` 默认使用混合检索；向量库尚未构建或模型不可用时会自动回退 TF-IDF：

```bash
python main.py --search "人物动机与世界观如何衔接" --top-k 8
```

运行 LangGraph 高级知识库更新：

```bash
python main.py --advanced-kb
```

镜头和 spaCy 分析随 `--v3` 自动执行。没有本地视频文件时镜头分析会标记为跳过，不影响其余结果。

## Creator Knowledge Base

构建创作者能力知识库、可调用模板库和项目总整合报告：

```bash
python main.py --build-creator-kb
python main.py --build-template-library
python main.py --project-report
```

检索创作者能力与模板：

```bash
python main.py --creator-search "怎么设计一个问题式开头" --top-k 8
python main.py --creator-search "转场模板" --top-k 8
```

UP 定位和别名维护在：

```text
tools/creator_specs.json
```

在 Web UI 的“UP选择”中输入目标方向，可以让配置好的 LLM 结合当前知识库缺口判断是否继续抓取、优先寻找哪些创作者类型以及候选筛选标准。模型调用失败或未配置 `LLM_API_KEY` 时，页面会明确显示原因，并继续提供本地规则建议。

命令行也可以生成同一份决策报告：

```bash
python main.py --up-advisor "自动化视频制作器下一批应该抓哪些系列UP"
```

输出：

```text
output/integrated/up_advisor_report.md
output/integrated/up_advisor_report.json
```

主要输出：

```text
output/creator_knowledge_base/
  manifest.json
  creator_knowledge_base.md / creator_knowledge_base.json
  cross_creator_analysis.md / cross_creator_analysis.json
  creators/<作者>/creator_profile.md / creator_profile.json / style_summary.json
  videos/<视频ID>/video.md / analysis.json / structure.json / keywords.json / summary.json
  templates/template_library.md / template_library.json / template_index.json
```

## 目录

```text
main.py
config.py
pipeline/
downloader/
processor/
analyzer/
exporter/
models/
cache/
output/
logs/
```

## 安装

1. 安装 Python 依赖：

```bash
pip install -r requirements.txt
```

2. FFmpeg 可以通过系统 PATH、`.env` 里的 `FFMPEG_PATH`，或 `imageio-ffmpeg` 自动提供。

3. 可选：复制 `.env.example` 为 `.env`，配置 Whisper、LLM 和各平台 Cookie。

```bash
copy .env.example .env
```

### Whisper GPU 安全加速

Windows 安装 `requirements.txt` 后会同时安装 CTranslate2 所需的 CUDA 12/cuDNN 9 运行库，不需要单独安装完整 CUDA Toolkit。默认配置会：

- 检测 NVIDIA GPU、CUDA DLL、空闲显存和 GPU 占用率。
- 资源充足时使用 `float16` GPU 批量识别；否则自动使用 `int8` CPU。
- GPU 显存不足时依次降低批量大小，仍失败则自动回退 CPU。
- 同一批任务复用模型，并在任务结束后释放模型显存。
- 串行执行 Whisper，避免多个分析任务同时争抢 GPU。

常用配置：

```env
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=auto
WHISPER_BATCH_SIZE=8
WHISPER_MIN_FREE_VRAM_MB=4096
WHISPER_GPU_MAX_UTILIZATION=60
WHISPER_GPU_FALLBACK=true
WHISPER_RELEASE_AFTER_JOB=true
YOUTUBE_WHISPER_LANGUAGE=auto
DOUYIN_WHISPER_LANGUAGE=zh
```

运行状态可在程序控制台查看，也可以执行：

```bash
python -m processor.whisper --status
```

## 运行

```bash
python main.py "https://www.bilibili.com/video/BVxxxx"
```

## Web UI

启动本地界面：

```bash
python web_ui.py
```

浏览器打开：

```text
http://127.0.0.1:7860
```

界面支持输入：

- B站视频链接
- YouTube 视频链接
- YouTube 频道主页链接
- 抖音公开视频分享链接
- 抖音创作者主页链接
- 小红书视频笔记分享链接
- BV号
- UP主页链接
- UP mid
- UP 名

界面功能：

- 自动判断多平台单视频、B站 UP、YouTube 频道或抖音创作者批量
- 可开启 V3 增强
- V3 使用 spaCy、RapidOCR、OpenCV 和 PySceneDetect 分析字幕、封面与镜头节奏
- 可快速更新词法索引，或用 LangGraph 完整更新知识系统
- 完整更新包括 ChromaDB 语义向量库、创作者库、模板库、能力缺口和发现候选池
- 查看任务状态、日志和输出文件
- 使用关键词、语义向量或混合策略检索本地知识库
- 生成 V4 AI研究报告
- 在“创作者发现”中查看能力搜索计划、添加候选、人工批准并启动分析；抖音候选可分析创作者主页或公开视频，小红书候选可分析公开视频样本
- 在“UP抓取决策”中结合当前知识库判断下一批抓取方向

向量模型默认只读取本地缓存，避免 Hugging Face 网络不可用时长时间重试：

```text
SENTENCE_TRANSFORMER_LOCAL_ONLY=true
```

需要首次联网下载模型时可临时改为 `false`，下载完成后恢复为 `true`。

强制忽略缓存：

```bash
python main.py "https://www.bilibili.com/video/BVxxxx" --overwrite
```

输出位置：

```text
output/<视频ID>/
  video.md
  subtitle.txt
  subtitle.srt
  analysis.json
```

缓存位置：

```text
cache/videos/<视频ID>/        # 视频文件或官方字幕缓存
cache/transcripts/<视频ID>/   # 统一后的 txt/srt/json 字幕缓存
cache/analysis/<视频ID>/      # 分析缓存
cache/comments/<视频ID>/      # 评论缓存
cache/covers/<视频ID>/        # 封面缓存
cache/knowledge_base/         # 本地知识库
```

## LLM 配置

如果配置 `LLM_API_KEY`，分析阶段会调用 OpenAI 兼容接口。未配置时会使用本地启发式分析，仍会生成完整的 Markdown 和 JSON。

## 独立模块测试

每个主要模块都带有命令行入口，例如：

```bash
python -m pipeline.acquire "https://www.bilibili.com/video/BVxxxx"
python -m processor.subtitle path/to/subtitle.srt --video-id demo
python -m analyzer.analyze cache/transcripts/demo/subtitle.txt --video-id demo --title demo
python -m exporter.markdown output/demo/analysis.json --video-id demo --title demo
python -m downloader.bilibili_up "https://space.bilibili.com/123456/video" --limit 10
python -m rag.knowledge_base build
python -m rag.knowledge_base search "开头方式"
python -m rag.report "分析这个UP为什么播放高"
```

## 开源版数据边界

本仓库提供流水线、平台适配器、分析模块、能力本体、缺口分析、Creator
Discovery、知识库接口、Web UI、配置模板和测试。运行时生成的数据不属于源码，
不会提交到 Git：

- `.env`、API Key、Cookie 和浏览器登录状态
- 下载的视频、音频、字幕、封面和评论
- `cache/` 中的模型、转录缓存、向量索引和数据库
- `output/` 中的分析报告、Creator Profile 和知识库内容
- `logs/` 中的运行日志

公开仓库不附带任何平台账号，也不绕过平台访问控制。使用者需要自行遵守平台条款、
内容版权和所在地法律。

## License

本项目自有代码使用 [Apache License 2.0](LICENSE)。第三方组件及其许可证见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
