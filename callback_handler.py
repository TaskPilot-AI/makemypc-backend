"""WebSocket callback handler for LangChain agent events."""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AgentAction, AgentFinish, LLMResult

from logger import LoggerMixin
from models import WebSocketMessage, MessageType
from exceptions import ConnectionError


class WebSocketCallbackHandler(BaseCallbackHandler, LoggerMixin):
    """Enhanced WebSocket callback handler with error handling and logging."""

    def __init__(self, websocket: WebSocket, session_id: Optional[str] = None):
        super().__init__()
        self.websocket = websocket
        self.session_id = session_id or f"session_{datetime.now().timestamp()}"
        self.message_count = 0
        self.start_time = datetime.now()

    async def _send_message(self, message_type: MessageType, content: str,
                            metadata: Optional[Dict[str, Any]] = None):
        """Send a message through the WebSocket with error handling."""
        try:
            message = WebSocketMessage(
                type=message_type,
                content=content,
                metadata=metadata or {}
            )

            await self.websocket.send_text(message.model_dump_json())
            self.message_count += 1

        except WebSocketDisconnect:
            self.logger.warning("WebSocket disconnected during message send",
                                session_id=self.session_id)
            raise ConnectionError("WebSocket connection lost")
        except Exception as e:
            self.logger.error("Failed to send WebSocket message",
                              session_id=self.session_id,
                              error=str(e),
                              message_type=message_type)
            raise ConnectionError(f"Failed to send message: {str(e)}")

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts running."""
        self.logger.info("LLM started", session_id=self.session_id)
        await self._send_message(
            MessageType.LOG,
            "🤖 AI is thinking about your PC build request...",
            {"event": "llm_start"}
        )

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        """Called when a new token is generated."""
        await self._send_message(MessageType.TOKEN, token)

    async def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Called when LLM finishes running."""
        self.logger.info("LLM finished",
                         session_id=self.session_id,
                         token_count=response.llm_output.get('token_usage', {}).get('total_tokens'))

    async def on_llm_error(self, error: BaseException, **kwargs) -> None:
        """Called when LLM encounters an error."""
        self.logger.error("LLM error",
                          session_id=self.session_id,
                          error=str(error))
        await self._send_message(
            MessageType.ERROR,
            f"AI processing error: {str(error)}",
            {"event": "llm_error"}
        )

    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Called when a tool starts running."""
        tool_name = serialized.get('name', 'Unknown Tool')
        self.logger.info("Tool started",
                         session_id=self.session_id,
                         tool=tool_name,
                         input=input_str)

        await self._send_message(
            MessageType.LOG,
            f"🔍 Searching for: {input_str}",
            {"event": "tool_start", "tool": tool_name}
        )

    async def on_tool_end(self, output: str, **kwargs) -> None:
        """Called when a tool finishes running."""
        self.logger.info("Tool finished", session_id=self.session_id)
        await self._send_message(
            MessageType.LOG,
            "✅ Search completed, analyzing results...",
            {"event": "tool_end"}
        )

    async def on_tool_error(self, error: BaseException, **kwargs) -> None:
        """Called when a tool encounters an error."""
        self.logger.error("Tool error",
                          session_id=self.session_id,
                          error=str(error))
        await self._send_message(
            MessageType.ERROR,
            f"Search error: {str(error)}",
            {"event": "tool_error"}
        )

    async def on_agent_action(self, action: AgentAction, **kwargs) -> None:
        """Called when the agent takes an action."""
        self.logger.info("Agent action",
                         session_id=self.session_id,
                         action=action.tool,
                         input=action.tool_input)

        await self._send_message(
            MessageType.LOG,
            f"🎯 Action: {action.tool}",
            {"event": "agent_action", "tool": action.tool, "input": action.tool_input}
        )

    async def on_agent_finish(self, finish: AgentFinish, **kwargs) -> None:
        """Called when the agent finishes."""
        processing_time = (datetime.now() - self.start_time).total_seconds()

        self.logger.info("Agent finished",
                         session_id=self.session_id,
                         processing_time=processing_time,
                         messages_sent=self.message_count)

        await self._send_message(
            MessageType.FINAL_OUTPUT,
            finish.return_values.get("output", "No output generated"),
            {
                "event": "agent_finish",
                "processing_time": processing_time,
                "messages_sent": self.message_count
            }
        )

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain starts."""
        self.logger.info("Chain started",
                         session_id=self.session_id,
                         inputs=list(inputs.keys()))

    async def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain ends."""
        self.logger.info("Chain ended", session_id=self.session_id)

    async def on_chain_error(self, error: BaseException, **kwargs) -> None:
        """Called when a chain encounters an error."""
        self.logger.error("Chain error",
                          session_id=self.session_id,
                          error=str(error))
        await self._send_message(
            MessageType.ERROR,
            f"Processing error: {str(error)}",
            {"event": "chain_error"}
        )

    async def send_heartbeat(self):
        """Send a heartbeat message to keep the connection alive."""
        await self._send_message(
            MessageType.HEARTBEAT,
            "ping",
            {"timestamp": datetime.now().isoformat()}
        )
