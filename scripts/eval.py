"""Retrieval / guardrail / pruning evaluation on the bundled sample docs.

    python scripts/eval.py                       # fastembed (default model)
    python scripts/eval.py --embedding hash      # offline lexical baseline
    python scripts/eval.py --min-score 0.55      # try another abstain threshold
    python scripts/eval.py --sweep               # compare thresholds side by side

Metrics
  hit@k           answerable questions whose expected file is among the retrieved sources
  abstain         cross-tenant / off-topic questions where the agent correctly retrieved nothing
                  (a miss here means it retrieved a loosely related doc of its OWN tenant)
  leaks           questions where any source came from another tenant (must be 0%)
  answer kept     answerable hits whose answer text survives context pruning
  tokens saved    context tokens removed by pruning (answerable questions)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api.deps import Services  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.demo import DEMO_TENANTS, SAMPLE_DIR, seed_demo  # noqa: E402
from app.main import build_services  # noqa: E402
from app.rag.pruning import prune_passages  # noqa: E402


async def collect(settings: Settings, questions: list[dict]) -> list[dict]:
    """Retrieve for every question once (no score floor); thresholds are applied afterwards."""
    services: Services = build_services(settings)
    await services.db.create_schema()
    await seed_demo(services)
    own_files = {
        tenant: {p.name for p in (SAMPLE_DIR / tenant).glob("*.md")} for tenant in DEMO_TENANTS
    }
    services.pipeline._settings = settings.model_copy(update={"retrieval_min_score": -1.0})
    rows = []
    for q in questions:
        sources = await services.pipeline.retrieve(q["tenant"], q["question"])
        rows.append(q | {"sources": sources, "own_files": own_files[q["tenant"]]})
    await services.db.dispose()
    return rows


def score(rows: list[dict], min_score: float, verbose: bool = False) -> dict:
    hits = answerable = abstained = unanswerable = kept = leaks = 0
    original_tokens = pruned_tokens = 0
    for row in rows:
        sources = [s for s in row["sources"] if s.score >= min_score]
        leaks += any(s.filename not in row["own_files"] for s in sources)
        if row["expect_file"] is None:
            unanswerable += 1
            ok = not sources
            abstained += ok
        else:
            answerable += 1
            ok = row["expect_file"] in {s.filename for s in sources}
            hits += ok
            pruned, stats = prune_passages(row["question"], [s.text for s in sources])
            original_tokens += stats.original_tokens
            pruned_tokens += stats.pruned_tokens
            if ok and any(row["expect_text"] in s.text for s in sources):
                survived = any(row["expect_text"] in p for p in pruned)
                kept += survived
                if verbose and not survived:
                    print(f"PRUNED-AWAY {row['question']!r}: {row['expect_text']!r}")
        if verbose and not ok:
            top = f"{sources[0].filename}@{sources[0].score:.2f}" if sources else "-"
            print(f"MISS [{row['tenant']}] {row['question'][:58]:58s} top={top}")
    return {
        "hit@k (answerable)": hits / answerable,
        "abstain (cross-tenant + off-topic)": abstained / unanswerable,
        "cross-tenant leaks": leaks / len(rows),
        "answer kept after pruning": kept / max(hits, 1),
        "tokens saved by pruning": 1 - pruned_tokens / max(original_tokens, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--embedding", choices=["fastembed", "hash"], default="fastembed")
    parser.add_argument("--min-score", type=float)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--sweep", action="store_true", help="table over thresholds")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    questions = [
        json.loads(line)
        for line in (ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    default_floor = 0.15 if args.embedding == "hash" else 0.6
    min_score = args.min_score if args.min_score is not None else default_floor
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None,
            database_url=f"sqlite+aiosqlite:///{Path(tmp, 'eval.db').as_posix()}",
            embedding_provider=args.embedding,
            retrieval_top_k=args.top_k,
            log_level="WARNING",
        )
        rows = asyncio.run(collect(settings, questions))

    model = settings.embedding_model if args.embedding == "fastembed" else "lexical hashing"
    print(f"embedding: {model} | questions: {len(rows)} | top_k: {args.top_k}")
    print()
    if args.sweep:
        names = list(score(rows, min_score))
        print("| min_score | " + " | ".join(names) + " |")
        print("|---" * (len(names) + 1) + "|")
        for floor in [round(0.40 + 0.05 * i, 2) for i in range(8)]:
            values = score(rows, floor).values()
            print(f"| {floor:.2f} | " + " | ".join(f"{v:.0%}" for v in values) + " |")
        return
    results = score(rows, min_score, verbose=args.verbose)
    print(f"min_score: {min_score}")
    print()
    print("| metric | value |")
    print("|---|---|")
    for name, value in results.items():
        print(f"| {name} | {value:.0%} |")


if __name__ == "__main__":
    main()
