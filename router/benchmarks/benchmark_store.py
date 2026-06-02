from __future__ import annotations

from uuid import uuid4

from memory.postgres.db import execute, fetch


async def save_metric(
    model_name,
    task_type,
    latency_ms,
    tokens_used,
    success,
    hallucination_flag,
):
    query = """
        INSERT INTO model_metrics (
            metric_id,
            model_name,
            task_type,
            latency_ms,
            tokens_used,
            success,
            hallucination_flag
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """
    await execute(
        query,
        uuid4(),
        model_name,
        task_type,
        latency_ms,
        tokens_used,
        success,
        hallucination_flag,
    )


async def get_model_stats(model_name):
    query = """
        SELECT
            AVG(latency_ms) AS avg_latency_ms,
            AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate
        FROM model_metrics
        WHERE model_name = $1
    """
    rows = await fetch(query, model_name)
    if not rows:
        return {"avg_latency_ms": None, "success_rate": None}

    row = rows[0]
    return {
        "avg_latency_ms": row["avg_latency_ms"],
        "success_rate": row["success_rate"],
    }
