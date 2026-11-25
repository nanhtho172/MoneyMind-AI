"""Read-only index diagnosis. Run retrieval on a disposable copy, with no provider connection."""

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from backend.app.agent.rag import ChromaKnowledge
from backend.app.core.config import Settings
import backend.app.models.chat  # Register chat tables in SQLAlchemy's schema inventory.
from backend.app.models.finance import Base


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    settings = Settings()
    db = Path(make_url(settings.database_url).database)
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(db.as_uri() + "?mode=ro", uri=True))
    inspector = inspect(engine)
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "database": db.name,
        "provider": settings.llm_provider,
        "requested_model": settings.llm_model,
        "reasoning_effort": settings.llm_reasoning_effort,
        "key_loaded": bool(settings.llm_api_key and settings.llm_api_key.get_secret_value().strip()),
        "ip_family": settings.groq_ip_family,
        "embedding_model": settings.embedding_model,
        "path": str(settings.rag_directory),
        "langsmith": settings.langsmith_tracing,
        "dependencies": {
            p: version(p)
            for p in ("fastapi", "langgraph", "chromadb", "sentence-transformers", "httpx", "streamlit")
        },
        "missing_columns": {
            t.name: sorted(set(t.columns.keys()) - {c["name"] for c in inspector.get_columns(t.name)})
            for t in Base.metadata.sorted_tables
            if inspector.has_table(t.name)
        },
        "missing_tables": sorted(set(Base.metadata.tables) - set(inspector.get_table_names())),
    }
    with engine.connect() as conn:
        report["publications"] = [
            list(row)
            for row in conn.exec_driver_sql(
                "SELECT indexing_status,published_collection,count(*),sum(chunk_count) FROM knowledge_files GROUP BY 1,2"
            )
        ]
        report["index_overrides"] = [
            list(r) for r in conn.exec_driver_sql("SELECT namespace,collection_name FROM knowledge_indexes")
        ]
        report["matching_historic_turns"] = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM chat_turns WHERE message IN (?,?)",
            (
                "Với chi tiêu tháng này, tôi nên quản lý chi tiêu như thế nào?",
                "Tôi đã chi những khoản gì hôm nay?",
            ),
        ).scalar()
    with tempfile.TemporaryDirectory(prefix="moneymind-index-audit-", ignore_cleanup_errors=True) as folder:
        copy = Path(folder) / "chroma"
        shutil.copytree(settings.rag_directory, copy)
        vector = ChromaKnowledge(settings.model_copy(update={"rag_directory": copy}), engine)
        name, _, _ = vector._visible()
        report["active_collection"] = name
        client = vector._client()
        report["collections"] = {c.name: c.count() for c in client.list_collections()}
        report["retrieval"] = {}
        for query in (
            "Quy tắc 50/30/20 là gì?",
            "Với chi tiêu tháng này, tôi nên quản lý chi tiêu như thế nào?",
        ):
            try:
                hits = vector.retrieve(query)
                report["retrieval"][query] = [h.chunk_id for h in hits]
            except Exception as exc:
                report["retrieval"][query] = {"error": getattr(exc, "code", type(exc).__name__)}
        close = getattr(client, "close", None)
        if close:
            close()
    engine.dispose()
    (Path(__file__).parent / "results" / "index-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(report["collections"], list(map(len, report["retrieval"].values())))


if __name__ == "__main__":
    main()
