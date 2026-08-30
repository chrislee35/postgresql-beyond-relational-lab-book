# The Portsmith Papers

<img src="imgs/portsmith-art.jpg" alt="The harbour of Portsmith Art" width="800"/>

## A Hands-On Tour of PostgreSQL Beyond the Relational Model

---

> *"PostgreSQL is not a database with extensions.  
> It is an extensible data platform that happens to speak SQL."*

---

# About This Book

Most PostgreSQL tutorials end where the interesting work begins.

Once you know how to `SELECT`, `JOIN`, and `GROUP BY`, you have mastered perhaps twenty percent of what PostgreSQL can do. The remaining eighty percent — geospatial queries, semantic search, real-time notifications, fuzzy matching, vector embeddings, distributed coordination, and more — lives in a ecosystem of extensions, index types, and language features that most practitioners never discover.

This book is a guided tour of that other eighty percent.

Each chapter is built around a concrete engineering problem faced by the fictional city of **Portsmith** and its data platform team. We store business directories as semi-structured JSON documents. We route emergency services using geospatial proximity queries. We build a job queue with no message broker. We search municipal records with fuzzy matching that survives typos and OCR errors. We expose the entire platform as a REST API with zero application code.

Every chapter follows the same structure: synthetic data is generated first, giving you a realistic dataset to work against, and then a series of exercises walks you from first principles to production-ready technique. The exercises are written to be done — not just read.

By the end, you will see PostgreSQL not as a place to store rows, but as a programmable data infrastructure layer capable of doing work that most teams reach for separate specialized systems to handle.

**What you will need:**

- A working PostgreSQL 16 installation, plus two disposable Docker containers (PostgreSQL 19 and 18) for the final chapters — setup for all three covered in Appendix A
- Python 3.12+
- A Debian-based Linux environment
- Familiarity with basic SQL (`SELECT`, `INSERT`, `JOIN`, `GROUP BY`)
- Curiosity about what else is in there

---

**Chris Lee**  

*Edition 1.0 — September 12, 2026*
