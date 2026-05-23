"""Vault ingestion — ^id injection, indexing, file watcher. See ADR-0012, ADR-0017."""

from .pipeline import Embedder, IngestReport, ingest, ingest_file
from .watcher import watch

__all__ = ["Embedder", "IngestReport", "ingest", "ingest_file", "watch"]
