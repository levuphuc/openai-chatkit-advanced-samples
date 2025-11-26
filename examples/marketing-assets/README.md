# Marketing Assets Demo

Build campaign briefs and ad concepts with a ChatKit-driven creative workspace. This example pairs a marketing-focused FastAPI backend with a React UI so copy, imagery, and feedback stay in sync while you iterate.

## What's Inside
- FastAPI service that runs an OpenAI Agent tuned for campaign planning and stores approved assets.
- ChatKit Web Component embedded in React with a gallery panel for concepts and generated ad assets.
- Tools for generating copy, capturing image prompts, toggling themes, and persisting finished ads in real time.

## Architecture & Workflow

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                  │
│  ┌──────────────────┐        ┌───────────────────────┐    │
│  │  ChatKit Panel   │        │   Ad Assets Gallery   │    │
│  │  (Chat Interface)│        │   (Saved Concepts)    │    │
│  └────────┬─────────┘        └──────────┬────────────┘    │
│           │                              │                  │
│           │ /chatkit (SSE)              │ /assets (REST)  │
└───────────┼──────────────────────────────┼──────────────────┘
            │                              │
            ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Backend (FastAPI + ChatKit Server)             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    main.py (FastAPI)                 │  │
│  │  • POST /chatkit  - Streaming chat responses         │  │
│  │  • GET  /assets   - List saved ad assets             │  │
│  │  • GET  /health   - Health check                     │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                     │
│  ┌────────────────────▼──────────────────────────────────┐ │
│  │           AdCreativeServer (chat.py)                  │ │
│  │  • ChatKit Server implementation                      │ │
│  │  • OpenAI Agent (GPT-4.1) with Tools                  │ │
│  │  • Streaming via Server-Sent Events                   │ │
│  └────────────────────┬──────────────────────────────────┘ │
│                       │                                     │
│           ┌───────────┴───────────┐                        │
│           │                       │                        │
│  ┌────────▼─────────┐  ┌──────────▼───────────┐          │
│  │  Agent Tools     │  │  Storage Layer       │          │
│  │  ┌─────────────┐ │  │  ┌─────────────────┐ │          │
│  │  │save_ad_asset│ │  │  │  MemoryStore    │ │          │
│  │  ├─────────────┤ │  │  │  (Threads/Chat) │ │          │
│  │  │generate_    │ │  │  ├─────────────────┤ │          │
│  │  │  ad_image   │ │  │  │  AdAssetStore   │ │          │
│  │  ├─────────────┤ │  │  │  (Ad Concepts)  │ │          │
│  │  │switch_theme │ │  │  └─────────────────┘ │          │
│  │  └─────────────┘ │  └──────────────────────┘          │
│  └──────────────────┘                                      │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
         ┌─────────────────────────┐
         │   OpenAI API Services   │
         │  • GPT-4.1 (Chat)       │
         │  • DALL-E (Images)      │
         └─────────────────────────┘
```

### Key Components

#### Backend Modules

1. **`app/main.py`** - FastAPI Entry Point
   - Exposes REST endpoints for chat streaming and asset management
   - Initializes ChatKit server on startup
   - Handles CORS and request routing

2. **`app/chat.py`** - ChatKit Server & Agent Logic
   - **AdCreativeServer**: Custom ChatKit server implementation
   - **OpenAI Agent**: GPT-4.1 agent with marketing-focused instructions
   - **Agent Tools** (4 tools available):
     - `save_ad_asset` - Stores finalized ad concepts (headline, copy, CTA, image prompts)
     - `generate_ad_image` - Creates marketing images using DALL-E
     - `switch_theme` - Toggles UI between light/dark mode
     - `fetch_web_content` - Fetches and analyzes web pages via Redis-backed crawler service
   - Handles streaming responses via Server-Sent Events (SSE)

6. **`app/crawl_service.py`** - Redis Queue Integration
   - Sends crawl jobs to Redis queue (`crawl_jobs`)
   - Polls for results from Redis (`crawl_results`)
   - 30-second timeout for crawl operations
   - Returns structured content (title, description, headings, text)

### Web Crawling Architecture

The system uses a **Redis-based queue architecture** to handle web crawling with SPA support:

```
Backend (fetch_web_content tool)
    │
    │ 1. send_crawl_job(url)
    ▼
