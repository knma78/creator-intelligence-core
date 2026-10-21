# 采集契约与统一资源调度

## 采集契约

流水线不再把“下载器返回了 `Video`”当成完整的采集状态。新增
`AcquisitionResult`，明确记录四层信息：

- `AccessAssessment`：平台登录状态、内容权益状态、媒体可用性和判断证据。
- `AcquisitionPlan`：首选采集策略及合规回退策略。
- `MediaArtifact`：视频、字幕和元数据等实际产物。
- `AcquisitionResult`：最终采用的策略、产物、`Video` 兼容对象和本地清单。

单视频采集清单写入：

```text
cache/acquisitions/<platform>/<video_id>.json
```

当前可识别的结果策略包括本地文件、平台官方字幕和直接下载。浏览器播放采集与
人工导入已作为正式回退策略进入领域模型，但本次没有实现录制或绕过平台保护。
后续实现 Windows 本地播放采集时，只需增加策略执行器，并继续向后续流水线提供
同一种 `AcquisitionResult`。

旧接口 `acquire_video()` 仍返回 `Video`；新增
`acquire_video_details()` 返回完整采集契约。Pipeline result schema 更新为
`1.1`，新增可选的 `acquisition` 字段，旧结果仍可正常校验。

## 统一资源调度

`infrastructure/resources.py` 提供进程内统一资源租约：

- `network_io`：平台元数据、字幕和媒体采集。
- `cpu_heavy`：FFmpeg、场景检测、音频解码和节奏特征。
- `gpu_inference`：Whisper 与 OpenCLIP 推理。

默认 GPU 并发为 1。Whisper 和 OpenCLIP 使用不同模型族；模型族切换时，调度器
会先调用上一模型族的释放钩子，再允许下一模型进入 GPU，以降低 8GB 显存环境中
两个大模型同时驻留导致 OOM 的概率。同一线程重复申请同类资源采用可重入租约，
所以音频节奏分析内部再次调用 FFmpeg 不会发生自锁。

配置：

```env
RESOURCE_NETWORK_SLOTS=3
RESOURCE_CPU_HEAVY_SLOTS=2
RESOURCE_GPU_SLOTS=1
RESOURCE_ACQUIRE_TIMEOUT=3600
```

Web 健康接口 `/api/health` 的 `resources` 字段会显示限制、当前占用、等待数量和
当前 GPU 模型族。

## 边界

- 调度器负责本进程内的并发和显存模型族互斥，不是跨机器调度系统。
- OpenCLIP 是否真正使用 GPU 仍取决于其 PyTorch 是否为 CUDA 构建；配置
  `OPENCLIP_DEVICE=auto` 时会优先选择可用 CUDA。
- Whisper 保留原有显存门槛、利用率检查、批量降级和 CPU 回退逻辑。
- 权限模型不会把“账号已登录”推断成“作品有观看权”，也不会把“作品可观看”
  推断成“下载器能取得媒体流”。

## B站权限预检

`BilibiliEntitlementService` 分别输出账号登录、会员类型和有效期、内容要求、
观看资格、官方字幕、媒体流以及推荐策略。预检失败不会阻断普通下载；只有本地
播放采集才要求观看资格明确通过。

Web API：

```text
POST /api/bilibili/entitlement
{"source": "https://www.bilibili.com/bangumi/play/ss..."}
```

## Windows 本地播放采集

本地播放采集必须由任务显式勾选授权。程序打开默认浏览器并等待用户确认播放，
然后通过 PyAudioWPatch 的 WASAPI loopback 录制默认输出设备，保存标准 WAV 后
进入 Whisper。录制期间可以停止，已录部分会继续分析。

安全边界：

- 不破解 DRM，不读取或解密客户端缓存。
- WASAPI 录制整个输出设备的声音，UI 会明确提示。
- 静音或损坏录音不会进入 Whisper 和知识库。
- 服务重启不会自动恢复交互式录音，必须重新确认并提交。
