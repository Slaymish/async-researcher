"""DuckDB-backed vector store.

Stores file manifests, chunks, frontmatter metadata, and embeddings. Schema migrations
are idempotent — running against an existing db is a no-op. Embedding dimension is set
at first migration and recorded in a `meta` table; a mismatch on subsequent runs raises
(changing embedding model = re-create the index).
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import duckdb

from .types import Chunk, FileSig, ScoredChunk

_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-]*")
_STOPWORDS = {
    "about",
    "and",
    "are",
    "block",
    "did",
    "find",
    "for",
    "from",
    "have",
    "that",
    "the",
    "this",
    "what",
    "where",
    "which",
    "with",
}


class EmbeddingDimensionMismatch(RuntimeError):
    pass


class DuckDBStore:
    def __init__(self, db_path: Path, embedding_dim: int, *, read_only: bool = False) -> None:
        self.db_path = db_path
        self.embedding_dim = embedding_dim
        self.read_only = read_only
        self._lock = Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(db_path), read_only=read_only)
        if not read_only:
            self._migrate()
        else:
            self._validate_existing_schema()

    def close(self) -> None:
        self._con.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            self._con.execute("BEGIN")
            try:
                yield self._con
                self._con.execute("COMMIT")
            except Exception:
                self._con.execute("ROLLBACK")
                raise

    def _migrate(self) -> None:
        c = self._con
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = c.execute("SELECT value FROM meta WHERE key = 'embedding_dim'").fetchone()
        if row is None:
            c.execute(
                "INSERT INTO meta(key, value) VALUES ('embedding_dim', ?)",
                [str(self.embedding_dim)],
            )
        else:
            stored = int(row[0])
            if stored != self.embedding_dim:
                raise EmbeddingDimensionMismatch(
                    f"DB at {self.db_path} was built with embedding_dim={stored}, "
                    f"config requests {self.embedding_dim}. Delete the db or revert the model."
                )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                relpath TEXT PRIMARY KEY,
                size BIGINT NOT NULL,
                mtime_ns BIGINT NOT NULL,
                content_hash TEXT NOT NULL
            )
            """
        )
        c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS chunks (
                block_id TEXT PRIMARY KEY,
                relpath TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                frontmatter JSON,
                embedding FLOAT[{self.embedding_dim}],
                created_at TIMESTAMP DEFAULT now()
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS chunks_relpath_idx ON chunks(relpath)")

    def _validate_existing_schema(self) -> None:
        row = self._con.execute("SELECT value FROM meta WHERE key = 'embedding_dim'").fetchone()
        if row is None:
            raise EmbeddingDimensionMismatch(
                f"DB at {self.db_path} has no embedding_dim metadata. Re-run ingestion."
            )
        stored = int(row[0])
        if stored != self.embedding_dim:
            raise EmbeddingDimensionMismatch(
                f"DB at {self.db_path} was built with embedding_dim={stored}, "
                f"config requests {self.embedding_dim}. Delete the db or revert the model."
            )

    # ---- file manifest --------------------------------------------------------

    def get_file_signature(self, relpath: str) -> FileSig | None:
        row = self._con.execute(
            "SELECT relpath, size, mtime_ns, content_hash FROM files WHERE relpath = ?",
            [relpath],
        ).fetchone()
        if row is None:
            return None
        return FileSig(relpath=row[0], size=row[1], mtime_ns=row[2], content_hash=row[3])

    def set_file_signature(self, sig: FileSig) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO files(relpath, size, mtime_ns, content_hash)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(relpath) DO UPDATE SET
                    size = EXCLUDED.size,
                    mtime_ns = EXCLUDED.mtime_ns,
                    content_hash = EXCLUDED.content_hash
                """,
                [sig.relpath, sig.size, sig.mtime_ns, sig.content_hash],
            )

    def delete_file(self, relpath: str) -> int:
        with self._tx() as c:
            n = c.execute(
                "DELETE FROM chunks WHERE relpath = ?", [relpath]
            ).fetchone()
            c.execute("DELETE FROM files WHERE relpath = ?", [relpath])
        return n[0] if n else 0

    # ---- chunks ---------------------------------------------------------------

    def upsert_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        with self._tx() as c:
            # Replace strategy: delete-by-relpath then insert. Cleaner than per-row upsert
            # when a file is fully reprocessed.
            relpaths = {ch.relpath for ch in chunks}
            for rp in relpaths:
                c.execute("DELETE FROM chunks WHERE relpath = ?", [rp])
            c.executemany(
                """
                INSERT INTO chunks(
                    block_id, relpath, kind, text, line_start, line_end,
                    frontmatter, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        ch.block_id,
                        ch.relpath,
                        ch.kind,
                        ch.text,
                        ch.line_start,
                        ch.line_end,
                        json.dumps(ch.frontmatter or {}, default=str),
                        ch.embedding,
                    )
                    for ch in chunks
                ],
            )
        return len(chunks)

    def search(
        self,
        query_embedding: list[float],
        k: int = 20,
        *,
        relpath_prefix: str | None = None,
        kinds: list[str] | None = None,
    ) -> list[ScoredChunk]:
        """Vector similarity search. NULL embeddings are excluded (untranslatable here).

        Filters in v0.1 are intentionally narrow: prefix match on relpath (for "search
        within this folder") and kind allow-list. Frontmatter-aware filters land when a
        real query language is needed.
        """
        if len(query_embedding) != self.embedding_dim:
            raise ValueError(
                f"query embedding has dim {len(query_embedding)}, "
                f"store expects {self.embedding_dim}"
            )
        where: list[str] = ["embedding IS NOT NULL"]
        params: list = [query_embedding]
        if relpath_prefix is not None:
            where.append("relpath LIKE ? || '%'")
            params.append(relpath_prefix)
        if kinds:
            placeholders = ", ".join(["?"] * len(kinds))
            where.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        sql = f"""
            SELECT
                block_id, relpath, kind, text, line_start, line_end, frontmatter,
                array_cosine_similarity(embedding, ?::FLOAT[{self.embedding_dim}]) AS score
            FROM chunks
            WHERE {" AND ".join(where)}
            ORDER BY score DESC
            LIMIT ?
        """
        params.append(k)
        rows = self._con.execute(sql, params).fetchall()
        return [
            ScoredChunk(
                chunk=Chunk(
                    block_id=r[0],
                    relpath=r[1],
                    kind=r[2],
                    text=r[3],
                    line_start=r[4],
                    line_end=r[5],
                    frontmatter=json.loads(r[6]) if r[6] else {},
                    embedding=None,  # not loaded; readers don't need it
                ),
                score=float(r[7]),
            )
            for r in rows
        ]

    def keyword_search(
        self,
        query: str,
        k: int = 20,
        *,
        relpath_prefix: str | None = None,
        kinds: list[str] | None = None,
    ) -> list[ScoredChunk]:
        """Simple local lexical search for identifiers, code terms, and exact phrases.

        This is deliberately not a full search engine. It plugs the main v0.1 vector
        weakness: exact technical tokens (`apiKey`, `Server-Timing`, package names)
        often matter more than semantic proximity.
        """
        query_tokens = _query_tokens(query)
        if not query_tokens:
            return []
        where: list[str] = []
        params: list = []
        if relpath_prefix is not None:
            where.append("relpath LIKE ? || '%'")
            params.append(relpath_prefix)
        if kinds:
            placeholders = ", ".join(["?"] * len(kinds))
            where.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        sql = """
            SELECT block_id, relpath, kind, text, line_start, line_end, frontmatter
            FROM chunks
        """
        if where:
            sql += f" WHERE {' AND '.join(where)}"
        rows = self._con.execute(sql, params).fetchall()
        scored: list[ScoredChunk] = []
        query_phrase = query.strip().lower()
        for row in rows:
            text = row[3]
            score = _lexical_score(query_tokens, query_phrase, text, row[1])
            if score <= 0:
                continue
            scored.append(
                ScoredChunk(
                    chunk=Chunk(
                        block_id=row[0],
                        relpath=row[1],
                        kind=row[2],
                        text=text,
                        line_start=row[4],
                        line_end=row[5],
                        frontmatter=json.loads(row[6]) if row[6] else {},
                        embedding=None,
                    ),
                    score=score,
                )
            )
        return sorted(scored, key=lambda sc: sc.score, reverse=True)[:k]

    def get_embeddings_by_ids(self, block_ids: list[str]) -> dict[str, list[float] | None]:
        """Bulk-fetch raw embeddings by block_id. Used by hybrid retrieval to
        compute cosine similarity for chunks that surfaced via lexical/graph
        ranking (and thus didn't carry a cosine score through `search()`)."""
        if not block_ids:
            return {}
        placeholders = ", ".join(["?"] * len(block_ids))
        rows = self._con.execute(
            f"""
            SELECT block_id, embedding FROM chunks
            WHERE block_id IN ({placeholders})
            """,
            list(block_ids),
        ).fetchall()
        return {r[0]: (list(r[1]) if r[1] is not None else None) for r in rows}

    def get_chunks_by_ids(self, block_ids: list[str]) -> dict[str, Chunk]:
        """Bulk-fetch chunks by block_id. Used by the citation verifier (link + quote
        checks need the full chunk text). Returns a dict keyed on block_id; missing
        ids simply absent. Order of input is irrelevant; callers should look up
        directly by id.
        """
        if not block_ids:
            return {}
        placeholders = ", ".join(["?"] * len(block_ids))
        rows = self._con.execute(
            f"""
            SELECT block_id, relpath, kind, text, line_start, line_end, frontmatter
            FROM chunks WHERE block_id IN ({placeholders})
            """,
            list(block_ids),
        ).fetchall()
        return {
            r[0]: Chunk(
                block_id=r[0],
                relpath=r[1],
                kind=r[2],
                text=r[3],
                line_start=r[4],
                line_end=r[5],
                frontmatter=json.loads(r[6]) if r[6] else {},
                embedding=None,
            )
            for r in rows
        }

    def block_ids_except(self, relpath: str) -> set[str]:
        """All block_ids already in the index that don't belong to `relpath`.

        Used by ingestion to disambiguate cross-file hash collisions (truncated hashes
        collide via birthday paradox once chunk counts exceed a few thousand).
        """
        rows = self._con.execute(
            "SELECT block_id FROM chunks WHERE relpath <> ?", [relpath]
        ).fetchall()
        return {r[0] for r in rows}

    def chunk_count(self) -> int:
        row = self._con.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0]) if row else 0

    def file_count(self) -> int:
        row = self._con.execute("SELECT COUNT(*) FROM files").fetchone()
        return int(row[0]) if row else 0


def _query_tokens(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(query.lower()):
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _lexical_score(query_tokens: list[str], query_phrase: str, text: str, relpath: str) -> float:
    haystack = f"{relpath}\n{text}".lower()
    score = 0.0
    for token in query_tokens:
        count = haystack.count(token)
        if count:
            # Long or hyphenated identifiers carry more signal than common words.
            weight = 1.0 + min(len(token), 16) / 16
            if "-" in token or "_" in token:
                weight += 0.5
            score += min(count, 5) * weight
    if query_phrase and query_phrase in haystack:
        score += 10.0
    return score
