"""FastAPI entrypoint wiring the ChatKit server and REST endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from chatkit.server import StreamingResult

# Load environment variables from .env file
load_dotenv()
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from .ad_assets import ad_asset_store
from .chat import AdCreativeServer, create_chatkit_server
from .persistence import init_persistence, get_persistence
from .crawl_service import send_crawl_job, get_crawl_result, check_redis_connection

app = FastAPI(title="ChatKit API")

base_dir = Path(__file__).parent.parent
_chatkit_server: AdCreativeServer = create_chatkit_server()
init_persistence(base_dir)  # Initialize SQLite storage

# Mount static files directory for serving images
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# If you want to check what's going on under the hood, set this to DEBUG
logging.basicConfig(level=logging.INFO)


logger = logging.getLogger(__name__)


def get_chatkit_server() -> AdCreativeServer:
    return _chatkit_server


@app.post("/chatkit")
async def chatkit_endpoint(
    request: Request, server: AdCreativeServer = Depends(get_chatkit_server)
) -> Response:
    payload = await request.body()
    result = await server.process(payload, {"request": request})
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return JSONResponse(result)


@app.get("/assets")
async def list_assets() -> dict[str, Any]:
    assets = await ad_asset_store.list_saved()
    return {"assets": [asset.as_dict() for asset in assets]}


@app.get("/history/threads")
async def history_threads(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    persistence = get_persistence()
    return {"threads": persistence.list_threads(limit=limit, offset=offset)}


@app.get("/history/thread/{thread_id}")
async def history_thread(thread_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    persistence = get_persistence()
    return {"messages": persistence.get_thread_messages(thread_id, limit=limit, offset=offset)}


@app.get("/history/assets")
async def history_assets(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    persistence = get_persistence()
    return {"assets": persistence.list_assets(limit=limit, offset=offset)}


@app.post("/history/prune")
async def history_prune(days: int = 30, vacuum: bool = True) -> dict[str, Any]:
    """Delete records older than the given number of days (default 30)."""
    if days < 1:
        return {"error": "days must be >= 1"}
    persistence = get_persistence()
    result = persistence.prune(older_than_days=days, vacuum=vacuum)
    result.update({"retention_days": days})
    return result


@app.get("/images/{filename}")
async def download_image(filename: str) -> FileResponse:
    """Serve image files for download or display."""
    image_path = Path(__file__).parent.parent / "static" / "images" / filename
    if not image_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "Image not found"}
        )
    return FileResponse(
        path=str(image_path),
        media_type="image/png",
        filename=filename
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    redis_ok = check_redis_connection()
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected"
    }


@app.post("/crawl")
async def crawl_url(url: str, timeout: int = 30) -> dict[str, Any]:
    """Submit a crawl job and wait for result.
    
    Args:
        url: URL to crawl
        timeout: Maximum seconds to wait for result (default 30)
        
    Returns:
        Crawl result or pending status
    """
    if not url.startswith(("http://", "https://")):
        return {"status": "error", "error": "URL must start with http:// or https://"}
    
    # Send job to Redis queue
    job_id = send_crawl_job(url)
    
    # Poll for result
    result = get_crawl_result(job_id, timeout=timeout)
    
    if result:
        return result
    
    return {
        "status": "pending",
        "job_id": job_id,
        "message": f"Crawl job submitted but no result after {timeout}s"
    }

