from __future__ import annotations

import mimetypes
import re
import time
from itertools import chain
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from agents import Agent, RunConfig, Runner
from agents.model_settings import ModelSettings
from chatkit.agents import AgentContext, stream_agent_response
from chatkit.server import ChatKitServer, StreamingResult
from chatkit.types import (
    Annotation,
    AssistantMessageContent,
    AssistantMessageItem,
    Attachment,
    ClientToolCallItem,
    ThreadItem,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
)
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from openai.types.responses import ResponseInputContentParam
from starlette.responses import JSONResponse

from .assistant_agent import assistant_agent, get_agent_for_message
from .documents import (
    DOCUMENTS,
    DOCUMENTS_BY_FILENAME,
    DOCUMENTS_BY_ID,
    DOCUMENTS_BY_SLUG,
    DOCUMENTS_BY_STEM,
    DocumentMetadata,
    as_dicts,
)
from .memory_store import MemoryStore


def _normalise_filename(value: str) -> str:
    return Path(value).name.strip().lower()


def _slug(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _user_message_text(item: UserMessageItem) -> str:
    parts: list[str] = []
    for part in item.content:
        text = getattr(part, "text", None)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _resolve_document(annotation: Annotation) -> DocumentMetadata | None:
    source = getattr(annotation, "source", None)
    if not source or getattr(source, "type", None) != "file":
        return None

    filename = getattr(source, "filename", None)
    if filename:
        normalised = _normalise_filename(filename)
        match = DOCUMENTS_BY_FILENAME.get(normalised)
        if match:
            return match
        stem_match = DOCUMENTS_BY_STEM.get(Path(normalised).stem.lower())
        if stem_match:
            return stem_match
        slug_match = DOCUMENTS_BY_SLUG.get(_slug(normalised))
        if slug_match:
            return slug_match

    title = getattr(source, "title", None)
    if title:
        candidate = DOCUMENTS_BY_SLUG.get(_slug(title))
        if candidate:
            return candidate

    description = getattr(source, "description", None)
    if description:
        candidate = DOCUMENTS_BY_SLUG.get(_slug(description))
        if candidate:
            return candidate

    return None


_FILENAME_REGEX = re.compile(r"(0[1-8]_[a-z0-9_\-]+\.(?:pdf|html))", re.IGNORECASE)


def _documents_from_text(text: str) -> Iterable[DocumentMetadata]:
    if not text:
        return []
    matches = {match.lower() for match in _FILENAME_REGEX.findall(text)}
    if not matches:
        return []
    results: list[DocumentMetadata] = []
    for filename in matches:
        doc = DOCUMENTS_BY_FILENAME.get(filename)
        if doc and doc not in results:
            results.append(doc)
    return results


def _is_tool_completion_item(item: Any) -> bool:
    return isinstance(item, ClientToolCallItem)


class KnowledgeAssistantServer(ChatKitServer[dict[str, Any]]):
    def __init__(self, agent: Agent[AgentContext]) -> None:
        self.store = MemoryStore()
        super().__init__(self.store)
        self.assistant = agent

    async def respond(
        self,
        thread: ThreadMetadata,
        item: ThreadItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        if item is None:
            return

        if _is_tool_completion_item(item):
            return

        if not isinstance(item, UserMessageItem):
            return

        message_text = _user_message_text(item)
        if not message_text:
            return

        # Track start time for timing metadata
        start_time = time.time()
        first_token_time = None
        first_token_recorded = False

        # Use the workflow: classify the message and get the appropriate agent
        try:
            selected_agent = await get_agent_for_message(message_text)
        except Exception as e:
            # Fallback to default agent if classification fails
            import traceback
            print(f"Classification failed: {e}")
            traceback.print_exc()
            selected_agent = self.assistant

        agent_context = AgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )
        
        # Run the selected agent with streaming support
        result = Runner.run_streamed(
            selected_agent,
            message_text,
            context=agent_context,
            run_config=RunConfig(model_settings=ModelSettings(temperature=0.3)),
        )

        # Stream events and track completion time
        async for event in stream_agent_response(agent_context, result):
            # Record first token time (when first content delta arrives)
            if not first_token_recorded and event.type == "thread.item.updated":
                update = getattr(event, "update", None)
                if update and getattr(update, "type", None) == "assistant_message.content_part.text_delta":
                    first_token_time = time.time() - start_time
                    first_token_recorded = True
                    print(f"[Timing] First token: {first_token_time:.3f}s")
            
            # Add timing metadata to the completed message
            if event.type == "thread.item.done":
                item_data = getattr(event, "item", None)
                if item_data and isinstance(item_data, AssistantMessageItem):
                    completion_time = time.time() - start_time
                    ttft = first_token_time or 0
                    
                    # Add timing as metadata
                    if hasattr(item_data, "metadata"):
                        if item_data.metadata is None:
                            item_data.metadata = {}
                        item_data.metadata["ttft"] = round(ttft, 3)
                        item_data.metadata["completion_time"] = round(completion_time, 3)
                    
                    print(f"[Timing] Message completed - TTFT: {ttft:.3f}s, Total: {completion_time:.3f}s")
            
            yield event

    async def to_message_content(self, input: Attachment) -> ResponseInputContentParam:
        raise RuntimeError("File attachments are not supported in this demo.")

    async def latest_citations(
        self, thread_id: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        items = await self.store.load_thread_items(
            thread_id,
            after=None,
            limit=50,
            order="desc",
            context=context,
        )

        for item in items.data:
            if isinstance(item, AssistantMessageItem):
                citations = list(self._extract_citations(item))
                if citations:
                    return citations
        return []

    def _extract_citations(self, item: AssistantMessageItem) -> Iterable[dict[str, Any]]:
        found = False
        for content in item.content:
            if not isinstance(content, AssistantMessageContent):
                continue
            for annotation in content.annotations:
                document = _resolve_document(annotation)
                if not document:
                    continue
                found = True
                yield {
                    "document_id": document.id,
                    "filename": document.filename,
                    "title": document.title,
                    "description": document.description,
                    "annotation_index": annotation.index,
                }
        if not found:
            texts = chain.from_iterable(
                content.text.splitlines()
                for content in item.content
                if isinstance(content, AssistantMessageContent)
            )
            for line in texts:
                for document in _documents_from_text(line):
                    yield {
                        "document_id": document.id,
                        "filename": document.filename,
                        "title": document.title,
                        "description": document.description,
                        "annotation_index": None,
                    }


knowledge_server = KnowledgeAssistantServer(agent=assistant_agent)

app = FastAPI(title="ChatKit Knowledge Assistant API")

_DATA_DIR = Path(__file__).parent / "data"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_server() -> KnowledgeAssistantServer:
    return knowledge_server


@app.post("/knowledge/chatkit")
async def chatkit_endpoint(
    request: Request, server: KnowledgeAssistantServer = Depends(get_server)
) -> Response:
    payload = await request.body()
    result = await server.process(payload, {"request": request})
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return JSONResponse(result)


@app.get("/knowledge/documents")
async def list_documents() -> dict[str, Any]:
    return {"documents": as_dicts(DOCUMENTS)}


@app.get("/knowledge/documents/{document_id}/file")
async def document_file(document_id: str) -> FileResponse:
    document = DOCUMENTS_BY_ID.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = _DATA_DIR / document.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not available")

    media_type, _ = mimetypes.guess_type(str(file_path))
    headers = {"Content-Disposition": f'inline; filename="{document.filename}"'}
    return FileResponse(
        file_path,
        media_type=media_type or "application/octet-stream",
        headers=headers,
    )


@app.get("/knowledge/threads/{thread_id}/citations")
async def thread_citations(
    thread_id: str,
    request: Request,
    server: KnowledgeAssistantServer = Depends(get_server),
) -> dict[str, Any]:
    context = {"request": request}
    try:
        citations = await server.latest_citations(thread_id, context=context)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    document_ids = sorted({citation["document_id"] for citation in citations})
    return {"documentIds": document_ids, "citations": citations}


@app.get("/knowledge/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
