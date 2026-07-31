#!/usr/bin/env python3.12
"""
Chapter 6 (bonus) — chunk and embed a directory of documents for RAG.

Splits every .txt/.md file in a directory into overlapping word-count
chunks, embeds each chunk with all-MiniLM-L6-v2 (the same model used
throughout this chapter, and it must stay the same model used at query
time in ch06_rag_chat.py — mixing embedding models makes distances
meaningless), and loads the chunks into a table this script creates.

Unlike ch06_embed_documents.py, which embeds three already-short columns
of an existing table whole, this script is the more typical RAG ingestion
shape: arbitrary-length source documents, chunked because a whole document
is usually too large (and too topically mixed) to embed as one vector and
still get a useful similarity match against a narrow question.

Usage:
    python ch06_rag_ingest.py DOCS_DIR --table TABLE [options]

    python ch06_rag_ingest.py data/rag_docs --table portsmith_rag

Options:
    --dsn            Defaults to "dbname=portsmith"
    --chunk-size     Words per chunk (default 180)
    --chunk-overlap  Words shared between consecutive chunks (default 40)
    --recreate       Drop and recreate the table instead of appending to it
"""

import argparse
import re
import sys
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"


def chunk_words(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    if overlap >= chunk_size:
        raise ValueError("--chunk-overlap must be smaller than --chunk-size")
    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(words), step):
        chunk = words[start : start + chunk_size]
        if not chunk:
            break
        chunks.append(" ".join(chunk))
        if start + chunk_size >= len(words):
            break
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docs_dir", type=Path)
    parser.add_argument("--table", required=True)
    parser.add_argument("--dsn", default="dbname=portsmith")
    parser.add_argument("--chunk-size", type=int, default=180)
    parser.add_argument("--chunk-overlap", type=int, default=40)
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z_][a-z0-9_]*", args.table):
        sys.exit(
            f"ERROR: --table '{args.table}' isn't a plain lowercase identifier "
            "(letters, digits, underscores only, not starting with a digit)."
        )
    table = sql.Identifier(args.table)

    paths = sorted(list(args.docs_dir.glob("*.txt")) + list(args.docs_dir.glob("*.md")))
    if not paths:
        sys.exit(f"ERROR: no .txt or .md files found in {args.docs_dir}")

    print(f"Connecting to: {args.dsn}")
    with psycopg.connect(args.dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            if args.recreate:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
            cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    id          SERIAL PRIMARY KEY,
                    source      TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content     TEXT NOT NULL,
                    embedding   vector(384) NOT NULL
                )
            """).format(table))
        conn.commit()

        print(f"Loading {MODEL_NAME} …")
        model = SentenceTransformer(MODEL_NAME)

        total_chunks = 0
        for path in paths:
            text = path.read_text()
            chunks = chunk_words(text, args.chunk_size, args.chunk_overlap)
            embeddings = model.encode(chunks, show_progress_bar=False, normalize_embeddings=True)

            insert_stmt = sql.SQL("""
                INSERT INTO {} (source, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s)
            """).format(table)
            with conn.cursor() as cur:
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    cur.execute(insert_stmt, (path.name, i, chunk, embedding))
            conn.commit()
            print(f"  {path.name}: {len(chunks)} chunks")
            total_chunks += len(chunks)

        with conn.cursor() as cur:
            cur.execute(sql.SQL("""
                CREATE INDEX IF NOT EXISTS {}
                    ON {} USING hnsw (embedding vector_cosine_ops)
            """).format(sql.Identifier(f"idx_{args.table}_embedding"), table))
        conn.commit()

        print(f"Done — {total_chunks} chunks from {len(paths)} files loaded into '{args.table}'.")


if __name__ == "__main__":
    main()
