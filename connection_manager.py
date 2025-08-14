"""WebSocket connection manager for handling multiple concurrent connections."""

import asyncio
import uuid
from typing import Dict, Set
from datetime import datetime, timedelta
from fastapi import WebSocket, WebSocketDisconnect

from logger import LoggerMixin
from config import ConnectionConfig
from models import WebSocketMessage, MessageType
from exceptions import ConnectionError


class ConnectionManager(LoggerMixin):
    """Manages WebSocket connections with support for multiple concurrent users."""
    
    def __init__(self):
        # Active connections: session_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Connection metadata: session_id -> dict
        self.connection_info: Dict[str, dict] = {}
        # Processing connections: session_id -> bool
        self.processing_connections: Set[str] = set()
        self._heartbeat_task = None
    
    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection and return session ID."""
        await websocket.accept()
        
        # Check connection limit
        if len(self.active_connections) >= ConnectionConfig.MAX_CONNECTIONS:
            await websocket.close(code=1013, reason="Server at capacity")
            raise ConnectionError("Maximum connections exceeded")
        
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        
        # Store connection
        self.active_connections[session_id] = websocket
        self.connection_info[session_id] = {
            "connected_at": datetime.now(),
            "last_activity": datetime.now(),
            "message_count": 0,
            "client_info": websocket.client if websocket.client else None
        }
        
        # Start heartbeat task if it's the first connection
        if len(self.active_connections) == 1:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        self.logger.info("New connection established",
                        session_id=session_id,
                        total_connections=len(self.active_connections))
        
        # Send welcome message
        await self._send_to_connection(
            session_id,
            WebSocketMessage(
                type=MessageType.CONNECTION_STATUS,
                content=f"Connected successfully. Session ID: {session_id}"
            )
        )
        
        return session_id
    
    async def disconnect(self, session_id: str):
        """Disconnect a WebSocket connection."""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            
            try:
                await websocket.close()
            except Exception:
                pass  # Connection might already be closed
            
            # Clean up
            del self.active_connections[session_id]
            del self.connection_info[session_id]
            self.processing_connections.discard(session_id)
            
            self.logger.info("Connection disconnected",
                           session_id=session_id,
                           total_connections=len(self.active_connections))
            
            # Stop heartbeat task if no connections remain
            if len(self.active_connections) == 0 and self._heartbeat_task:
                self._heartbeat_task.cancel()
                self._heartbeat_task = None
    
    async def _send_to_connection(self, session_id: str, message: WebSocketMessage):
        """Send a message to a specific connection."""
        if session_id not in self.active_connections:
            raise ConnectionError(f"Connection {session_id} not found")
        
        websocket = self.active_connections[session_id]
        
        try:
            await websocket.send_text(message.model_dump_json())
            
            # Update connection info
            if session_id in self.connection_info:
                self.connection_info[session_id]["last_activity"] = datetime.now()
                self.connection_info[session_id]["message_count"] += 1
                
        except WebSocketDisconnect:
            self.logger.warning("WebSocket disconnected during send", session_id=session_id)
            await self.disconnect(session_id)
            raise
        except Exception as e:
            self.logger.error("Failed to send message", 
                            session_id=session_id, 
                            error=str(e))
            await self.disconnect(session_id)
            raise ConnectionError(f"Failed to send message: {str(e)}")
    
    async def send_error(self, session_id: str, error_message: str, error_type: str = "general"):
        """Send an error message to a connection."""
        message = WebSocketMessage(
            type=MessageType.ERROR,
            content=error_message,
            metadata={"error_type": error_type}
        )
        await self._send_to_connection(session_id, message)
    
    def is_processing(self, session_id: str) -> bool:
        """Check if a connection is currently processing a request."""
        return session_id in self.processing_connections
    
    def set_processing(self, session_id: str, processing: bool = True):
        """Mark a connection as processing or not processing."""
        if processing:
            self.processing_connections.add(session_id)
        else:
            self.processing_connections.discard(session_id)
    
    def get_connection_info(self, session_id: str) -> dict:
        """Get information about a connection."""
        return self.connection_info.get(session_id, {})
    
    def get_stats(self) -> dict:
        """Get connection statistics."""
        now = datetime.now()
        active_count = len(self.active_connections)
        processing_count = len(self.processing_connections)
        
        # Calculate average connection duration
        durations = [
            (now - info["connected_at"]).total_seconds()
            for info in self.connection_info.values()
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0
        
        return {
            "active_connections": active_count,
            "processing_connections": processing_count,
            "max_connections": ConnectionConfig.MAX_CONNECTIONS,
            "average_connection_duration_seconds": avg_duration,
            "total_messages_sent": sum(
                info["message_count"] for info in self.connection_info.values()
            )
        }
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat messages to maintain connections."""
        while self.active_connections:
            try:
                await asyncio.sleep(ConnectionConfig.HEARTBEAT_INTERVAL)
                
                # Send heartbeat to all connections
                heartbeat_message = WebSocketMessage(
                    type=MessageType.HEARTBEAT,
                    content="ping"
                )
                
                # Create tasks for all heartbeat sends
                tasks = []
                for session_id in list(self.active_connections.keys()):
                    task = asyncio.create_task(
                        self._send_heartbeat_to_connection(session_id, heartbeat_message)
                    )
                    tasks.append(task)
                
                # Wait for all heartbeats to complete
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # Clean up stale connections
                await self._cleanup_stale_connections()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in heartbeat loop", error=str(e))
    
    async def _send_heartbeat_to_connection(self, session_id: str, message: WebSocketMessage):
        """Send heartbeat to a specific connection."""
        try:
            await self._send_to_connection(session_id, message)
        except Exception as e:
            self.logger.warning("Failed to send heartbeat", 
                              session_id=session_id, 
                              error=str(e))
            await self.disconnect(session_id)
    
    async def _cleanup_stale_connections(self):
        """Remove connections that haven't been active recently."""
        now = datetime.now()
        timeout = timedelta(seconds=ConnectionConfig.CONNECTION_TIMEOUT)
        
        stale_connections = []
        for session_id, info in self.connection_info.items():
            if now - info["last_activity"] > timeout:
                stale_connections.append(session_id)
        
        for session_id in stale_connections:
            self.logger.info("Cleaning up stale connection", session_id=session_id)
            await self.disconnect(session_id)


# Global connection manager instance
connection_manager = ConnectionManager()