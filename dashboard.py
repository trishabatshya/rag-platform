"""Local-operator dashboard over measured request logs, including explicit mock labels."""

from contextlib import closing

from app.logging_db import create_request_store


def main() -> None:
    """Render request cost, cache/routing/escalation, latency and known judged quality."""
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Northwind RAG measurements", layout="wide")
    st.title("Northwind RAG measurements")
    st.caption("Cost is estimated at reference prices. This dashboard is a local operator tool.")
    with closing(create_request_store()) as store:
        rows = store.rows()
    if not rows:
        st.info("No request measurements yet. Ask a question or run python tasks.py bench-cache.")
        return
    frame = pd.DataFrame(rows)
    modes = sorted(frame["mode"].unique())
    mode = st.selectbox("Runtime mode", modes)
    frame = frame[frame["mode"] == mode]
    if mode == "MOCK":
        st.warning(
            "MOCK (not a result): fake models/embeddings/token counts; "
            "do not publish these as real results."
        )
    tag = st.selectbox("Run tag", ["All"] + sorted(frame["run_tag"].unique()))
    if tag != "All":
        frame = frame[frame["run_tag"] == tag]
    columns = st.columns(4)
    columns[0].metric("Mean cost/request (reference USD)", f"{frame['cost'].mean():.6f}")
    columns[1].metric("Cache hit rate", f"{frame['cache_hit'].mean():.1%}")
    columns[2].metric("Escalation rate", f"{frame['escalated'].mean():.1%}")
    columns[3].metric("Requests", str(len(frame)))
    st.write(
        {
            "p50_latency_ms": float(frame["latency_ms"].quantile(0.5)),
            "p95_latency_ms": float(frame["latency_ms"].quantile(0.95)),
        }
    )
    st.caption(
        "Logged latency includes cache writes and excludes the final request-log commit. "
        "Benchmark CSVs time the full service separately."
    )
    st.subheader("Route split")
    st.bar_chart(frame["route"].value_counts())
    st.subheader("Reference cost over time")
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    st.line_chart(frame.set_index("ts")[["cost"]])
    st.subheader("Judged quality by route over time")
    judged = frame.dropna(subset=["quality"])
    if judged.empty:
        st.info("Quality is unknown: no reference judge was run for these requests.")
    else:
        st.line_chart(judged.pivot_table(index="ts", columns="route", values="quality"))
    st.dataframe(
        frame[
            [
                "ts",
                "mode",
                "run_tag",
                "route",
                "model",
                "cache_hit",
                "escalated",
                "cost",
                "latency_ms",
                "quality",
                "error",
            ]
        ]
    )


if __name__ == "__main__":
    main()
