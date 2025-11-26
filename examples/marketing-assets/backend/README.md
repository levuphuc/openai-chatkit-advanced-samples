# Marketing Assets Backend

Marketing teams can iterate on campaign copy and imagery with this FastAPI service powering the ChatKit marketing demo. It streams agent responses tailored for creative briefs and exposes REST helpers so the frontend can persist approved assets.

## What's Inside

- ChatKit server (`POST /chatkit`) that streams ad concepts, theme toggles, and other agent-driven actions.
- Tools that capture headlines, body copy, calls to action, and image prompts directly from the conversation.
- In-memory store for assets located in `app/ad_assets.py` (swap with your own persistence layer as needed).
- REST endpoint under `/assets` for listing saved creative.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or `pip`
- OpenAI API key exported as `OPENAI_API_KEY`

## Quickstart

```bash
cd examples/marketing-assets/backend
uv sync
export OPENAI_API_KEY="sk-proj-..."
uv run uvicorn app.main:app --reload --port 8003
```

The API listens on `http://127.0.0.1:8003`. If your environment requires it, set `PYTHONPATH=$(pwd)` before running Uvicorn so the local `app` package resolves.

## Technical Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                      │
│                        (main.py)                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Endpoints:                                          │  │
│  │  • POST /chatkit  → ChatKit streaming                │  │
│  │  • GET  /assets   → List saved ad assets             │  │
│  │  • GET  /health   → Health check                     │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │ loads .env via python-dotenv        │
│                       │ OPENAI_API_KEY from environment     │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│               AdCreativeServer (chat.py)                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Inherits: ChatKitServer[dict[str, Any]]            │  │
│  │                                                       │  │
│  │  Key Methods:                                         │  │
│  │  • respond() - Main chat loop                        │  │
│  │  • _to_agent_input() - Convert messages to agent    │  │
│  │  • _add_hidden_item() - Store context                │  │
│  └──────────────────────┬───────────────────────────────┘  │
│                         │                                   │
│  ┌──────────────────────▼───────────────────────────────┐  │
│  │           OpenAI Agent Configuration                 │  │
│  │  • Model: GPT-4.1                                    │  │
│  │  • Name: "Ad Generation Helper"                     │  │
│  │  • Instructions: from constants.INSTRUCTIONS         │  │
│  │  • Tools: [save_ad_asset, generate_ad_image,        │  │
│  │            switch_theme]                             │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │      Agent Context           │
         │   (AdAgentContext)           │
         │  • thread: ThreadMetadata    │
         │  • store: MemoryStore        │
         │  • request_context: dict     │
         └──────────────────────────────┘
```

### Module Breakdown

#### 1. `app/main.py` - FastAPI Entry Point

**Responsibilities**:
- Initialize FastAPI application
- Load environment variables from `.env` using `python-dotenv`
- Create singleton `AdCreativeServer` instance
- Route HTTP requests to appropriate handlers

**Key Functions**:
```python
@app.post("/chatkit")
async def chatkit_endpoint(request, server):
    # Process ChatKit protocol messages
    # Return streaming or JSON response

@app.get("/assets")
async def list_assets():
    # Return all saved ad assets as JSON

@app.get("/health")
async def health_check():
    # Simple health check endpoint
```

**Environment Variables**:
- `OPENAI_API_KEY` - Required for both chat (GPT-4.1) and image generation (DALL-E)

#### 2. `app/chat.py` - ChatKit Server & Agent

**Classes**:

**`AdAgentContext(AgentContext)`**:
- Custom context passed to tools
- Contains: `store`, `thread`, `request_context`

**`AdCreativeServer(ChatKitServer)`**:
- Implements ChatKit protocol
- Manages conversation flow
- Streams responses via SSE

**Agent Tools** (decorated with `@function_tool`):

1. **`save_ad_asset()`**
   - **Purpose**: Store finalized ad concept in gallery
   - **Parameters**: product, style, tone, pitch, headline, primary_text, call_to_action, image_prompts, images
   - **Returns**: asset_id, status, image_count
   - **Side Effects**:
     - Creates/updates AdAsset in ad_asset_store
     - Saves thread metadata with latest_asset_id
     - Streams hidden context item with asset details
     - Sends ClientToolCall to update frontend gallery

2. **`generate_ad_image()`**
   - **Purpose**: Create marketing image using DALL-E
   - **Parameters**: prompt (required), size (default: "1024x1024")
   - **Returns**: status, image_available, asset_id
   - **Process**:
     - Calls OpenAI Images API (gpt-image-1 model)
     - Retries up to MAX_IMAGE_ATTEMPTS (3) times
     - Converts image to base64 data URL
     - Streams Card widget with image preview
     - Appends image to latest asset or pending_images
     - Updates frontend via ClientToolCall

3. **`switch_theme()`**
   - **Purpose**: Toggle UI color scheme
   - **Parameters**: theme ("light" or "dark")
   - **Returns**: theme
   - **Side Effects**: Sends ClientToolCall to frontend

**Response Flow**:
```
respond() called
  ↓
Load thread history (last 50 items, keep last 12 relevant)
  ↓
Convert to agent input format
  ↓
