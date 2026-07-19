"""RAG (Retrieval-Augmented Generation) subpackage.

Public entry points used by the service layer:
- :func:`app.rag.loader.load_document`  -- dispatch on extension.
- :class:`app.rag.chunker.RecursiveChunker`
- :class:`app.rag.embedder.Embedder`
- :class:`app.rag.vectorstore.VectorStore`
- :class:`app.rag.retriever.Retriever`
"""