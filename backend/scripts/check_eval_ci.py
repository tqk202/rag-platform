"""CI 评测护栏（P2-6）：跑一遍黄金评测，质量回退即失败。

每次提交都在 CI 里跑离线 mock 评测（不烧 API），与 committed 基线对比：
可答题的四个指标任一跌过容差、no_answer_rate 升过容差、拒答准确率跌过
容差，CI 红——防止改检索/切片/重排时回答质量无声退化（"质量是每次提交
都在守，不是上线时测一次"）。

容差可调：EVAL_TOLERANCE 环境变量（默认 0.05）。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE = BACKEND_DIR / "eval_data" / "ci_baseline.json"
TOLERANCE = float(os.getenv("EVAL_TOLERANCE", "0.05"))
KEYS = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["metrics"]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        report_path = f.name
    try:
        # 钉死离线配置：护栏必须不烧 API、不依赖本地 .env，否则 .env 里配了
        # 真实 rerank/embedding 会导致本地跑护栏既花钱又和 CI 结果不一致。
        env = {
            **os.environ,
            "REPORT_JSON": report_path,
            "LABEL": "CI 评测护栏",
            "RERANKER_BACKEND": "lexical",
            "EMBEDDING_BACKEND": "mock",
            "LLM_BACKEND": "mock",
        }
        subprocess.run(
            [sys.executable, "scripts/run_eval.py"],
            cwd=BACKEND_DIR, env=env, check=True,
        )
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    finally:
        Path(report_path).unlink(missing_ok=True)

    metrics = report["metrics"]

    failures: list[str] = []
    for k in KEYS:
        drop = baseline[k] - metrics[k]
        if drop > TOLERANCE:
            failures.append(f"{k}: 基线 {baseline[k]:.3f} -> 现在 {metrics[k]:.3f}（跌 {drop:.3f} > {TOLERANCE}）")
    rise = metrics["no_answer_rate"] - baseline["no_answer_rate"]
    if rise > TOLERANCE:
        failures.append(f"no_answer_rate 上升 {rise:.3f} > {TOLERANCE}")
    base_rej = baseline.get("reject_accuracy")
    if base_rej is not None:
        rej_drop = base_rej - metrics.get("reject_accuracy", 0.0)
        if rej_drop > TOLERANCE:
            failures.append(f"reject_accuracy 跌 {rej_drop:.3f} > {TOLERANCE}（基线 {base_rej:.3f}）")

    print("== CI 评测护栏（黄金集）==")
    for k in KEYS:
        print(f"  {k:20} {baseline[k]:.3f} -> {metrics[k]:.3f}")
    print(f"  no_answer_rate       {baseline['no_answer_rate']:.3f} -> {metrics['no_answer_rate']:.3f}")
    if base_rej is not None:
        print(f"  reject_accuracy      {base_rej:.3f} -> {metrics.get('reject_accuracy', 0.0):.3f}")

    if failures:
        print("质量回退：")
        for msg in failures:
            print("  [FAIL]", msg)
        return 1
    print("质量无回退 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
