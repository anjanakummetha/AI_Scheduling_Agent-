"""LLM cost ledger (plan Phase 3) — per-call token usage for budget tracking.

Rough USD estimate uses per-MTok rates; cache reads are billed at ~0.1x input.
Rates are approximate and easy to update as pricing changes.
"""

from __future__ import annotations

from typing import Any

from app.storage.lexi_db import get_lexi_connection

# Approximate USD per million tokens (input, output). Cache reads ≈ 0.1x input.
_RATES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
}
_DEFAULT_RATE = (3.0, 15.0)


def _ensure_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            role TEXT,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_creation_tokens INTEGER DEFAULT 0,
            est_usd REAL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_cost_ts ON llm_cost_log(ts)")


def estimate_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> float:
    in_rate, out_rate = _RATES.get(model, _DEFAULT_RATE)
    fresh_in = max(0, input_tokens)  # SDK reports uncached input in input_tokens
    return round(
        (fresh_in * in_rate
         + cache_creation_tokens * in_rate * 1.25
         + cache_read_tokens * in_rate * 0.1
         + output_tokens * out_rate)
        / 1_000_000,
        6,
    )


def record_llm_call(
    *,
    role: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    est = estimate_usd(model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens)
    with get_lexi_connection() as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO llm_cost_log
              (role, model, input_tokens, output_tokens, cache_read_tokens,
               cache_creation_tokens, est_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (role, model, input_tokens, output_tokens, cache_read_tokens,
             cache_creation_tokens, est),
        )
        conn.commit()


def cost_rollup(days: int = 30) -> dict[str, Any]:
    """Aggregate spend + cache-hit ratio over the last `days` — for status/briefing."""
    with get_lexi_connection() as conn:
        _ensure_table(conn)
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(est_usd), 0) AS usd,
                   COALESCE(SUM(input_tokens), 0) AS in_tok,
                   COALESCE(SUM(output_tokens), 0) AS out_tok,
                   COALESCE(SUM(cache_read_tokens), 0) AS cache_read
            FROM llm_cost_log
            WHERE ts >= datetime('now', '-{int(days)} days')
            """
        ).fetchone()
    calls = int(row["calls"] or 0)
    cache_read = int(row["cache_read"] or 0)
    in_tok = int(row["in_tok"] or 0)
    return {
        "days": days,
        "calls": calls,
        "est_usd": round(float(row["usd"] or 0), 4),
        "input_tokens": in_tok,
        "output_tokens": int(row["out_tok"] or 0),
        "cache_read_tokens": cache_read,
        "cache_hit_ratio": round(cache_read / (cache_read + in_tok), 3) if (cache_read + in_tok) else 0.0,
    }
