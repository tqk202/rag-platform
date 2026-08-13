# W4 消融实验报告（LLM 裁判: `api`，18 题黄金评测集）

> 本次为 **真实模式**：LLM 裁判为真实 DeepSeek，faithfulness / answer_relevancy 是真实指标，可直接用于调参。
> 检索侧嵌入仍为 mock（哈希占位、无语义），context_precision / context_recall 只体现检索配置的相对差异，
> 绝对检索指标需在切换生产模式换 bge-m3 后重跑。

| 配置 | context_precision（检索精准度） | context_recall（检索召回） | faithfulness（忠于资料） | answer_relevancy（切题） | no_answer_rate（拒答率） |
|---|------|---|---|---|---|
| 混合检索+重排 (chunk500) | 0.9444 | 1.0 | 1.0 | 1.0 | 0.0 |
| 纯向量检索 (chunk500) | 0.2102 | 0.5 | 0.8333 | 0.5556 | 0.4444 |
| 混合检索 无重排 (chunk500) | 0.6459 | 1.0 | 1.0 | 1.0 | 0.0 |
| 混合检索+重排 (chunk300) | 0.9954 | 1.0 | 1.0 | 1.0 | 0.0 |
