# Creator Knowledge Schema v2

Creator Knowledge Base 是供本地 RAG 和后续 AI 调用的外部知识，不是模型训练后的内部记忆。

知识写入遵循三个层级：

## Observation

Observation 只描述单条视频中检测到的抽象功能信号。

必须包含：

- `observation_id`
- `video_id`
- 创作者和内容定位
- 抽象检测信号
- 所属结构位置和可用时间范围
- 上游分析覆盖范围
- 来源文件
- 自动分析置信度

禁止包含字幕原句、段落、口头禅或可直接模仿的个人表达。

## Pattern

Pattern 聚合多个 Observation，描述信号出现的频率和分布。

必须包含：

- Observation 数量
- 创作者覆盖
- 内容定位和时长分布
- 可定位证据数量
- 代理表现指标
- 替代模式
- 模式置信度
- 数据限制

Pattern 只能声明相关观察重复出现，不能声明传播效果的因果关系。

## Rule

Rule 是基于 Pattern 形成的条件性创作假设。

必须区分：

- `Observed`：视频中直接检测到的功能信号
- `Inferred`：由跨样本模式归纳出的槽位和组织顺序
- `Recommended`：系统提出的剪辑建议、质量检查和停用条件

规则必须包含 Trigger、Goal、Mechanism、Action、Constraints、Evidence、Effect Evidence、Confidence、Counter Evidence、Provenance 和 Revision History。

## Confidence

置信度拆成三个维度：

- `pattern_confidence`：模式确实重复出现的确定程度
- `effect_confidence`：模式能提升传播结果的确定程度
- `evidence_quality`：定位、指标覆盖和人工复核质量

播放量、点赞率和评论率只能作为代理指标。没有留存、完播或受控对照时，`causal_status` 必须为 `not_established` 或 `unverified`。

## Lifecycle

规则状态：

- `candidate`：自动生成，尚未人工复核
- `validated`：已登记人工复核
- `rejected`：人工复核后不成立
- `deprecated`：曾经可用但已被新证据替代

人工复核写入运行目录的 `rules/rule_reviews.json`。生成器只在文件不存在时创建它，不覆盖已有复核记录。

示例：

```json
{
  "version": 1,
  "reviews": {
    "R-001": {
      "approved": true,
      "status": "validated",
      "reviewer": "reviewer-name",
      "reviewed_at": "2026-07-28",
      "notes": "已复核代表 Observation 和反证样本"
    }
  }
}
```

## Retrieval

RAG 索引分别写入 Rule、Pattern 和 Observation 文档。检索结果必须保留 `knowledge_type`、状态、置信度和来源视频，不应把三种知识层混成同一种事实。
