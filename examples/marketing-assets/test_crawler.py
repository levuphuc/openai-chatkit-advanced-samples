#!/usr/bin/env python3
"""
Quick test script to verify crawler setup and functionality.
Run this after setting up Redis and crawler worker.
"""

import time
import requests
import sys
from typing import Dict, Any

BACKEND_URL = "http://127.0.0.1:8003"
TEST_URLS = [
    "https://example.com",  # Simple static site
    "https://trieuvu.netlify.app",  # SPA homepage
    "https://trieuvu.netlify.app/lien-he",  # SPA subpage (requires navigate strategy)
]


def print_section(title: str):
    """Print formatted section header"""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def check_health() -> bool:
    """Check backend and Redis health"""
    print_section("Health Check")
    
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        data = response.json()
        
        print(f"Backend Status: {data.get('status', 'unknown')}")
        print(f"Redis Status: {data.get('redis', 'unknown')}")
        
        if data.get("status") == "healthy" and data.get("redis") == "connected":
            print("✅ All systems operational")
            return True
        else:
            print("❌ System not ready")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to backend")
        print(f"   Make sure backend is running: uvicorn app.main:app --port 8003")
        return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False


def test_crawl(url: str) -> Dict[str, Any]:
    """Test crawling a URL"""
    print(f"\nTesting: {url}")
    print("-" * 60)
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{BACKEND_URL}/crawl",
            params={"url": url},
            timeout=45
        )
        elapsed = time.time() - start_time
        
        data = response.json()
        
        if data.get("status") == "success":
            print(f"✅ Success (took {elapsed:.1f}s)")
            print(f"   Strategy: {data.get('strategy', 'N/A')}")
            print(f"   Title: {data.get('title', 'N/A')[:50]}")
            print(f"   Content length: {len(data.get('content', ''))} chars")
            
            # Check if content is meaningful
            if len(data.get('content', '')) >= 200:
                print(f"   Content quality: ✅ Good")
            else:
                print(f"   Content quality: ⚠️  Short")
                
        elif data.get("status") == "pending":
            print(f"⏳ Pending (timeout after {elapsed:.1f}s)")
            print(f"   Job ID: {data.get('job_id')}")
            print(f"   Crawler may be down or overloaded")
            
        else:
            print(f"❌ Failed")
            print(f"   Error: {data.get('error', 'Unknown')}")
            
        return data
        
    except requests.exceptions.Timeout:
        print(f"❌ Request timeout (>45s)")
        return {"status": "timeout"}
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return {"status": "error", "error": str(e)}


def run_tests():
    """Run all tests"""
    print_section("Crawler Integration Test Suite")
    
    # Step 1: Health check
    if not check_health():
        print("\n❌ Setup incomplete. Please ensure:")
        print("   1. Redis is running (docker run -d -p 6379:6379 redis)")
        print("   2. Backend is running (uvicorn app.main:app --port 8003)")
        print("   3. Crawler worker is running (python crawler/main.py)")
        sys.exit(1)
    
    # Step 2: Test crawls
    print_section("Crawl Tests")
    
    results = []
    for url in TEST_URLS:
        result = test_crawl(url)
        results.append({
            "url": url,
            "status": result.get("status"),
            "strategy": result.get("strategy")
        })
        time.sleep(1)  # Brief delay between tests
    
    # Step 3: Summary
    print_section("Test Summary")
    
    success_count = sum(1 for r in results if r["status"] == "success")
    total_count = len(results)
    
    print(f"Tests passed: {success_count}/{total_count}")
    print()
    
    for r in results:
        status_icon = "✅" if r["status"] == "success" else "❌"
        print(f"{status_icon} {r['url']}")
        if r.get("strategy"):
            print(f"   Strategy: {r['strategy']}")
    
    if success_count == total_count:
        print("\n🎉 All tests passed! Crawler is working correctly.")
        return 0
    elif success_count > 0:
        print(f"\n⚠️  {total_count - success_count} test(s) failed. Check logs for details.")
        return 1
    else:
        print("\n❌ All tests failed. Please check:")
        print("   - Crawler worker logs (crawler/crawler.log)")
        print("   - Redis connection")
        print("   - Network connectivity")
        return 2


if __name__ == "__main__":
    sys.exit(run_tests())
