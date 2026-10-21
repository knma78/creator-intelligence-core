# ContentResearch 领域架构

## 目标

ContentResearch 仍采用单仓库和单机部署，但内容研究、小说创作和视频生产不再由
Web 服务器直接拼装。单仓库用于共享任务存储、取消、文件访问和配置，不代表各领域
可以互相直接导入实现。

```text
Web / CLI app shell
        ↓
features.api + features.bootstrap
        ↓
Feature job contract
   ├── novel
   └── video_production
          ├── script_video
          └── source_editing
```

## 依赖规则

1. `webapp/server.py` 只能通过 `features.api` 使用小说和视频生产能力。
2. 领域任务统一通过 `FeatureJobServices` 接收进度与文件序列化端口。
3. `features/novel` 与 `features/video_production` 禁止互相导入。
4. 内嵌抖音项目只能由 `downloader/douyin_adapter.py` 调用；核心代码不能依赖其内部模块。
5. 旧入口可以保留兼容转发，但不能重新承载领域实现。

这些规则由 `tests/test_architecture_guards.py` 自动检查。

## 视频生产职责

```text
production/script_video.py  流水线编排、TTS 与渲染
production/captions.py      字幕解析、切分、时间轴与格式写入
production/assets.py        蒸馏封面发现、语义匹配与审计评分
production/script_runtime.py 依赖与 Windows SAPI 运行时检测
production/script_schema.py 稳定格式版本
```

原有 `production.script_video` 公共导入仍然有效，避免破坏 UI、工具脚本和已有测试。

## 规则知识职责

```text
exporter/rule_library.py    样本匹配、Observation/Pattern/Rule 与置信度
exporter/rule_documents.py  RAG 文档、Markdown 和逐视频观察输出
```

文档格式的变化不应影响证据选择；证据算法的变化也不应要求修改 Markdown 生成器。

## 当前规模护栏

架构测试为仍承担编排职责的模块设置上限：

- `webapp/server.py`：不超过 1900 行；
- `production/script_video.py`：不超过 1400 行；
- `exporter/rule_library.py`：不超过 1550 行。

行数不是质量指标，但可以阻止已拆出的职责被重新塞回单体文件。

## 数据兼容性

领域拆分不修改以下稳定边界：

- `output/<video_id>/analysis.json`；
- Creator Knowledge Base v3；
- DuckDB、能力本体 SQLite 和任务 SQLite；
- Web API 路径与任务结果中的 `files` 契约；
- CLI 入口和本地缓存目录。