Redis Queue (crawl_jobs)
    │
    │ 2. Worker consumes job
    ▼
Crawler Worker (crawler/main.py)
    │
    │ 3. Try strategies sequentially:
    │    - DIRECT: Basic HTTP request
    │    - SPA_WITH_DELAY: Wait for JS rendering
    │    - NAVIGATE_FROM_HOME: Load homepage → click link
    │
    │ 4. Quality checks:
    │    - Detect error pages (404, "not found")
    │    - Ensure min 200 chars content
    │    - Extract structured content
    │
    ▼
Redis Results (crawl_results)
    │
    │ 5. get_crawl_result(job_id)
    ▼
Backend returns to agent
```

**Crawler Features:**
- **Playwright-based**: Full browser automation for JavaScript-heavy sites
- **Fallback strategies**: Automatically tries 3 different approaches
- **Error detection**: Identifies 404 pages and fallbacks to next strategy
- **SPA support**: Can navigate from homepage to subpages for proper routing
- **Quality checks**: Ensures meaningful content (min 200 chars)
- **Structured extraction**: Returns title, description, headings, and clean text
- **Async polling**: Backend waits up to 30s for crawler results

3. **`app/constants.py`** - Configuration
   - Agent instructions and personality
   - Model configuration (GPT-4.1)
   - System prompts for marketing workflow

4. **`app/ad_assets.py`** - Ad Asset Store
   - In-memory storage for ad concepts
   - Data model: `AdAsset` (product, style, tone, pitch, headline, copy, CTA, images)
   - CRUD operations for assets

5. **`app/memory_store.py`** - Thread Store
   - In-memory storage for conversation threads
   - Manages chat history and metadata
   - Implements ChatKit Store interface

### Conversation Workflow

```
1. User Input
   │
   ├─→ User types message in ChatKit panel
   │
   ▼
2. Frontend → Backend
   │
   ├─→ POST /chatkit with thread_id + message
   │
   ▼
3. ChatKit Server Processing
   │
   ├─→ AdCreativeServer.respond() triggered
   ├─→ Load conversation history (last 12 messages)
   ├─→ Create AdAgentContext with thread metadata
   │
   ▼
4. OpenAI Agent Processing
   │
   ├─→ Agent analyzes user intent
   ├─→ Decides which tool(s) to call (if any)
   │   ├─ save_ad_asset: Store complete ad concept
   │   ├─ generate_ad_image: Create image from prompt
   │   ├─ switch_theme: Change UI theme
   │   └─ fetch_web_content: Analyze competitor/reference URLs (via Redis crawler)
   │
   ▼
5. Tool Execution
   │
   ├─→ Tool function executes with context
   ├─→ Results stored in memory/asset store
   ├─→ Client tool calls sent to frontend (if applicable)
   │
   ▼
6. Response Streaming
   │
   ├─→ Agent generates response text
   ├─→ Streams chunks via SSE to frontend
   ├─→ Widgets (images, cards) streamed inline
   │
   ▼
7. Frontend Update
   │
   ├─→ ChatKit panel displays response
   ├─→ Gallery updates with new assets (if saved)
   └─→ UI reflects theme changes (if switched)
```

### Data Flow Examples

#### Example 1: Creating an Ad Concept
```
User: "Create an ad for a coffee shop with cozy vibes"
  ↓
Agent: Asks clarifying questions (target audience, tone, CTA)
  ↓
User: Provides details
  ↓
Agent: Generates headline, copy, CTA, image prompts
  ↓
Agent calls: save_ad_asset(product="Coffee Shop", style="Cozy", ...)
  ↓
