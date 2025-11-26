# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Overview

Knowledge Assistant is a ChatKit-powered RAG application that grounds AI responses with citations from a vector store. It consists of a FastAPI backend streaming grounded answers from OpenAI Agents and a React frontend with ChatKit Web Component displaying inline citations and document previews.

## Prerequisites

- Python 3.11+
- Node.js 20+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or `pip`
- OpenAI API key exported as `OPENAI_API_KEY`
- Vector store ID exported as `KNOWLEDGE_VECTOR_STORE_ID` (create at [OpenAI Vector Stores](https://platform.openai.com/storage/vector_stores))
- ChatKit domain key exported as `VITE_KNOWLEDGE_CHATKIT_API_DOMAIN_KEY` (use placeholder for local dev, register production domain at [domain allowlist page](https://platform.openai.com/settings/organization/security/domain-allowlist))

## Development Commands

### Full Stack

```powershell
# Start both backend and frontend together (from repository root)
npm start
```

### Backend (FastAPI)

```powershell
# Navigate to backend directory
cd backend

# Install dependencies
uv sync

# Install dev dependencies (includes ruff and mypy)
uv sync --extra dev

# Run the API server (default port 8002)
uv run uvicorn app.main:app --reload --port 8002

# Lint with ruff
uv run ruff check .

# Format with ruff
uv run ruff format .

# Type check with mypy
uv run mypy app
```

### Frontend (React + Vite)

```powershell
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Run dev server (default port 5172)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint
npm run lint
```

### Testing

The codebase currently includes test utilities (`useStableOptions.test.ts`) but does not have a comprehensive test suite. Use `npm test` (if configured) or Vitest directly for frontend tests.

## Architecture

### Backend Structure

**FastAPI Service** (`backend/app/main.py`):
- Serves ChatKit endpoint at `/knowledge/chatkit` (POST)
- Exposes REST API for documents (`/knowledge/documents`), document files (`/knowledge/documents/{id}/file`), and citations (`/knowledge/threads/{thread_id}/citations`)
- Uses `KnowledgeAssistantServer` which extends `ChatKitServer` to handle streaming agent responses

**Agent System** (`backend/app/assistant_agent.py`):
- **Multi-agent workflow**: Classifier → specialized agents (Buddhism, Greet, Refuse)
- **Classifier agent**: Routes questions to GREET, SENSITIVE, BUDDHISM, or OTHER categories
- **Buddhism agent**: Answers Buddhist doctrine questions using File Search tool against vector store
- **Query rewrite agent**: Reformulates queries for better retrieval
- **Refuse/Greet agents**: Handle out-of-scope or greeting interactions
- All agents use `gpt-4o-mini` with different temperature settings per use case

**Document Management** (`backend/app/documents.py`):
- Hardcoded manifest (`DOCUMENTS` tuple) defines available documents with metadata
- Multiple lookup dictionaries (by ID, filename, stem, slug) for flexible citation resolution
- Documents stored in `backend/app/data/` directory (PDFs and HTML files)

**Storage** (`backend/app/memory_store.py`):
- In-memory implementation of ChatKit `Store` interface
- Stores threads, thread items, and metadata
- Does NOT persist attachments (raises NotImplementedError for security)
- Thread and item pagination supported

### Frontend Structure

**Main Components**:
- `Home.tsx`: Top-level layout coordinating ChatKit panel and document panel
- `ChatKitPanel.tsx`: Wraps ChatKit React component, handles thread lifecycle
- `KnowledgeDocumentsPanel.tsx`: Grid display of documents with citation highlighting
- `DocumentPreviewModal.tsx`: Full-screen preview of selected documents

**React Hooks**:
- `useKnowledgeDocuments.ts`: Fetches document metadata from `/knowledge/documents`
- `useThreadCitations.ts`: Polls `/knowledge/threads/{id}/citations` to highlight cited documents
- `useColorScheme.ts`: Manages dark/light theme persistence
- `useChatKit.ts` / `useStableOptions.ts`: Custom ChatKit integration utilities

**Configuration** (`frontend/src/lib/config.ts`):
- All API endpoints, greeting text, and starter prompts configurable via `VITE_KNOWLEDGE_*` environment variables
- Defaults proxy to `http://127.0.0.1:8002` in development (via Vite proxy in `vite.config.ts`)

### Data Flow

1. **User query** → ChatKit component → POST `/knowledge/chatkit`
2. **Backend** receives query → `KnowledgeAssistantServer.respond()` creates `AgentContext`
3. **Agent workflow** executes (classify → route to specialist agent)
4. **Buddhism agent** (if applicable) calls File Search tool against OpenAI vector store
5. **Streaming response** with annotations returned via Server-Sent Events
6. **Frontend** parses citations from annotations → displays inline citation numbers
7. **Citation fetch** polls `/knowledge/threads/{thread_id}/citations` → highlights cited documents in grid
8. **Document preview** fetches file from `/knowledge/documents/{id}/file` on user click

### Citation Resolution Logic

The backend (`main.py`) attempts to match OpenAI File Search annotations to local documents using:
1. Exact filename match (case-insensitive)
2. Stem match (filename without extension)
3. Slug match (alphanumeric-only version of filename, title, or description)
4. Regex extraction from assistant message text (fallback for inline filenames like `01_fomc_statement_2025-09-17.html`)

This multi-strategy approach ensures citations display correctly even when vector store filenames don't exactly match the document manifest.

### Key Files to Modify

**To change knowledge base**:
- Update `KNOWLEDGE_VECTOR_STORE_ID` environment variable
- Modify `backend/app/documents.py` manifest to match new document set
- Replace files in `backend/app/data/` directory

**To customize agents**:
- Edit `backend/app/assistant_agent.py` (agent instructions, model settings, workflow logic)
- Adjust temperature/top_p in `ModelSettings` for different response styles

**To adjust frontend behavior**:
- Modify `frontend/src/lib/config.ts` for text/prompts/URLs
- Update `frontend/vite.config.ts` for allowed hosts or proxy settings

**To replace storage**:
- Implement custom `Store[dict[str, Any]]` subclass in place of `MemoryStore`
- Required for production deployments with authentication/persistence

## Environment Variables

### Backend
- `OPENAI_API_KEY` (required): OpenAI API key
- `KNOWLEDGE_VECTOR_STORE_ID` (required): Vector store ID from OpenAI platform

### Frontend
- `VITE_KNOWLEDGE_CHATKIT_API_DOMAIN_KEY` (required for production): Domain key from allowlist
- `VITE_KNOWLEDGE_API_BASE`: Override default `/knowledge` base path
- `VITE_KNOWLEDGE_CHATKIT_API_URL`: Override ChatKit endpoint
- `VITE_KNOWLEDGE_DOCUMENTS_URL`: Override documents list endpoint
- `VITE_KNOWLEDGE_DOCUMENT_FILE_BASE_URL`: Override document file base URL
- `VITE_KNOWLEDGE_THREADS_BASE_URL`: Override threads base URL
- `VITE_KNOWLEDGE_GREETING`: Override greeting text
- `VITE_KNOWLEDGE_COMPOSER_PLACEHOLDER`: Override input placeholder text
- `BACKEND_URL`: Override backend target for Vite proxy (default `http://127.0.0.1:8002`)

## Notes

- **Agent workflow is hardcoded Vietnamese**: The classifier and Buddhist agent instructions are in Vietnamese and specific to Buddhist doctrine queries. Modify `assistant_agent.py` for different domains.
- **No authentication**: `MemoryStore` and CORS middleware allow all origins. Implement proper auth before production deployment.
- **Ruff configuration**: Line length set to 100 in `backend/pyproject.toml`, extends select includes import sorting (`I`).
- **Vector store must be pre-populated**: Upload documents to OpenAI vector store via platform UI before running the app.
- **Citations depend on filename matching**: Ensure vector store filenames align with `documents.py` manifest for accurate citation display.
