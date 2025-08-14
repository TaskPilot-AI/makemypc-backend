"""Pydantic models for request/response validation."""

from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class MessageType(str, Enum):
    """WebSocket message types."""
    QUERY = "query"
    LOG = "log"
    TOKEN = "token"
    FINAL_OUTPUT = "final_output"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    CONNECTION_STATUS = "connection_status"


class UserQuery(BaseModel):
    """Model for user query input."""
    
    query: str = Field(..., min_length=1, max_length=1000, description="User's PC build query")
    session_id: Optional[str] = Field(None, description="Optional session identifier")
    
    @validator('query')
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()


class WebSocketMessage(BaseModel):
    """Model for WebSocket messages."""
    
    type: MessageType
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None


class SearchResult(BaseModel):
    """Model for search results."""
    
    title: str
    body: str
    url: str
    relevance_score: Optional[float] = None


class AgentResponse(BaseModel):
    """Model for agent responses."""
    
    output: str
    tokens_used: Optional[int] = None
    processing_time: Optional[float] = None
    search_results_count: Optional[int] = None


class ErrorResponse(BaseModel):
    """Model for error responses."""
    
    error_type: str
    message: str
    error_code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)