AdAssetStore: Saves asset with ID
  ↓
Frontend: Gallery updates with new ad card
```

#### Example 2: Generating Images
```
User: "Generate an image for this ad"
  ↓
Agent calls: generate_ad_image(prompt="Cozy coffee shop interior...")
  ↓
OpenAI DALL-E API: Creates image
  ↓
Agent: Streams image widget to frontend
  ↓
AdAssetStore: Appends image to latest asset
  ↓
Frontend: Displays image inline + updates gallery

#### Example 3: Analyzing Competitor Website
```
User: "Tham khảo https://ketoanquocviet.com để tạo ad cho dịch vụ kế toán"
  ↓
Agent calls: fetch_web_content(url="https://ketoanquocviet.com")
  ↓
HTTP Client: Fetches HTML content (timeout: 30s)
  ↓
BeautifulSoup: Parses and extracts:
  - Title, meta description
  - Main headings (H1, H2)
  - Cleaned text content (max 10KB)
  ↓
Agent: Analyzes messaging style, tone, value propositions
  ↓
Agent: Creates ad concept inspired by competitor insights
  ↓
Agent calls: save_ad_asset(...)
  ↓
Frontend: Gallery updates with new ad
```
```

### Web Content Capability

The backend now includes a real `fetch_web_content` tool that retrieves a page (using `httpx` with redirect + timeout handling) and parses structure (title, meta description, top H1/H2 headings, cleaned body text truncated at 10KB) via `BeautifulSoup` + `lxml`. The agent can incorporate live competitive messaging into generated concepts.

Logging emits a multi-line breakdown so you can inspect scraped sections. If a URL fails (timeout, HTTP error), the tool returns a structured error payload while preserving the chat continuity.

### Persistence Layer

Storage now combines in-memory performance with a lightweight SQLite archive:

| Component | Volatile In-Memory | Durable (SQLite) |
|-----------|--------------------|------------------|
| Chat threads (active) | `MemoryStore` | Messages mirrored to `messages` table |
| Ad assets (current session) | `AdAssetStore` | Saved assets + generated images in `assets` table |

SQLite file: `backend/storage.sqlite` (WAL mode for safe concurrent writes).

#### Tables
- `messages(thread_id, role, content, created_at)` — user & assistant text chunks (stream assembled per message event).
- `assets(asset_id, thread_id, prompt, image_path, metadata, created_at)` — consolidated asset metadata + first image or subsequent generated images with minimal metadata.

#### Endpoints
- `GET /history/threads` — thread summaries (id, counts, first/last timestamps)
- `GET /history/thread/{id}` — ordered messages with pagination
- `GET /history/assets` — asset records with pagination
- `POST /history/prune` — delete rows older than N days (default 30) and optionally VACUUM

#### Pruning
Use `POST /history/prune?days=30` to enforce retention. The API reports deleted counts. For high churn deployments schedule an external cron calling this endpoint.

#### Backup & Migration
- Backup: copy `storage.sqlite` while service runs (WAL ensures consistency) or use `sqlite3 .backup`.
- Migration path: replace persistence implementation with PostgreSQL keeping the same method signatures in `persistence.py`.

#### Notes
- All timestamps stored as ISO 8601 UTC strings (lexically sortable).
- No PII stored; add auth + encryption if expanding user scope.
- Vacuum is optional to avoid IO spikes in busy intervals.

## Prerequisites
- Python 3.11+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or `pip`
- OpenAI API key exported as `OPENAI_API_KEY`
- ChatKit domain key exported as `VITE_CHATKIT_API_DOMAIN_KEY` (any non-empty placeholder during local dev; use a real key in production)

## Quickstart Overview
1. Install dependencies and start the marketing backend.
2. Configure the domain key and launch the React frontend.
3. Generate a few campaign concepts in the demo workflow.

Each step is detailed below.

### 1. Start the FastAPI backend

The backend lives in `examples/marketing-assets/backend` and ships with its own `pyproject.toml`.

```bash
cd examples/marketing-assets/backend
uv sync
export OPENAI_API_KEY="sk-proj-..."
uv run uvicorn app.main:app --reload --port 8003
```

The API exposes ChatKit at `http://127.0.0.1:8003/chatkit` plus REST helpers under `/assets` for storing approved creative. (If your shell cannot resolve local packages, set `PYTHONPATH=$(pwd)` before running Uvicorn.)

