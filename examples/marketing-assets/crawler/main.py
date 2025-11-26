import os
import json
import logging
import asyncio
import redis
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("crawler-service")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_QUEUE = os.getenv("CRAWL_JOB_QUEUE", "crawl_jobs")
RESULT_QUEUE = os.getenv("CRAWL_RESULT_QUEUE", "crawl_results")

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


class CrawlStrategy:
    """Crawl strategies (from universal_crawler.py)"""
    DIRECT = "direct"
    SPA_WITH_DELAY = "spa_with_delay"
    NAVIGATE_FROM_HOME = "navigate_from_home"


def extract_content(crawl_result) -> dict:
    """Extract structured content from crawl result"""
    html = getattr(crawl_result, "html", "") or ""
    soup = BeautifulSoup(html, "html.parser")
    
    # Extract title
    title = ""
    h1_tags = soup.find_all("h1")
    if h1_tags:
        title = h1_tags[0].get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
    if not title and crawl_result.metadata:
        title = crawl_result.metadata.get("title", "")
    
    # Extract description
    description = ""
    if crawl_result.metadata:
        description = crawl_result.metadata.get("description", "") or crawl_result.metadata.get("og:description", "")
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = meta_desc.get("content", "").strip()
    
    # Extract main content
    content = ""
    main_selectors = ["main", "article", "[role='main']", ".main-content", ".content", "#content"]
    for selector in main_selectors:
        main_tag = soup.select_one(selector)
        if main_tag:
            content = main_tag.get_text("\n", strip=True)
            if len(content) > 100:
                break
    
    # Fallback: body content
    if not content or len(content) < 100:
        body = soup.find("body")
        if body:
            for tag in body.find_all(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            content = body.get_text("\n", strip=True)
    
    # Extract headings
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"], limit=10):
        text = tag.get_text(strip=True)
        if text:
            headings.append(f"{tag.name.upper()}: {text}")
    
    return {
        "title": title or "Untitled",
        "description": description,
        "content": content[:10000],  # Limit to 10k chars
        "headings": "\n".join(headings),
        "html_size": len(html),
        "text_size": len(content),
    }


async def crawl_with_strategy(crawler, url: str, strategy: str):
    """Crawl with specific strategy (from universal_crawler.py)"""
    try:
        if strategy == CrawlStrategy.DIRECT:
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                word_count_threshold=0,
                verbose=False,
                page_timeout=30000,
                delay_before_return_html=1.0,
            )
            return await crawler.arun(url=url, config=config)
            
        elif strategy == CrawlStrategy.SPA_WITH_DELAY:
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                word_count_threshold=0,
                verbose=False,
                page_timeout=60000,
                delay_before_return_html=5.0,
            )
            return await crawler.arun(url=url, config=config)
            
        elif strategy == CrawlStrategy.NAVIGATE_FROM_HOME:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            path = url.replace(base_url, '').lstrip('/')
            
            # If already at home, just delay more
            if not path or path == '/':
                config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    word_count_threshold=0,
                    verbose=False,
                    page_timeout=60000,
                    delay_before_return_html=5.0,
                )
                return await crawler.arun(url=base_url, config=config)
            
            # Navigate from home to target page
            # Try multiple selectors to find the link
            js_code = f"""
            await new Promise(resolve => setTimeout(resolve, 3000));
            
            // Try finding link by href
            let link = document.querySelector('a[href="/{path}"]') || 
                       document.querySelector('a[href*="/{path}"]');
            
            if (link) {{
                console.log('Found link, clicking...');
                link.click();
                await new Promise(resolve => setTimeout(resolve, 4000));
            }} else {{
                console.log('Link not found, staying on homepage');
            }}
            """
            
            config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                word_count_threshold=0,
                verbose=False,
                page_timeout=60000,
                delay_before_return_html=6.0,
                js_code=js_code,
            )
            logger.info(f"[crawl_with_strategy] navigate strategy: loading {base_url} then clicking to /{path}")
            return await crawler.arun(url=base_url, config=config)
            
    except Exception as e:
        logger.warning(f"[crawl_with_strategy] strategy={strategy} error={e}")
        return None


async def crawl_job(job):
    """Crawl with fallback strategies (universal_crawler approach)"""
    url = job.get("url")
    job_id = job.get("job_id")
    logger.info(f"[crawl_job] job_id={job_id} url={url}")
    
    result = {
        "job_id": job_id,
        "url": url,
        "status": "error",
        "error": "Unknown error"
    }
    
    try:
        browser_cfg = BrowserConfig(browser_type="chromium", headless=True, verbose=False)
        
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            strategies = [
                CrawlStrategy.DIRECT,
                CrawlStrategy.SPA_WITH_DELAY,
                CrawlStrategy.NAVIGATE_FROM_HOME
            ]
            
            for strategy in strategies:
                logger.info(f"[crawl_job] job_id={job_id} trying strategy={strategy}")
                crawl_result = await crawl_with_strategy(crawler, url, strategy)
                
                if crawl_result and getattr(crawl_result, "success", False):
                    extracted = extract_content(crawl_result)
                    
                    # Quality check 1: detect error pages
                    title_lower = extracted["title"].lower()
                    content_lower = extracted["content"].lower()
                    
                    error_indicators = [
                        'page not found',
                        '404',
                        'not found',
                        'page does not exist',
                        'broken link'
                    ]
                    
                    is_error_page = any(indicator in title_lower or indicator in content_lower[:200] 
                                       for indicator in error_indicators)
                    
                    if is_error_page:
                        logger.warning(f"[crawl_job] job_id={job_id} strategy={strategy} detected error page, trying next")
                        continue
                    
                    # Quality check 2: ensure meaningful content
                    if extracted["text_size"] >= 200:
                        result.update({
                            "status": "success",
                            "strategy": strategy,
                            "title": extracted["title"],
                            "description": extracted["description"],
                            "content": extracted["content"],
                            "headings": extracted["headings"],
                            "html": getattr(crawl_result, "html", "")[:50000],  # Limit HTML size
                        })
                        logger.info(f"[crawl_job] job_id={job_id} success with strategy={strategy}")
                        return result
                    else:
                        logger.warning(f"[crawl_job] job_id={job_id} strategy={strategy} content too short ({extracted['text_size']} chars)")
            
            result["error"] = "All crawl strategies failed"
            
    except Exception as e:
        logger.error(f"[crawl_job] job_id={job_id} error={e}")
        result["error"] = str(e)
    
    return result

def main():
    logger.info(f"[main] Waiting for crawl jobs on Redis list '{JOB_QUEUE}'...")
    while True:
        job_data = redis_client.blpop(JOB_QUEUE, timeout=5)
        if job_data:
            _, job_json = job_data
            job = json.loads(job_json)
            job_id = job.get("job_id")
            logger.info(f"[main] Received job_id={job_id}")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(crawl_job(job))
            redis_client.rpush(RESULT_QUEUE, json.dumps(result))
            logger.info(f"[main] Published result for job_id={job_id}")

if __name__ == "__main__":
    main()
