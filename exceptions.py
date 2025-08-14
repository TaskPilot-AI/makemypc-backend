"""Custom exceptions for the PC Build Assistant application."""


class PCBuildAssistantError(Exception):
    """Base exception for PC Build Assistant errors."""
    
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message)
        self.error_code = error_code


class SearchError(PCBuildAssistantError):
    """Raised when search operations fail."""
    pass


class AgentError(PCBuildAssistantError):
    """Raised when agent operations fail."""
    pass


class ConnectionError(PCBuildAssistantError):
    """Raised when WebSocket connection issues occur."""
    pass


class RateLimitError(SearchError):
    """Raised when rate limits are exceeded."""
    pass


class TimeoutError(PCBuildAssistantError):
    """Raised when operations timeout."""
    pass


class ValidationError(PCBuildAssistantError):
    """Raised when input validation fails."""
    pass