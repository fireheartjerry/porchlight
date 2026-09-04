"""Porchlight's HTTP surface: FastAPI locally and on Lambda (via Mangum)."""

__all__ = ["create_app"]


def __getattr__(name: str) -> object:
    """Expose :func:`api.main.create_app` without importing FastAPI at package import."""
    if name == "create_app":
        from .main import create_app

        return create_app
    raise AttributeError(name)
