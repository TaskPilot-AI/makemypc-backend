"""Configuration settings for the PC Build Assistant application."""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Keys
    google_api_key: Optional[str] = None
    
    # Search settings
    search_rate_limit_delay: float = 1.0
    max_search_results: int = 5
    search_timeout: int = 30
    
    # Agent settings
    agent_max_iterations: int = 10
    agent_temperature: float = 0.7
    llm_model: str = "gemini-2.0-flash-exp"
    
    # WebSocket settings
    websocket_timeout: int = 300  # 5 minutes
    max_concurrent_connections: int = 100
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()

# Validate required settings
def validate_settings():
    """Validate that all required settings are present."""
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is required")


# Connection manager settings
class ConnectionConfig:
    """Configuration for WebSocket connections."""
    
    MAX_CONNECTIONS = settings.max_concurrent_connections
    CONNECTION_TIMEOUT = settings.websocket_timeout
    HEARTBEAT_INTERVAL = 30  # seconds