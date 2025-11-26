# Crawler Service

This subproject is dedicated to running web crawling jobs (SPA/static) independently from the backend, using crawl4ai and Redis queue.

## Purpose
- Decouple crawling logic from backend (FastAPI)
- Run on Linux/WSL for full Playwright/crawl4ai support (or Windows with limitations)
- Communicate with backend via Redis queue

## Setup

### 1. Install Redis
**Using Docker (recommended):**
```bash
docker run -d --name redis-crawler -p 6379:6379 redis:latest
```

**Using WSL/Linux:**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis-server
```

### 2. Install Python dependencies
```bash
cd crawler
pip install -r requirements.txt
```

### 3. Run crawler worker
```bash
python main.py
```

Worker will listen for jobs on Redis list `crawl_jobs` and publish results to `crawl_results`.

## Testing

### Send test job:
```bash
python send_job.py
```

### Get result:
```bash
python get_result.py
```

## Backend Integration

The backend has a `/crawl` endpoint that:
1. Sends job to Redis queue
2. Polls for result (default 30s timeout)
3. Returns crawl result or pending status

### Example usage:
```bash
curl -X POST "http://localhost:8000/crawl?url=https://example.com"
```

## Environment Variables
- `REDIS_URL`: Redis connection string (default: `redis://localhost:6379/0`)
- `CRAWL_JOB_QUEUE`: Job queue name (default: `crawl_jobs`)
- `CRAWL_RESULT_QUEUE`: Result queue name (default: `crawl_results`)

