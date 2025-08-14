"""Main FastAPI application for PC Build Assistant."""

import json
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import ValidationError as PydanticValidationError

from config import settings, validate_settings
from logger import setup_logging, get_logger
from models import UserQuery, ErrorResponse, MessageType
from connection_manager import connection_manager
from agent_service import agent_service
from callback_handler import WebSocketCallbackHandler
from exceptions import (
    PCBuildAssistantError, 
    ValidationError, 
    AgentError, 
    ConnectionError,
    TimeoutError
)


# Setup logging
setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting PC Build Assistant API", version="1.0.0")
    
    try:
        validate_settings()
        logger.info("Configuration validated successfully")
    except Exception as e:
        logger.error("Configuration validation failed", error=str(e))
        raise
    
    # Periodic cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    yield
    
    # Shutdown
    logger.info("Shutting down PC Build Assistant API")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# Initialize FastAPI app
app = FastAPI(
    title="PC Build Assistant",
    description="AI-powered PC build recommendation service",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def periodic_cleanup():
    """Periodic cleanup task for old sessions and connections."""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            
            # Cleanup old agent sessions
            agent_service.cleanup_old_sessions()
            
            logger.info("Periodic cleanup completed")
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic cleanup", error=str(e))


@app.get("/")
async def root():
    """Root endpoint with basic information."""
    return {
        "name": "PC Build Assistant API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "websocket": "/ws",
            "health": "/health",
            "stats": "/stats"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    stats = connection_manager.get_stats()
    memory_stats = agent_service.get_memory_stats()
    
    return {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
        "connections": stats,
        "memory": memory_stats
    }


@app.get("/stats")
async def get_stats():
    """Get application statistics."""
    connection_stats = connection_manager.get_stats()
    memory_stats = agent_service.get_memory_stats()
    search_stats = agent_service.search_tool.get_stats()
    
    return {
        "connections": connection_stats,
        "memory": memory_stats,
        "search": search_stats
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for PC build assistant interactions."""
    session_id = None
    
    try:
        # Accept connection and get session ID
        session_id = await connection_manager.connect(websocket)
        logger.info("WebSocket connection established", session_id=session_id)
        
        # Main message loop
        while True:
            try:
                # Wait for user message
                data = await websocket.receive_text()
                
                # Parse message
                try:
                    message_data = json.loads(data)
                    user_query = UserQuery(**message_data)
                except (json.JSONDecodeError, PydanticValidationError) as e:
                    await connection_manager.send_error(
                        session_id,
                        f"Invalid message format: {str(e)}",
                        "validation_error"
                    )
                    continue
                
                # Check if already processing
                if connection_manager.is_processing(session_id):
                    await connection_manager.send_error(
                        session_id,
                        "Already processing a request. Please wait for completion.",
                        "rate_limit_error"
                    )
                    continue
                
                # Mark as processing
                connection_manager.set_processing(session_id, True)
                
                try:
                    # Process the query
                    await process_user_query(session_id, user_query, websocket)
                    
                except Exception as e:
                    logger.error("Error processing query", 
                               session_id=session_id,
                               error=str(e))
                    
                    # Send error to client
                    error_message = _format_error_message(e)
                    await connection_manager.send_error(
                        session_id,
                        error_message,
                        type(e).__name__
                    )
                
                finally:
                    # Mark as not processing
                    connection_manager.set_processing(session_id, False)
            
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected by client", session_id=session_id)
                break
            
            except ConnectionError:
                logger.warning("Connection error occurred", session_id=session_id)
                break
            
            except Exception as e:
                logger.error("Unexpected error in WebSocket loop", 
                           session_id=session_id,
                           error=str(e))
                
                try:
                    await connection_manager.send_error(
                        session_id,
                        "An unexpected error occurred. Please try again.",
                        "internal_error"
                    )
                except:
                    pass  # Connection might be dead
                break
    
    except Exception as e:
        logger.error("Error in WebSocket endpoint", 
                   session_id=session_id,
                   error=str(e))
    
    finally:
        # Clean up connection
        if session_id:
            await connection_manager.disconnect(session_id)


async def process_user_query(session_id: str, user_query: UserQuery, websocket: WebSocket):
    """Process a user query with the PC build assistant."""
    logger.info("Processing user query", 
               session_id=session_id,
               query_preview=user_query.query[:100])
    
    # Create callback handler
    callback_handler = WebSocketCallbackHandler(websocket, session_id)
    
    # Process with agent service
    response = await agent_service.process_query(
        user_query,
        callback_handler,
        session_id
    )
    
    logger.info("Query processed successfully",
               session_id=session_id,
               processing_time=response.processing_time,
               output_length=len(response.output))


def _format_error_message(error: Exception) -> str:
    """Format error messages for user consumption."""
    if isinstance(error, ValidationError):
        return f"Input validation error: {str(error)}"
    elif isinstance(error, TimeoutError):
        return "Request timed out. Please try again with a more specific query."
    elif isinstance(error, AgentError):
        return "I encountered an issue processing your request. Please try rephrasing your question."
    elif isinstance(error, ConnectionError):
        return "Connection issue occurred. Please refresh and try again."
    else:
        return "An unexpected error occurred. Please try again."


@app.exception_handler(PCBuildAssistantError)
async def pc_build_assistant_exception_handler(request, exc: PCBuildAssistantError):
    """Handle PC Build Assistant specific exceptions."""
    logger.error("PC Build Assistant error", error=str(exc))
    
    return ErrorResponse(
        error_type=type(exc).__name__,
        message=str(exc),
        error_code=getattr(exc, 'error_code', None)
    ).dict()


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Handle general exceptions."""
    logger.error("Unhandled exception", error=str(exc))
    
    return ErrorResponse(
        error_type="InternalServerError",
        message="An internal server error occurred"
    ).dict()


# Development HTML client
# @app.get("/client")
# async def get_client():
#     """Serve a simple HTML client for testing (development only)."""
#     html_content = """
#     <!DOCTYPE html>
#     <html>
#     <head>
#         <title>PC Build Assistant</title>
#         <style>
#             body { font-family: Arial, sans-serif; margin: 40px; }
#             .container { max-width: 800px; margin: 0 auto; }
#             .messages { height: 400px; overflow-y: scroll; border: 1px solid #ccc; padding: 10px; margin: 10px 0; }
#             .message { margin: 5px 0; }
#             .log { color: #666; }
#             .error { color: red; }
#             .final { color: green; font-weight: bold; }
#             input[type="text"] { width: 70%; padding: 5px; }
#             button { padding: 5px 10px; }
#         </style>
#     </head>
#     <body>
#         <div class="container">
#             <h1>PC Build Assistant</h1>
#             <div id="messages" class="messages"></div>
#             <div>
#                 <input type="text" id="queryInput" placeholder="Ask about PC builds..." />
#                 <button onclick="sendQuery()">Send</button>
#                 <button onclick="clearMessages()">Clear</button>
#             </div>
#             <p><strong>Status:</strong> <span id="status">Disconnected</span></p>
#         </div>

#         <script>
#             const messages = document.getElementById('messages');
#             const status = document.getElementById('status');
#             const queryInput = document.getElementById('queryInput');
            
#             let ws = null;
            
#             function connect() {
#                 ws = new WebSocket(`ws://${window.location.host}/ws`);
                
#                 ws.onopen = function() {
#                     status.textContent = 'Connected';
#                     status.style.color = 'green';
#                 };
                
#                 ws.onclose = function() {
#                     status.textContent = 'Disconnected';
#                     status.style.color = 'red';
#                 };
                
#                 ws.onmessage = function(event) {
#                     const data = JSON.parse(event.data);
#                     displayMessage(data);
#                 };
                
#                 ws.onerror = function(error) {
#                     displayMessage({type: 'error', content: 'WebSocket error: ' + error});
#                 };
#             }
            
#             function displayMessage(data) {
#                 const div = document.createElement('div');
#                 div.className = `message ${data.type}`;
                
#                 const timestamp = new Date().toLocaleTimeString();
#                 div.innerHTML = `<small>[${timestamp}] ${data.type}:</small> ${data.content}`;
                
#                 messages.appendChild(div);
#                 messages.scrollTop = messages.scrollHeight;
#             }
            
#             function sendQuery() {
#                 const query = queryInput.value.trim();
#                 if (!query || !ws || ws.readyState !== WebSocket.OPEN) {
#                     return;
#                 }
                
#                 ws.send(JSON.stringify({query: query}));
#                 queryInput.value = '';
                
#                 displayMessage({type: 'user', content: query});
#             }
            
#             function clearMessages() {
#                 messages.innerHTML = '';
#             }
            
#             // Enter key support
#             queryInput.addEventListener('keypress', function(e) {
#                 if (e.key === 'Enter') {
#                     sendQuery();
#                 }
#             });
            
#             // Auto-connect
#             connect();
#         </script>
#     </body>
#     </html>
#     """
#     return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower()
    )
