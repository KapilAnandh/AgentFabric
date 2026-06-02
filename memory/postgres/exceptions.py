from __future__ import annotations


class DatabaseUnavailableError(Exception):
    """Raised when PostgreSQL database is unreachable or connection fails."""

    def __init__(self, message: str = "Database is unavailable", original_error: Exception | None = None) -> None:
        self.message = message
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message}: {type(self.original_error).__name__}: {self.original_error}"
        return self.message
