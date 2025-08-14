"""PC Build Assistant Agent Service with enhanced error handling."""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

from langchain_google_genai import GoogleGenerativeAI
from langchain.agents import Tool, initialize_agent, AgentType
from langchain.memory import ConversationBufferMemory
from langchain.schema import OutputParserException

from config import settings
from exceptions import AgentError, ValidationError, TimeoutError
from logger import LoggerMixin
from models import UserQuery, AgentResponse
from search_tool import DDGSearchTool
from callback_handler import WebSocketCallbackHandler


class PCBuildAgentService(LoggerMixin):
    """Service for handling PC build assistant agent operations."""

    def __init__(self):
        self.search_tool = DDGSearchTool()
        self._agent_cache: Dict[str, Any] = {}
        self._memory_cache: Dict[str, ConversationBufferMemory] = {}

    def _create_system_prompt(self) -> str:
        """Create the system prompt for the agent."""
        current_year = datetime.now().year
        return f"""You are an expert PC build assistant with extensive knowledge of computer hardware.

            Current year: {current_year}

            Your role:
            - Help users build optimal PC configurations within their budget
            - Provide accurate, up-to-date information about PC components
            - Consider compatibility, performance, and value
            - Explain your recommendations clearly
            - Stay current with market trends and pricing

            Guidelines:
            - Always search for current pricing and availability
            - Consider compatibility between components
            - Suggest alternatives when components are unavailable
            - Explain technical concepts clearly
            - Ask clarifying questions when budget or use case is unclear
            - Prioritize performance per dollar value
            - Mention any potential issues or considerations

            Response format:
            - Be comprehensive but concise
            - Use clear headings and bullet points when appropriate
            - Include estimated pricing when available
            - Mention specific model numbers and brands
            """

    def _get_or_create_memory(self, session_id: str) -> ConversationBufferMemory:
        """Get or create conversation memory for a session."""
        if session_id not in self._memory_cache:
            self._memory_cache[session_id] = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True
            )
        return self._memory_cache[session_id]

    def _create_agent(self, session_id: str, callback_handler: WebSocketCallbackHandler):
        """Create a new agent instance."""
        try:
            # Initialize LLM
            llm = GoogleGenerativeAI(
                model=settings.llm_model,
                temperature=settings.agent_temperature,
                google_api_key=settings.google_api_key
            )

            # Get tools
            tools = [self.search_tool.to_langchain_tool()]

            # Get memory
            memory = self._get_or_create_memory(session_id)

            # Create agent
            agent = initialize_agent(
                tools=tools,
                llm=llm,
                agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                verbose=True,
                memory=memory,
                max_iterations=settings.agent_max_iterations,
                handle_parsing_errors=True,
                agent_kwargs={
                    "system_message": self._create_system_prompt()
                },
                callbacks=[callback_handler]
            )

            return agent

        except Exception as e:
            self.logger.error("Failed to create agent",
                              session_id=session_id,
                              error=str(e))
            raise AgentError(f"Failed to create agent: {str(e)}")

    async def process_query(self,
                            query: UserQuery,
                            callback_handler: WebSocketCallbackHandler,
                            session_id: str) -> AgentResponse:
        """Process a user query and return the agent's response."""
        start_time = datetime.now()

        try:
            # Validate input
            self._validate_query(query)

            # Create agent
            agent = self._create_agent(session_id, callback_handler)

            self.logger.info("Processing query",
                             session_id=session_id,
                             query_length=len(query.query))

            # Execute agent in thread pool to avoid blocking
            loop = asyncio.get_event_loop()

            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._execute_agent,
                        agent,
                        query.query
                    ),
                    timeout=300  # 5 minutes timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    "Agent processing timed out after 5 minutes")

            processing_time = (datetime.now() - start_time).total_seconds()

            # Get search stats
            search_stats = self.search_tool.get_stats()

            response = AgentResponse(
                output=result.get("output", "No response generated"),
                processing_time=processing_time,
                search_results_count=search_stats.get("successful_searches", 0)
            )

            self.logger.info("Query processed successfully",
                             session_id=session_id,
                             processing_time=processing_time,
                             output_length=len(response.output))

            return response

        except Exception as e:
            processing_time = (datetime.now() - start_time).total_seconds()

            self.logger.error("Query processing failed",
                              session_id=session_id,
                              error=str(e),
                              processing_time=processing_time)

            # Re-raise specific exceptions
            if isinstance(e, (ValidationError, AgentError, TimeoutError)):
                raise

            # Wrap other exceptions
            raise AgentError(f"Query processing failed: {str(e)}")

    def _validate_query(self, query: UserQuery):
        """Validate the user query."""
        if not query.query or len(query.query.strip()) < 3:
            raise ValidationError("Query must be at least 3 characters long")

        if len(query.query) > 1000:
            raise ValidationError("Query cannot exceed 1000 characters")

        # Check for potentially problematic content
        forbidden_terms = ["hack", "crack", "piracy", "illegal"]
        query_lower = query.query.lower()

        if any(term in query_lower for term in forbidden_terms):
            raise ValidationError("Query contains inappropriate content")

    def _execute_agent(self, agent, query: str) -> dict:
        """Execute the agent with the given query."""
        try:
            return agent.invoke({"input": query})
        except OutputParserException as e:
            self.logger.warning("Agent parsing error", error=str(e))
            # Return a fallback response
            return {
                "output": "I encountered an issue processing your request. Please try rephrasing your PC build question."
            }
        except Exception as e:
            self.logger.error("Agent execution failed", error=str(e))
            raise AgentError(f"Agent execution failed: {str(e)}")

    def clear_memory(self, session_id: str):
        """Clear conversation memory for a session."""
        if session_id in self._memory_cache:
            del self._memory_cache[session_id]
            self.logger.info("Memory cleared", session_id=session_id)

    def get_memory_stats(self) -> dict:
        """Get memory usage statistics."""
        return {
            "active_sessions": len(self._memory_cache),
            "total_messages": sum(
                len(memory.chat_memory.messages)
                for memory in self._memory_cache.values()
            )
        }

    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Clean up old session memories."""
        # This would require storing session timestamps
        # For now, we'll implement a simple cleanup based on memory size
        if len(self._memory_cache) > 100:  # Arbitrary limit
            # Remove oldest sessions (this is a simplified approach)
            sessions_to_remove = list(self._memory_cache.keys())[:50]
            for session_id in sessions_to_remove:
                del self._memory_cache[session_id]

            self.logger.info("Cleaned up old sessions",
                             removed_count=len(sessions_to_remove))


# Global agent service instance
agent_service = PCBuildAgentService()
