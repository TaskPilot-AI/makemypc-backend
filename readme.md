# PC Build Assistant API

A professional-grade FastAPI application that provides AI-powered PC build recommendations through WebSocket connections. This service supports multiple concurrent users, includes comprehensive error handling, and provides real-time streaming responses.

## Features

- **Real-time WebSocket Communication**: Stream AI responses in real-time
- **Concurrent User Support**: Handle multiple users simultaneously
- **Comprehensive Error Handling**: Robust error handling with detailed logging
- **Rate Limiting**: Built-in rate limiting and connection management
- **Search Integration**: DuckDuckGo search for current PC part pricing and availability
- **Memory Management**: Conversation memory per session
- **Health Monitoring**: Health checks and statistics endpoints
- **Production Ready**: Docker support with proper logging and monitoring

## Architecture

The application is structured with a modular, professional architecture:

```
├── main.py                 # FastAPI application entry point
├── config.py              # Configuration management
├── models.py              # Pydantic models for validation
├── exceptions.py          # Custom exception classes
├── logger.py              # Structured logging setup
├── connection_manager.py  # WebSocket connection management
├── agent_service.py       # AI agent service
├── callback_handler.py    # WebSocket callback handler
├── search_tool.py         # Search functionality
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker container configuration
├── docker-compose.yml    # Docker Compose setup
└── .env.example         # Environment variables example
```

## Installation

### Prerequisites

- Python 3.11+
- Google AI API key (for Gemini)

### Local Development

1. **Clone and setup**:
   ```bash
   git clone <repository>
   cd pc-build-assistant
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Environment configuration**:
   ```bash
   cp .env.example .env
   # Edit .env and add your GOOGLE_API_KEY
   ```

3. **Run the application**:
   ```bash
   python main.py
   ```

### Docker Deployment

1. **Build and run**:
   ```bash
   docker-compose up --build
   ```

2. **Production deployment**:
   ```bash
   docker-compose --profile production up -d
   ```

## API Endpoints

### REST Endpoints

- `GET /` - API information and available endpoints
- `GET /health` - Health check with system statistics
- `GET /stats` - Detailed application statistics
- `GET /client` - Simple HTML client for testing (development only)

### WebSocket Endpoint

- `WS /ws` - Main WebSocket endpoint for PC build assistance

## WebSocket Communication

### Connection Flow

1. **Connect**: Client connects to `/ws`
2. **Authentication**: Server responds with session ID and connection status
3. **Query**: Client sends JSON message with user query
4. **Streaming**: Server streams real-time updates during processing
5. **Response**: Server sends final recommendation

### Message Format

**Client to Server**:
```json
{
  "query": "I want to build a gaming PC for $1500",
  "session_id": "optional_session_id"
}
```

**Server to Client**:
```json
{
  "type": "log|token|final_output|error|heartbeat|connection_status",
  "content": "message content",
  "timestamp": "2024-01-01T12:00:00Z",
  "metadata": {}
}
```

### Message Types

- `connection_status`: Connection established/status updates
- `log`: Processing status updates
- `token`: Real-time AI response tokens
- `final_output`: Complete recommendation
- `error`: Error messages
- `heartbeat`: Keep-alive messages

## Configuration

All configuration is handled through environment variables:

### Required Settings

- `GOOGLE_API_KEY`: Google AI API key for Gemini

### Optional Settings

- `SEARCH_RATE_LIMIT_DELAY`: Delay between searches (default: 1.0s)
- `MAX_SEARCH_RESULTS`: Maximum search results per query (default: 5)
- `AGENT_MAX_ITERATIONS`: Maximum agent iterations (default: 10)
- `AGENT_TEMPERATURE`: AI response creativity (default: 0.7)
- `LLM_MODEL`: Gemini model to use (default: gemini-2.0-flash-exp)
- `WEBSOCKET_TIMEOUT`: Connection timeout (default: 300s)
- `MAX_CONCURRENT_CONNECTIONS`: Maximum concurrent connections (default: 100)
- `LOG_LEVEL`: Logging level (default: INFO)

## Error Handling

The application includes comprehensive error handling:

- **Input Validation**: Pydantic models validate all inputs
- **Connection Management**: Automatic cleanup of stale connections
- **Rate Limiting**: Prevents overwhelming the search API
- **Timeout Handling**: Prevents long-running requests
- **Graceful Degradation**: Continues functioning when external services fail

## Monitoring and Logging

### Structured Logging

All logs are structured JSON with:
- Timestamp
- Log level
- Component name
- Session ID (when available)