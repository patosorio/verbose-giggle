import logging


def setup_logging() -> None:
    """Minimal console logging so app-level logger.info()/warning() calls are visible
    in `docker compose logs`. Deliberately basic — no structured JSON, no trace_id yet.
    That's a Phase 4 concern (architecture doc §8) once request-scoped correlation across
    the API/worker boundary actually matters. This just makes INFO-level logs show up.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs the full request URL at INFO, which would include SERPAPI_KEY.
    logging.getLogger("httpx").setLevel(logging.WARNING)
