"""DuckDuckGo search tool with error handling and rate limiting."""

import asyncio
from typing import List, Optional
from datetime import datetime, timedelta
from langchain.tools import Tool
from ddgs import DDGS
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings
from exceptions import SearchError, RateLimitError, TimeoutError
from logger import LoggerMixin
from models import SearchResult


class RateLimiter:
    """Simple rate limiter for search requests."""
    
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.last_request = None
    
    async def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        if self.last_request:
            elapsed = datetime.now() - self.last_request
            if elapsed < timedelta(seconds=self.delay):
                wait_time = self.delay - elapsed.total_seconds()
                await asyncio.sleep(wait_time)
        
        self.last_request = datetime.now()


class DDGSearchTool(LoggerMixin):
    """Enhanced DuckDuckGo search tool with error handling and rate limiting."""
    
    def __init__(self):
        self.rate_limiter = RateLimiter(settings.search_rate_limit_delay)
        self._search_stats = {
            "total_searches": 0,
            "successful_searches": 0,
            "failed_searches": 0
        }
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((SearchError, RateLimitError))
    )
    async def search_async(self, query: str) -> List[SearchResult]:
        """Perform async search with retry logic."""
        await self.rate_limiter.wait_if_needed()
        
        self.logger.info("Starting search", query=query)
        self._search_stats["total_searches"] += 1
        
        try:
            # Run the blocking search in a thread pool
            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(None, self._perform_search, query),
                timeout=settings.search_timeout
            )
            
            self._search_stats["successful_searches"] += 1
            self.logger.info("Search completed", 
                           query=query, 
                           results_count=len(results))
            return results
            
        except asyncio.TimeoutError:
            self._search_stats["failed_searches"] += 1
            raise TimeoutError(f"Search timed out after {settings.search_timeout} seconds")
        except Exception as e:
            self._search_stats["failed_searches"] += 1
            self.logger.error("Search failed", query=query, error=str(e))
            raise SearchError(f"Search failed: {str(e)}")
    
    def _perform_search(self, query: str) -> List[SearchResult]:
        """Perform the actual search operation."""
        try:
            with DDGS(verify=True) as ddgs:
                results = list(ddgs.text(
                    query, 
                    max_results=settings.max_search_results,
                    region='us-en',
                    safesearch='moderate'
                ))
                
                if not results:
                    return []
                
                return [
                    SearchResult(
                        title=r.get('title', 'No title'),
                        body=r.get('body', 'No description'),
                        url=r.get('href', '#')
                    )
                    for r in results
                ]
                
        except Exception as e:
            raise SearchError(f"DuckDuckGo search failed: {str(e)}")
    
    def search_sync(self, query: str) -> str:
        """Synchronous search wrapper for LangChain compatibility."""
        try:
            # Create new event loop if none exists
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the async search
            if loop.is_running():
                # If loop is already running, we need to use a different approach
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.search_async(query))
                    results = future.result(timeout=settings.search_timeout)
            else:
                results = loop.run_until_complete(self.search_async(query))
            
            if not results:
                return "No search results found."
            
            return '\n\n'.join(
                f"Title: {result.title}\n"
                f"Description: {result.body}\n"
                f"URL: {result.url}"
                for result in results
            )
            
        except Exception as e:
            self.logger.error("Sync search failed", query=query, error=str(e))
            return f"Search failed: {str(e)}"
    
    def to_langchain_tool(self) -> Tool:
        """Convert to LangChain tool."""
        return Tool.from_function(
            name="PC_Parts_Search",
            func=self.search_sync,
            description=(
                "Search for PC parts, compatibility information, pricing, and reviews. "
                "Use this tool to find current information about computer hardware, "
                "build recommendations, and technical specifications. "
                "Input should be a specific search query about PC components."
            )
        )
    
    def get_stats(self) -> dict:
        """Get search statistics."""
        return self._search_stats.copy()