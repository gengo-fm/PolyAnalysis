"""
Batch processor for concurrent wallet analysis.

Features:
- Configurable concurrency
- Rate limiting
- Progress tracking
- Failure handling
- Resume capability
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class BatchConfig:
    """Configuration for batch processing."""
    max_concurrent: int = 20           # Max concurrent requests
    rate_limit_per_minute: int = 50    # API rate limit
    retry_attempts: int = 3            # Max retries for failed items
    retry_delay_seconds: int = 10      # Delay between retries
    progress_interval: int = 10        # Save progress every N items
    verbose: bool = True               # Show progress


@dataclass
class BatchResult:
    """Result of batch processing."""
    total: int
    successful: int
    failed: int
    skipped: int
    duration_seconds: float
    results: list[Any]


class RateLimiter:
    """Simple rate limiter for API requests."""
    
    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._requests: list[float] = []
    
    async def acquire(self):
        """Acquire permission to make a request."""
        now = time.time()
        
        # Remove requests older than 1 minute
        self._requests = [t for t in self._requests if now - t < 60]
        
        if len(self._requests) >= self._max:
            # Wait until we can make another request
            wait_time = 60 - (now - self._requests[0]) + 0.1
            logger.debug(f"Rate limit reached, waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            return await self.acquire()
        
        self._requests.append(now)
    
    @property
    def available(self) -> int:
        """Get available requests in current window."""
        now = time.time()
        self._requests = [t for t in self._requests if now - t < 60]
        return self._max - len(self._requests)


class BatchProcessor:
    """
    Process items in batches with concurrency and rate limiting.
    
    Usage:
        processor = BatchProcessor(config)
        
        results = await processor.run(
            items=addresses,
            process_func=analyze_wallet,
            on_progress=print_progress,
        )
    """
    
    def __init__(self, config: Optional[BatchConfig] = None):
        self._config = config or BatchConfig()
        self._rate_limiter = RateLimiter(self._config.rate_limit_per_minute)
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent)
        self._stats = {
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
        }
    
    async def run(
        self,
        items: list[str],
        process_func: Callable[[str], Any],
        on_progress: Optional[Callable[[dict], None]] = None,
    ) -> BatchResult:
        """
        Run batch processing.
        
        Args:
            items: List of items to process
            process_func: Async function to process each item
            on_progress: Callback for progress updates
            
        Returns:
            BatchResult with statistics and results
        """
        start_time = time.time()
        results = []
        failed_items = []
        
        logger.info(f"Starting batch: {len(items)} items, "
                   f"concurrent={self._config.max_concurrent}")
        
        async def process_one(item: str, attempt: int = 1) -> Optional[Any]:
            async with self._semaphore:
                try:
                    # Rate limiting
                    await self._rate_limiter.acquire()
                    
                    # Process item
                    result = await process_func(item)
                    
                    self._stats["successful"] += 1
                    return result
                    
                except Exception as e:
                    logger.warning(f"Failed {item[:16]}...: {e}")
                    
                    if attempt < self._config.retry_attempts:
                        logger.info(f"Retrying {item[:16]}... (attempt {attempt + 1})")
                        await asyncio.sleep(self._config.retry_attempts)
                        return await process_one(item, attempt + 1)
                    else:
                        self._stats["failed"] += 1
                        failed_items.append((item, str(e)))
                        return None
        
        # Process all items
        tasks = [process_one(item) for item in items]
        
        # Process with progress updates
        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1
            
            # Progress update
            if completed % self._config.progress_interval == 0 or completed == len(items):
                progress = {
                    "completed": completed,
                    "total": len(items),
                    "successful": self._stats["successful"],
                    "failed": self._stats["failed"],
                    "elapsed": time.time() - start_time,
                }
                
                if on_progress:
                    on_progress(progress)
                
                if self._config.verbose:
                    pct = completed * 100 // len(items)
                    eta = (time.time() - start_time) / completed * (len(items) - completed) if completed > 0 else 0
                    logger.info(f"Progress: {completed}/{len(items)} ({pct}%) | "
                               f"✓{self._stats['successful']} ✗{self._stats['failed']} | "
                               f"ETA: {eta/60:.1f}min")
        
        duration = time.time() - start_time
        
        logger.info(f"Batch complete: {self._stats['successful']} successful, "
                   f"{self._stats['failed']} failed, {duration:.1f}s")
        
        return BatchResult(
            total=len(items),
            successful=self._stats["successful"],
            failed=self._stats["failed"],
            skipped=self._stats["skipped"],
            duration_seconds=duration,
            results=results,
        )


class ProgressTracker:
    """Track and persist progress for resume capability."""
    
    def __init__(self, cache_manager):
        self._cache = cache_manager
    
    def init(self, total: int, addresses: list[str]):
        """Initialize progress tracking."""
        self._cache.save_progress({
            "total": total,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": addresses,
            "failed_wallets": {},
            "start_time": datetime.now(timezone.utc).isoformat(),
        })
    
    def mark_success(self, address: str):
        """Mark item as successfully processed."""
        self._cache.mark_completed(address)
    
    def mark_failed(self, address: str, error: str):
        """Mark item as failed."""
        self._cache.mark_failed(address, error)
    
    def get_remaining(self) -> list[str]:
        """Get remaining items to process."""
        progress = self._cache.get_progress()
        return progress.get("remaining", [])
    
    def get_status(self) -> dict:
        """Get current status."""
        return self._cache.get_progress()


# Export
__all__ = [
    "BatchProcessor",
    "BatchConfig", 
    "BatchResult",
    "RateLimiter",
    "ProgressTracker",
]
