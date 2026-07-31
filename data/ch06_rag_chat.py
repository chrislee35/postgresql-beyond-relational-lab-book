#!/usr/bin/env python3.12
"""
Chapter 6 (bonus) — ask a question over an ingested table using Ollama.

Retrieval-Augmented Generation, spelled out: embed the question with the
same model used at ingestion time (all-MiniLM-L6-v2), pull the nearest
chunks from the given table by cosine distance, paste them into a prompt
that instructs the model to answer only from that context, and send the
prompt to a local Ollama server for the actual answer. Retrieval (Postgres
+ pgvector) and generation (Ollama) are two entirely separate systems —
this script is the glue between them, nothing more.

Usage:
    python ch06_rag_chat.py MODEL TABLE "QUESTION" [options]

    python ch06_rag_chat.py llama3.1:8b portsmith_rag "How do I get a business license?"

Options:
    --host        Ollama host (default: localhost)
    --port        Ollama port (default: 11434)
    --top-k       Chunks to retrieve as context (default: 4)
    --dsn         Defaults to "dbname=portsmith"
    --show-context  Print the retrieved chunks before the answer
"""

import argparse
import sys

import psycopg
import requests
from pgvector.psycopg import register_vector
from psycopg import sql
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

PROMPT_TEMPLATE = """You are a help-desk assistant for the city of Portsmith. \
Answer the question using ONLY the context below. If the context doesn't \
contain the answer, say you don't know rather than guessing.

Context:
{context}

Question: {question}

Answer:"""


def retrieve(conn, table: str, qvec, top_k: int) -> list[tuple[str, int, str, float]]:
    if not table.isidentifier():
        sys.exit(f"ERROR: '{table}' isn't a plain identifier.")
    query = sql.SQL("""
        SELECT source, chunk_index, content, embedding <=> %(qvec)s AS distance
        FROM   {table}
        ORDER  BY embedding <=> %(qvec)s
        LIMIT  %(top_k)s
    """).format(table=sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(query, {"qvec": qvec, "top_k": top_k})
        return cur.fetchall()


def ask_ollama(host: str, port: int, model: str, prompt: str) -> str:
    url = f"http://{host}:{port}/api/generate"
    try:
        resp = requests.post(url, json={"model": model, "prompt": prompt, "stream": False}, timeout=120)
    except requests.exceptions.ConnectionError:
        sys.exit(
            f"ERROR: could not reach Ollama at {url}. Is it running? "
            f"(`ollama serve`, or check --host/--port.)"
        )
    if resp.status_code == 404:
        sys.exit(
            f"ERROR: Ollama doesn't have model '{model}' pulled. Run: ollama pull {model}"
        )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("table")
    parser.add_argument("question")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--dsn", default="dbname=portsmith")
    parser.add_argument("--show-context", action="store_true")
    args = parser.parse_args()

    embed_model = SentenceTransformer(MODEL_NAME)
    qvec = embed_model.encode(args.question, normalize_embeddings=True)

    with psycopg.connect(args.dsn) as conn:
        register_vector(conn)
        rows = retrieve(conn, args.table, qvec, args.top_k)

    if not rows:
        sys.exit(f"No rows found in '{args.table}' — did you run ch06_rag_ingest.py?")

    if args.show_context:
        print("--- retrieved context ---")
        for source, chunk_index, content, distance in rows:
            print(f"[{source}#{chunk_index}  dist={distance:.4f}] {content[:100]}...")
        print()

    context = "\n\n".join(f"({source}) {content}" for source, _idx, content, _dist in rows)
    prompt = PROMPT_TEMPLATE.format(context=context, question=args.question)

    answer = ask_ollama(args.host, args.port, args.model, prompt)
    print(answer)


if __name__ == "__main__":
    main()
