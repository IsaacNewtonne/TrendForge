"""Verified HTTPS configuration for platforms with managed trust roots."""

from __future__ import annotations

from loguru import logger


_INJECTED = False


def configure_system_trust_store() -> bool:
    """Make Python HTTPS clients use the operating-system certificate store."""
    global _INJECTED
    if _INJECTED:
        return True
    try:
        import truststore

        truststore.inject_into_ssl()
        _INJECTED = True
        return True
    except ImportError:
        logger.warning(
            "truststore is not installed; managed Windows HTTPS certificates may fail. "
            "Run: pip install -r requirements.txt"
        )
    except Exception as exc:
        logger.warning(f"Could not activate the operating-system HTTPS trust store: {exc}")
    return False
