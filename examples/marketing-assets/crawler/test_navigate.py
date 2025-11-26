"""Test navigate strategy directly"""
import asyncio
import sys
sys.path.insert(0, '.')
from main import crawl_job

async def test():
    job = {
        "job_id": "test-123",
        "url": "https://trieuvu.netlify.app/lien-he"
    }
    
    result = await crawl_job(job)
    
    print("\n" + "="*70)
    print("RESULT:")
    print("="*70)
    print(f"Status: {result['status']}")
    print(f"Strategy: {result.get('strategy', 'N/A')}")
    print(f"Title: {result.get('title', 'N/A')}")
    print(f"Content length: {len(result.get('content', ''))}")
    if result['status'] == 'error':
        print(f"Error: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(test())
