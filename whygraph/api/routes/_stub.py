from fastapi import HTTPException


def not_implemented(feature: str) -> HTTPException:
    """Placeholder for routes owned by a feature branch (see docs/features.md)."""
    return HTTPException(status_code=501, detail=f"Not implemented yet: {feature}")
