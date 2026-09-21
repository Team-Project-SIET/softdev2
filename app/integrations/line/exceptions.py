class LineIntegrationError(Exception):
    """Base error for failures that can be shown safely in the TUI."""


class MissingLineTokenError(LineIntegrationError):
    """The LINE channel access token was not configured."""


class InvalidLineReceiverError(LineIntegrationError):
    """The receiver is not a valid LINE Messaging API user ID."""


class LineApiError(LineIntegrationError):
    """LINE returned an unsuccessful API response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LineNetworkError(LineIntegrationError):
    """The LINE API could not be reached."""


class LineMessageTooLongError(LineIntegrationError):
    """The route cannot fit in one plain-text LINE message."""


class RouteDriverNotAssignedError(LineIntegrationError):
    """The saved route has no assigned driver."""


class MissingLineUserIdError(LineIntegrationError):
    """The assigned driver has no LINE Messaging API user ID."""
