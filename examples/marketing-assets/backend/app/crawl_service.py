"""Redis-based crawl job service for sending crawl requests and retrieving results."""

import json
import logging
import os
import time
from typing import Any
from uuid import uuid4

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_QUEUE = os.getenv("CRAWL_JOB_QUEUE", "crawl_jobs")
RESULT_QUEUE = os.getenv("CRAWL_RESULT_QUEUE", "crawl_results")

# Initialize Redis client
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def send_crawl_job(url: str) -> str:
    """Send a crawl job to Redis queue and return job_id.
    
    Args:
        url: URL to crawl
        
    Returns:
        job_id: Unique job identifier
    """
    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "url": url,
    }
    redis_client.rpush(JOB_QUEUE, json.dumps(job))
    logger.info(f"[crawl_service] sent job_id={job_id} url={url}")
    return job_id


def get_crawl_result(job_id: str, timeout: int = 30) -> dict[str, Any] | None:
    """Poll Redis for crawl result by job_id.
    
    Args:
        job_id: Job identifier
        timeout: Maximum seconds to wait for result
        
    Returns:
        Result dict if found, None otherwise
    """
    start = time.time()
    logger.info(f"[crawl_service] polling for job_id={job_id} timeout={timeout}s")
    
    while time.time() - start < timeout:
        # Check all results in queue
        results = redis_client.lrange(RESULT_QUEUE, 0, -1)
        for raw in results:
            try:
                result = json.loads(raw)
                if result.get("job_id") == job_id:
                    # Remove this result from queue
                    redis_client.lrem(RESULT_QUEUE, 1, raw)
                    logger.info(f"[crawl_service] found result for job_id={job_id}")
                    return result
            except json.JSONDecodeError:
                logger.warning(f"[crawl_service] invalid json in result queue: {raw}")
                continue
        
        time.sleep(1)
    
    logger.warning(f"[crawl_service] timeout waiting for job_id={job_id}")
    return None


def check_redis_connection() -> bool:
    """Check if Redis is accessible.
    
    Returns:
        True if Redis is reachable, False otherwise
    """
    try:
        redis_client.ping()
        return True
    except Exception as e:
        logger.error(f"[crawl_service] Redis connection failed: {e}")
        return False
