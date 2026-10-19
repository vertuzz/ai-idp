"""Check worker database readiness without executing jobs or calling providers.

The container runtime separately checks that the worker's main process is alive.
"""

from ai_idp.adapters.outbound.persistence.database import build_engine, build_session_factory
from ai_idp.adapters.outbound.persistence.repositories import SqlAlchemyJobRepository
from ai_idp.settings import get_settings


def main() -> int:
    engine = build_engine(get_settings().database_url)
    try:
        return 0 if SqlAlchemyJobRepository(build_session_factory(engine)).check_health() else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
