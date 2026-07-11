class GatewayError(Exception):
    """Structured, serialization-safe error raised by Gateway primitives."""

    code: str
    message: str
    retryable: bool
    details: dict[str, object]

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details.copy(),
        }
