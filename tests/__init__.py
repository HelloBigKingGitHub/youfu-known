"""Tests for the youfu-known backend core.

This package is intentionally synchronous and network-free:
LLM/Embedding clients are mocked, Chroma uses a tmp directory per test,
and the SQLite metadata DB is rebuilt for each test that needs it.
"""