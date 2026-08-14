# W4 消融实验报告（LLM 裁判: `api`，18 题黄金评测集）

> 本次为 **全真实模式**：嵌入 bge-m3 + 重排 bge-reranker-v2-m3（SiliconFlow）+ LLM 裁判 DeepSeek，四个指标均为真实值，可直接用于调参。

| 配置 | context_precision（检索精准度） | context_recall（检索召回） | faithfulness（忠于资料） | answer_relevancy（切题） | no_answer_rate（拒答率） |
|---|------|---|---|---|---|
| 混合检索+重排 (chunk500) | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| 纯向量检索 (chunk500) | 0.9444 | 1.0 | 1.0 | 1.0 | 0.0 |
| 混合检索 无重排 (chunk500) | 0.9444 | 1.0 | 1.0 | 1.0 | 0.0 |
| 混合检索+重排 (chunk300) | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
