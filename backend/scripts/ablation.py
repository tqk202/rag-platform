"""W4 消融实验：控制变量对比不同配置的检索质量。

每个配置跑在独立子进程里（scripts/run_eval.py），环境变量注入配置，
保证"只改一个变量"——这是消融实验的核心方法论。

用法：
  python scripts/ablation.py            # 全部用 mock（占位数字，免费，验证流程）
  python scripts/ablation.py api        # LLM 裁判用真实 DeepSeek（花几分钱，出真实指标）

四组配置回答三个消融问题：
  1. 混合检索 vs 纯向量检索        → SEARCH_MODE hybrid|vector
  2. 有重排 vs 无重排              → RERANKER_BACKEND lexical|none
  3. chunk_size 500 vs 300         → CHUNK_SIZE
结果对比表写入 eval_reports/ablation_report.md。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
RUN_EVAL = BACKEND_DIR / "scripts" / "run_eval.py"
REPORT_DIR = BACKEND_DIR / "eval_reports"
LLM = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("mock", "api") else "mock"

# 消融配置：每组只改一个变量，其余保持生产默认
CONFIGS = [
    {
        "label": "混合检索+重排 (chunk500)",
        "env": {"SEARCH_MODE": "hybrid", "RERANKER_BACKEND": "lexical", "CHUNK_SIZE": "500"},
    },
    {
        "label": "纯向量检索 (chunk500)",
        "env": {"SEARCH_MODE": "vector", "RERANKER_BACKEND": "none", "CHUNK_SIZE": "500"},
    },
    {
        "label": "混合检索 无重排 (chunk500)",
        "env": {"SEARCH_MODE": "hybrid", "RERANKER_BACKEND": "none", "CHUNK_SIZE": "500"},
    },
    {
        "label": "混合检索+重排 (chunk300)",
        "env": {"SEARCH_MODE": "hybrid", "RERANKER_BACKEND": "lexical", "CHUNK_SIZE": "300"},
    },
]


def run_one(index: int, cfg: dict) -> dict:
    report_json = REPORT_DIR / f"run_{index}.json"
    env = {
        **os.environ,
        **cfg["env"],
        "LLM_BACKEND": LLM,
        "LABEL": cfg["label"],
        "REPORT_JSON": str(report_json),
    }
    print(f"\n>>> 运行配置 {index + 1}/{len(CONFIGS)}：{cfg['label']}（LLM={LLM}）")
    subprocess.run([sys.executable, str(RUN_EVAL)], env=env, cwd=BACKEND_DIR, check=True)
    return json.loads(report_json.read_text(encoding="utf-8"))


def to_md(reports: list[dict]) -> str:
    keys = ["context_precision", "context_recall", "faithfulness", "answer_relevancy", "no_answer_rate"]
    header = "| 配置 | " + " | ".join(
        {"context_precision": "context_precision（检索精准度）",
         "context_recall": "context_recall（检索召回）",
         "faithfulness": "faithfulness（忠于资料）",
         "answer_relevancy": "answer_relevancy（切题）",
         "no_answer_rate": "no_answer_rate（拒答率）"}[k] for k in keys
    ) + " |"
    sep = "|---|---" + "---|" * len(keys)
    lines = [header, sep]
    for r in reports:
        m = r["metrics"]
        lines.append(
            f"| {r['label']} | "
            + " | ".join(str(m[k]) for k in keys)
            + " |"
        )
    return "\n".join(lines)


def main() -> None:
    if LLM != "mock":
        print("提示：本次用真实 LLM 裁判，会产生少量 API 费用。")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = [run_one(i, cfg) for i, cfg in enumerate(CONFIGS)]

    md = to_md(reports)
    print("\n\n========== 消融实验对比表 ==========\n")
    print(md)

    # 每个指标的最佳配置
    keys = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    print("\n最佳配置：")
    for k in keys:
        best = max(reports, key=lambda r: r["metrics"][k])
        print(f"  {k:22} -> {best['label']}  ({best['metrics'][k]})")

    out_path = REPORT_DIR / "ablation_report.md"
    note = (
        "> 本次为 **mock 模式**：嵌入用哈希占位（无语义）、LLM 裁判用启发式。"
        "数字只用来验证评测流程能跑通、以及检索侧的相对对比（纯向量 < 混合、无重排 < 有重排）。"
        "真实的 embedding（bge-m3）+ LLM 裁判跑出来的绝对指标，需在切换生产模式后重跑本实验。"
        if LLM == "mock"
        else "> 本次为 **真实模式**：LLM 裁判为真实 DeepSeek，faithfulness / answer_relevancy 是真实指标，可直接用于调参。"
        "检索侧嵌入仍为 mock（哈希占位、无语义），context_precision / context_recall 只体现检索配置的相对差异，"
        "绝对检索指标需在切换生产模式换 bge-m3 后重跑。"
    )
    out_path.write_text(
        f"# W4 消融实验报告（LLM 裁判: `{LLM}`，{len(reports[0]['per_case'])} 题黄金评测集）\n\n{note}\n\n{md}\n",
        encoding="utf-8",
    )
    print(f"\n报告已写入 {out_path}")


if __name__ == "__main__":
    main()
