from fastapi.responses import JSONResponse


class AppError(Exception):
    """Every expected failure in the app raises one of these."""

    def __init__(self, code, message, status_code=400, details=None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_body(code, message, details):
    # The spec wants every error to look the same, so the frontend has
    # one shape to read no matter which route failed.
    return {"error": {"code": code, "message": message, "details": details}}


def error_response(code, message, status_code=400, details=None):
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, details or {}),
    )