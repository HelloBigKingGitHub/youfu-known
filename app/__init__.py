"""youfu-known application package.

Backend core for the personal knowledge-base RAG system.
Modules:
- app.config   -- load YAML + .env into Pydantic Settings.
- app.llm      -- Chat / Embedding async clients (OpenAI-compatible).
- app.rag      -- document loaders, chunker, embedder, vector store, retriever.
- app.kb       -- Pydantic models, SQLite storage, KB business service.

The FastAPI HTTP layer (app/api/*, app/jobs/*, main.py) is wired up
in a subsequent batch and is not part of this module.
"""

__version__ = "0.1.0"