import redis
import json

r = redis.Redis(host='localhost', port=6379, decode_responses=True)
result = r.blpop("crawl_results", timeout=10)
if result:
    _, data = result
    print("Result:", json.loads(data))
else:
    print("No result found.")