### 1.5. Start Redis and Crawler Worker (for web content fetching)

The `fetch_web_content` agent tool requires Redis and a crawler worker to be running.

#### Start Redis with Docker:

```bash
docker run -d --name redis-crawler -p 6379:6379 redis:latest
```

Or if you have Redis installed locally:
```bash
redis-server --port 6379
```

#### Start the Crawler Worker:

```bash
cd examples/marketing-assets/crawler
pip install -r requirements.txt
python main.py
```

The crawler worker will:
- Listen for crawl jobs on Redis queue `crawl_jobs`
- Execute web scraping with Playwright (Chromium)
- Try 3 fallback strategies for SPA sites:
  1. **Direct**: Simple HTTP request
  2. **SPA with delay**: Wait 5s for JavaScript rendering
  3. **Navigate from home**: Load homepage → click link → extract content
- Publish results to Redis queue `crawl_results`

**Testing the crawler directly:**

```bash
# Test endpoint
curl -X POST "http://127.0.0.1:8003/crawl?url=https://example.com"

# Check Redis health
curl http://127.0.0.1:8003/health
```

**Production Notes:**
- Run multiple crawler workers for parallel processing
- Monitor Redis memory usage (`maxmemory-policy allkeys-lru`)
- Configure crawler timeout based on your sites' complexity
- Consider using Redis Sentinel for high availability

### 2. Run the React frontend

```bash
cd examples/marketing-assets/frontend
npm install
npm run dev
```

The dev server runs at `http://127.0.0.1:5173` and proxies `/chatkit` and `/assets` requests back to the API, which is all you need for local iteration.

From the `examples/marketing-assets` directory you can also run `npm start` to launch the backend (`uv sync` + Uvicorn) and frontend together. Ensure `uv` is installed and required environment variables (for example `OPENAI_API_KEY` and the domain key) are exported before using this shortcut.

Regarding the domain public key, you can use any string during local development. However, for production deployments:

1. Host the frontend on infrastructure you control behind a managed domain.
2. Register that domain on the [domain allowlist page](https://platform.openai.com/settings/organization/security/domain-allowlist) and add it to `examples/marketing-assets/frontend/vite.config.ts` under `server.allowedHosts`.
3. Set `VITE_CHATKIT_API_DOMAIN_KEY` to the key returned by the allowlist page and confirm `examples/marketing-assets/frontend/src/lib/config.ts` picks it up (alongside any optional overrides such as `VITE_ASSETS_API_URL`).

If you want to verify remote-access behavior before launch, temporarily expose the app with a tunnel—e.g. `ngrok http 5173` or `cloudflared tunnel --url http://localhost:5173`—and allowlist that hostname first.

## 3. Try the workflow

Open the printed URL and prompt the agent with creative tasks like:

- `Draft a headline, body copy, and image prompt for a productivity app launch.`
- `Refresh our eco-friendly water bottle ad for a fall campaign.`
- `Suggest a carousel concept with three variations and matching calls to action.`

Approved concepts land in the gallery panel, and generated imagery is stored alongside each saved asset.

## Customize the demo

- **Instructions and tools**: Adjust prompt engineering or add/remove tools in `backend/app/constants.py` and `backend/app/chat.py`.
- **Asset persistence**: Swap the in-memory store in `backend/app/ad_assets.py` for your own database layer.
- **Frontend config**: Override endpoints or text in `frontend/src/lib/config.ts`, and tailor the gallery UI in `frontend/src/components`.
- **Styling**: Extend the Tailwind configuration or replace components to match your brand guidelines.
