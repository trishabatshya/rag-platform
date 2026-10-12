"""Isolated paired vector-filter overhead and immediate revoke-to-effect benchmark."""

import argparse
import csv
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import numpy as np

from app.acl import build_filter, can_access, update_acl
from app.config import ROOT, Settings
from app.contracts import CurrentUser
from app.corpus_state import CorpusState
from app.embed import embed
from app.ingest import ingest_acl_documents
from app.vectorstore import create_client


def run_benchmark(output_dir: Path, queries: int = 200) -> tuple[Path, dict]:
    """Measure at least 200 paired raw queries in a disposable benchmark-only collection."""
    if queries < 200:
        raise ValueError("ACL benchmark requires at least 200 paired queries")
    settings = Settings()
    documents = json.loads((settings.seed_dir / "documents.json").read_text(encoding="utf-8"))
    records = json.loads((settings.seed_dir / "users.json").read_text(encoding="utf-8"))
    users = [CurrentUser(row["user_id"], row["tenant_id"], tuple(row["roles"])) for row in records]
    workload = [
        f"Show {documents[i % len(documents)]['doc_id']} {documents[i % len(documents)]['text']}"
        for i in range(queries)
    ]
    vectors = embed(workload)
    collection = "acl_benchmark_" + uuid4().hex
    rows = []
    with TemporaryDirectory(prefix="Northwind ACL benchmark ") as temporary:
        state = CorpusState(Path(temporary) / "state.db")
        with closing(create_client()) as client:
            try:
                ingest_acl_documents(documents, client, state, collection=collection)
                # Warm both paths; only pure vector operations are timed, not embedding or audit.
                client.query_points(collection, query=vectors[0].tolist(), limit=5)
                client.query_points(
                    collection,
                    query=vectors[0].tolist(),
                    query_filter=build_filter(users[0]),
                    limit=5,
                )
                for index, vector in enumerate(vectors):
                    user = users[index % len(users)]
                    filtering = build_filter(user)
                    timings = {}
                    # Alternate order to reduce a systematic warm-cache/order bias.
                    order = (False, True) if index % 2 == 0 else (True, False)
                    for enabled in order:
                        start = perf_counter()
                        response = client.query_points(
                            collection,
                            query=vector.tolist(),
                            limit=5,
                            with_payload=True,
                            query_filter=filtering if enabled else None,
                        )
                        timings[enabled] = (perf_counter() - start) * 1000
                        if enabled and any(
                            not can_access(point.payload or {}, user) for point in response.points
                        ):
                            raise AssertionError("Filtered benchmark retrieval violated an ACL")
                    rows.append(
                        {
                            "measurement": "filter_pair",
                            "query_no": index + 1,
                            "with_filter_ms": timings[True],
                            "without_filter_ms": timings[False],
                            "overhead_ms": timings[True] - timings[False],
                            "revoke_to_effect_ms": "",
                            "mode": settings.mode.upper(),
                            "backend": "qdrant_memory"
                            if settings.mode == "mock"
                            else "qdrant_server",
                            "scope": (
                                "raw vector operations; excludes embedding, generation and audit"
                            ),
                        }
                    )
                engineer = next(user for user in users if "engineer" in user.roles)
                admin = next(
                    user
                    for user in users
                    if user.tenant_id == engineer.tenant_id and "admin" in user.roles
                )
                target = next(
                    document
                    for document in documents
                    if document["tenant_id"] == engineer.tenant_id
                    and document["doc_id"].endswith(":engineering-wiki")
                )
                revoke_vector = embed([target["text"]])[0].tolist()
                before = client.query_points(
                    collection, query=revoke_vector, query_filter=build_filter(engineer), limit=5
                )
                if target["doc_id"] not in {point.payload["doc_id"] for point in before.points}:
                    raise AssertionError("Revoke benchmark needs a retrievable positive control")
                start = perf_counter()
                update_acl(
                    target["doc_id"],
                    allowed_roles=["admin"],
                    allowed_users=[],
                    classification="confidential",
                    user=admin,
                    client=client,
                    state=state,
                    collection=collection,
                )
                after = client.query_points(
                    collection, query=revoke_vector, query_filter=build_filter(engineer), limit=5
                )
                elapsed = (perf_counter() - start) * 1000
                if target["doc_id"] in {point.payload["doc_id"] for point in after.points}:
                    raise AssertionError("Revocation did not affect the very next query")
                rows.append(
                    {
                        "measurement": "revoke",
                        "query_no": "",
                        "with_filter_ms": "",
                        "without_filter_ms": "",
                        "overhead_ms": "",
                        "revoke_to_effect_ms": elapsed,
                        "mode": settings.mode.upper(),
                        "backend": "qdrant_memory" if settings.mode == "mock" else "qdrant_server",
                        "scope": "epoch bump + payload update + immediate verification query",
                    }
                )
            finally:
                if client.collection_exists(collection):
                    client.delete_collection(collection)
    summary = {
        "mode": settings.mode.upper(),
        "paired_queries": queries,
        "median_with_filter_ms": float(np.median([row["with_filter_ms"] for row in rows[:-1]])),
        "median_without_filter_ms": float(
            np.median([row["without_filter_ms"] for row in rows[:-1]])
        ),
        "median_paired_overhead_ms": float(np.median([row["overhead_ms"] for row in rows[:-1]])),
        "revoke_to_effect_ms": rows[-1]["revoke_to_effect_ms"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"acl_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.csv"
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path, summary


def main() -> None:
    """Print only measurements from this invocation; mock output is never a real result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval" / "results")
    args = parser.parse_args()
    path, summary = run_benchmark(args.output_dir, args.queries)
    if Settings().mode == "mock":
        print("MOCK (not a result): in-memory vector timings, not production latency.")
    print(json.dumps(summary, indent=2))
    print(f"CSV: {path}")


if __name__ == "__main__":
    main()
