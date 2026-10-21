# Creator Knowledge Schema v3

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

Rule 是基于 Pattern 形成的条件性创作能力提案，不是命令。

统一语义：

```text
Condition
→ Candidate Ability Pool
→ Same-layer Competition
→ Cross-layer Composition
→ Capability Plan
```

条件成立只允许能力进入候选池，不代表必须调用。条件不成立时不触发；
条件未知时，只允许标记为低置信度候选。禁止为了调用能力而扩大条件解释。

必须区分：

- `Observed`：视频中直接检测到的功能信号
- `Inferred`：由跨样本模式归纳出的槽位和组织顺序
- `Recommended`：系统提出的剪辑建议、质量检查和停用条件

规则必须包含 ID、Name、Layer、Definition、Condition、Intended Function、
Selection Mode、Status、Evidence、Confidence，以及 Trigger、Goal、Mechanism、
Action、Constraints、Counter Evidence、Provenance 和 Revision History。

`selection_mode` 必须为 `candidate`。同一 Layer 的候选能力进行竞争，通常选一个
Primary Ability，并可在有明确理由时增加 Secondary Ability；不同 Layer 可以组合。

能力层级固定为：

- `opening`
- `narrative_structure`
- `transition`
- `climax`
- `ending`
- `workflow`

## Confidence

置信度至少拆成三个语义维度：

- `pattern_existence`：模式确实存在的确定程度
- `functional_interpretation`：模式可以合理解释为声明功能的确定程度
- `causal_effect`：能力是否导致传播结果；没有实验时必须为 `unverified`

兼容审计字段继续保留：`pattern_confidence`、`effect_confidence` 和
`evidence_quality`。

播放量、点赞率和评论率只能作为代理指标。没有留存、完播或受控对照时，`causal_status` 必须为 `not_established` 或 `unverified`。

## Lifecycle

规则状态：

- `candidate`：自动生成，尚未人工复核
- `under_review`：已有证据，正在人工验证
- `validated`：已登记人工复核
- `rejected`：人工复核后不成立
- `deprecated`：曾经可用但已被新证据替代

人工复核写入运行目录的 `rules/rule_reviews.json`。生成器只在文件不存在时创建它，不覆盖已有复核记录。

Agent 发现的新模式只能写入 `rules/candidate_knowledge.json`，权限为
`propose_only`。Candidate 必须包含来源、Observation、Evidence、Reasoning、
Possible Function、Alternative Interpretation 和拆分后的 Confidence。
正式 Rule 只能由验证流程产生；未经 `approved` 的记录不能进入 `validated`。

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

## Capability Planner

Rule Matching 只生成候选能力池。Capability Planner 负责：

1. 按 Layer 分类候选能力。
2. 在同一 Layer 内比较并选择 Primary Ability。
3. 必要时选择 Secondary Ability。
4. 将不同 Layer 的选择组合为 Capability Plan。
5. 保留放弃全部候选能力的权利。

命令行调用：

```bash
python main.py --capability-plan "存在反差和冲突，需要历史叙事与观点闭环"
```
