from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from packages.clustering.evaluation import (
    ClusteringEvaluationService,
    load_evaluation_dataset,
    threshold_sweep,
)

DEFAULT_DATASET = Path("tests/evaluation/m3_clustering_eval_v1.jsonl")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic OFFLINE ENGINEERING EVALUATION for M3 clustering."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--format",
        choices=("text", "json", "both"),
        default="both",
        dest="output_format",
    )
    parser.add_argument(
        "--no-threshold-sweep",
        action="store_true",
        help="Skip the bounded read-only threshold candidate sweep.",
    )
    return parser


def _summary(result: object) -> str:
    evaluation = result
    pair = evaluation.pair_metrics  # type: ignore[attr-defined]
    cluster = evaluation.cluster_metrics  # type: ignore[attr-defined]
    performance = evaluation.performance  # type: ignore[attr-defined]
    lines = [
        "OFFLINE ENGINEERING EVALUATION",
        f"dataset_version: {evaluation.dataset_version}",  # type: ignore[attr-defined]
        f"algorithm_version: {evaluation.algorithm_version}",  # type: ignore[attr-defined]
        f"pair_precision: {pair.precision:.4f}",
        f"pair_recall: {pair.recall:.4f}",
        f"pair_f1: {pair.f1:.4f}",
        f"coverage: {pair.coverage:.4f}",
        f"abstention_rate: {pair.abstention_rate:.4f}",
        f"cluster_pairwise_precision: {cluster.pairwise_precision:.4f}",
        f"cluster_pairwise_recall: {cluster.pairwise_recall:.4f}",
        f"cluster_pairwise_f1: {cluster.pairwise_f1:.4f}",
        f"overmerge_count: {cluster.overmerge_count}",
        f"fragmentation_count: {cluster.fragmentation_count}",
        "human_override_respect_rate: "
        f"{evaluation.human_override_respect_rate:.4f}",  # type: ignore[attr-defined]
        f"dataset_size: {performance.dataset_size}",
        f"pair_query_count: {performance.pair_query_count}",
        f"embedding_dimensions: {performance.embedding_dimensions}",
        f"elapsed_ms: {performance.elapsed_ms:.3f}",
    ]
    return "\n".join(lines)


def main() -> int:
    args = _parser().parse_args()
    try:
        signals = load_evaluation_dataset(args.dataset)
        result = ClusteringEvaluationService().evaluate(signals)
        sweep = () if args.no_threshold_sweep else threshold_sweep(signals)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2

    payload = {
        "status": "ok",
        "evaluation_kind": "OFFLINE ENGINEERING EVALUATION",
        "result": result.to_dict(),
        "threshold_sweep": [asdict(item) for item in sweep],
        "threshold_sweep_read_only": True,
        "production_policy_modified": False,
    }
    if args.output_format in {"text", "both"}:
        print(_summary(result))
        if sweep:
            print(f"threshold_candidates: {len(sweep)} (READ ONLY)")
    if args.output_format in {"json", "both"}:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    if result.human_override_respect_rate != 1.0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