Runner.run_streamed(assistant, input, context)
  ↓
stream_agent_response() yields events:
  • Text chunks
  • Tool calls
  • Widgets
  • Thread item done events
  ↓
Save previous_response_id to thread metadata
```

#### 3. `app/constants.py` - Configuration

**Constants**:
- `INSTRUCTIONS`: Agent system prompt (marketing focus, workflow guidance)
- `MODEL`: "gpt-4.1" (chat model)
- `OPENAI_IMAGE_MODEL`: "gpt-image-1" (DALL-E model)

**Agent Behavior**:
- Ask about product/service first
- Gather: style, tone, pitch
- Generate: headline, copy (45-80 words), CTA, 3+ image prompts
- Auto-call `save_ad_asset` after concept presentation
- Only generate images when explicitly requested
- Decline non-marketing requests politely

#### 4. `app/ad_assets.py` - Ad Asset Storage

**Data Model**:
```python
@dataclass
class AdAsset:
    product: str           # e.g., "Coffee Shop"
    style: str            # e.g., "Cozy", "Modern"
    tone: str             # e.g., "Friendly", "Professional"
    pitch: str            # Value proposition
    headline: str         # Main title
    primary_text: str     # Body copy (45-80 words)
    call_to_action: str   # CTA button text
    image_prompts: List[str]  # DALL-E prompts
    images: List[str]     # base64 data URLs
    id: str               # asset_{uuid}
    created_at: datetime
```

**AdAssetStore Methods**:
- `create()` - Insert or update asset
- `append_image()` - Add generated image to existing asset
- `list_saved()` - Get all assets in creation order
- `get_by_id()` - Retrieve specific asset

**Storage**: In-memory dictionary (`_assets: Dict[str, AdAsset]`)

#### 5. `app/memory_store.py` - Thread Storage

**Implements**: `Store[dict[str, Any]]` from ChatKit

**Data Structure**:
```python
@dataclass
class _ThreadState:
    thread: ThreadMetadata
    items: List[ThreadItem]
```

**Key Methods**:
- `load_thread()` / `save_thread()` - Thread metadata CRUD
- `load_thread_items()` / `add_thread_item()` - Message CRUD
- `load_threads()` - List all threads with pagination

**Storage**: In-memory dictionary (`_threads: Dict[str, _ThreadState]`)

**Limitations**:
- No persistence (data lost on restart)
- No authentication/authorization
- No attachment support

### Conversation State Management

**Thread Metadata** stores:
- `previous_response_id` - For conversation continuity with OpenAI
- `latest_asset_id` - Currently active ad asset
- `pending_images` - Generated images not yet associated with asset

**Flow Example**:
```
1. User starts conversation → New thread created
2. Agent generates ad concept → save_ad_asset() called
3. Thread metadata updated: latest_asset_id = "asset_abc123"
4. User: "Generate an image" → generate_ad_image() called
5. Image created → Appended to asset_abc123
6. User requests changes → save_ad_asset() updates existing asset
7. More images generated → All linked to same asset_abc123
```

### Error Handling

**Image Generation**:
- Retries up to 3 times with exponential backoff
- Raises `RuntimeError` if all attempts fail
- Validates API key presence before attempting

**Chat Processing**:
- Silently ignores non-UserMessageItem inputs
- Returns early for ClientToolCallItem (no response needed)
- Catches exceptions in history loading (continues with empty history)

**Tool Validation**:
- `save_ad_asset()` validates all required fields are non-empty
- `switch_theme()` normalizes theme values, raises `ValueError` for invalid

### Performance Considerations

**Streaming**:
- Uses async generators for response streaming
- Server-Sent Events (SSE) for real-time updates
- Widgets streamed inline (no separate requests)

**History Management**:
- Loads last 50 items, keeps 12 most relevant
- Filters to UserMessage, AssistantMessage, ClientToolCall only
- Prevents unbounded context growth

**Image Storage**:
- Base64 data URLs stored in memory (not scalable)
- Production should use blob storage (S3/Azure) with URLs

### Security Considerations

⚠️ **Current Limitations** (Demo purposes only):
- No authentication/authorization
- OPENAI_API_KEY in environment (secure secret management needed)
- No rate limiting
- No input validation/sanitization
- In-memory storage (no data isolation between users)

**Production Recommendations**:
- Implement user authentication (OAuth2, JWT)
- Use secret management (AWS Secrets Manager, Azure Key Vault)
- Add rate limiting per user/IP
- Validate and sanitize all inputs
- Use database with proper access controls
- Implement CORS properly
- Add request logging and monitoring

## Key Modules
- `app/chat.py` – ChatKit server wiring, agent definition, and tool handlers.
- `app/ad_assets.py` – Data model plus in-memory store for generated ads.
- `app/main.py` – FastAPI entry point exposing ChatKit and REST endpoints.
- `app/constants.py` – Agent instructions and model configuration.
- `app/memory_store.py` – In-memory thread and message storage.

## Next Steps
- Replace the in-memory stores with your database.
- Update guardrails or agent instructions in `app/constants.py`.
- Add new tools for approvals, handoffs, or analytics integrations.
