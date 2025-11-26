import redis
import json
import uuid

r = redis.Redis(host='localhost', port=6379, decode_responses=True)
job = {
    "job_id": str(uuid.uuid4()),
    "url": "https://example.com"
}
r.rpush("crawl_jobs", json.dumps(job))
print("Job sent:", job)