"""Integration tests for the youfu-known backend.

Unlike the unit tests under ``tests/test_*.py`` (which mock
``AuthService`` and exercise the HTTP layer in isolation), the tests in
this package boot the **real** ``main:create_app()`` factory with a real
SQLite metadata DB and a real Chroma collection directory -- they spin
up the full lifespan and verify the service graph end-to-end.

Why a separate package:

* Sharing ``tests/conftest.py`` would re-apply the unit-test fixtures
  (per-test ``Settings`` + transient Chroma) that are tuned for the
  single-process-per-test assumption. An integration test wants to
  bring the app up **twice** on the same on-disk DB to catch the
  ``P5b`` / ``P8a`` lifespan idempotent failures that plagued the
  32-commit DDD run, which the unit suite cannot reproduce.
* Keeping the integration suite isolated also means a future
  ``@pytest.mark.integration`` marker can be added without touching
  the rest of the suite.
"""