"""ChatKit server integration for the boilerplate backend."""

from __future__ import annotations

import asyncio
import base64
import os
from .persistence import get_persistence
from datetime import datetime
import logging
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Final, Literal, cast
from uuid import uuid4

from agents import Agent, RunContextWrapper, Runner, function_tool
from chatkit.agents import (
    AgentContext,
    ClientToolCall,
    ThreadItemConverter,
    stream_agent_response,
)
from chatkit.server import ChatKitServer
from chatkit.types import (
    AssistantMessageItem,
    Attachment,
    ClientToolCallItem,
    HiddenContextItem,
    ThreadItem,
    ThreadItemDoneEvent,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
)
from chatkit.widgets import Card
from chatkit.widgets import Image as WidgetImage
from chatkit.widgets import Text as WidgetText
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputContentParam
from pydantic import ConfigDict, Field

from .ad_assets import AdAsset, ad_asset_store
from .constants import INSTRUCTIONS, MODEL
from .memory_store import MemoryStore

SUPPORTED_COLOR_SCHEMES: Final[frozenset[str]] = frozenset({"light", "dark"})
CLIENT_THEME_TOOL_NAME: Final[str] = "switch_theme"
OPENAI_IMAGE_MODEL: Final[str] = "gpt-image-1"
MAX_IMAGE_ATTEMPTS: Final[int] = 3
MAX_CONTENT_LENGTH: Final[int] = 10000  # Max characters for web content
HTTP_TIMEOUT: Final[int] = 30  # Timeout for HTTP requests in seconds

# Module logger
logger = logging.getLogger(__name__)


def _normalize_color_scheme(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized in SUPPORTED_COLOR_SCHEMES:
        return normalized
    if "dark" in normalized:
        return "dark"
    if "light" in normalized:
        return "light"
    raise ValueError("Theme must be either 'light' or 'dark'.")


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _save_image_to_file(base64_data: str, image_id: str) -> str:
    """Save base64 image data to PNG file and return the file path.
    
    Args:
        base64_data: Base64 encoded image data (without data:image/png;base64, prefix)
        image_id: Unique identifier for the image
    
    Returns:
        Relative URL path to access the image (e.g., "/images/img_abc123.png")
    """
    # Create static/images directory if not exists
    static_dir = Path(__file__).parent.parent / "static" / "images"
    static_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    filename = f"img_{image_id}.png"
    file_path = static_dir / filename
    
    # Decode and save image
    image_bytes = base64.b64decode(base64_data)
    file_path.write_bytes(image_bytes)
    
    # Return URL path
    return f"/images/{filename}"


class AdAgentContext(AgentContext):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    store: Annotated[MemoryStore, Field(exclude=True)]
    request_context: dict[str, Any]


async def _stream_asset_hidden(ctx: RunContextWrapper[AdAgentContext], asset: AdAsset) -> None:
    prompt_summary = " | ".join(asset.image_prompts[:2]) if asset.image_prompts else ""
    images_summary = f' count="{len(asset.images)}"' if asset.images else ""
    details = (
        f'<AD_ASSET id="{asset.id}" product="{asset.product}" style="{asset.style}" '
        f'tone="{asset.tone}" pitch="{asset.pitch}">'
        f"<HEADLINE>{asset.headline}</HEADLINE>"
        f"<COPY>{asset.primary_text}</COPY>"
        f"<CTA>{asset.call_to_action}</CTA>"
        f"<PROMPTS>{prompt_summary}</PROMPTS>"
        f"<IMAGES{images_summary}/ />"
        "</AD_ASSET>"
    )
    hidden_item = HiddenContextItem(
        id=_gen_id("msg"),
        thread_id=ctx.context.thread.id,
        created_at=datetime.now(),
        content=details,
    )
    await ctx.context.stream(ThreadItemDoneEvent(item=hidden_item))


@function_tool(
    description_override=(
        "Store a finalized ad concept including copy and image prompts so it can be shown in the campaign gallery."
    )
)
async def save_ad_asset(
    ctx: RunContextWrapper[AdAgentContext],
    product: str,
    style: str,
    tone: str,
    pitch: str,
    headline: str,
    primary_text: str,
    call_to_action: str,
    image_prompts: list[str],
    images: list[str] | None = None,
    asset_id: str | None = None,
) -> dict[str, str]:
    metadata = dict(getattr(ctx.context.thread, "metadata", {}) or {})
    sanitized_prompts = [prompt.strip() for prompt in image_prompts if prompt.strip()]
    if not sanitized_prompts:
        sanitized_prompts = ["Visual direction forthcoming"]
    sanitized_images = [img.strip() for img in (images or []) if img.strip()]
    pending_images = list(metadata.get("pending_images") or [])
    latest_asset_id = asset_id or metadata.get("latest_asset_id")
    merged_images = sanitized_images or []
    if pending_images:
        merged_images = list(dict.fromkeys(merged_images + pending_images))
    clean_product = product.strip()
    clean_style = style.strip()
    clean_tone = tone.strip()
    clean_pitch = pitch.strip()
    clean_headline = headline.strip()
    clean_primary = primary_text.strip()
    clean_cta = call_to_action.strip()
    if not all(
        [
            clean_product,
            clean_style,
            clean_tone,
            clean_pitch,
            clean_headline,
            clean_primary,
            clean_cta,
        ]
    ):
        raise ValueError("All ad fields must be provided before saving the asset.")

    asset = await ad_asset_store.create(
        product=clean_product,
        style=clean_style,
        tone=clean_tone,
        pitch=clean_pitch,
        headline=clean_headline,
        primary_text=clean_primary,
        call_to_action=clean_cta,
        image_prompts=sanitized_prompts,
        images=merged_images if merged_images else None,
        asset_id=latest_asset_id,
    )
    thread = ctx.context.thread
    metadata["latest_asset_id"] = asset.id
    if merged_images:
        metadata.pop("pending_images", None)
    thread.metadata = metadata
    await ctx.context.store.save_thread(thread, ctx.context.request_context)
    await _stream_asset_hidden(ctx, asset)
    asset_arguments: dict[str, Any] = {"asset": asset.as_dict()}
    ctx.context.client_tool_call = ClientToolCall(
        name="record_ad_asset",
        arguments=asset_arguments,
    )
    # Persist asset in SQLite (taking first image if exists)
    try:
        persistence = get_persistence()
        persistence.save_asset(
            asset_id=asset.id,
            thread_id=thread.id,
            prompt="; ".join(sanitized_prompts) if sanitized_prompts else None,
            image_path=asset.images[0] if asset.images else None,
            metadata={
                "product": asset.product,
                "style": asset.style,
                "tone": asset.tone,
                "pitch": asset.pitch,
                "headline": asset.headline,
                "call_to_action": asset.call_to_action,
                "image_prompts": asset.image_prompts,
                "images": asset.images,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[persistence] failed saving asset id=%s error=%s", asset.id, exc)
    print(f"AD ASSET SAVED: {asset}")
    return {
        "asset_id": asset.id,
        "status": "saved",
        "image_count": str(len(asset.images or [])),
    }


@function_tool(
    description_override=(
        "Generate a marketing-ready image for the campaign using the image generation model."
    )
)
async def generate_ad_image(
    ctx: RunContextWrapper[AdAgentContext],
    prompt: str,
    size: Literal["256x256", "512x512", "1024x1024", "square", "portrait", "landscape"]
    | str = "1024x1024",
) -> dict[str, str | bool | None]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Image generation requires OPENAI_API_KEY to be configured on the server."
        )

    client = AsyncOpenAI(api_key=api_key)
    normalized_size = str(size).strip().lower()
    allowed_sizes = {"256x256", "512x512", "1024x1024"}
    if normalized_size in {"square", "default", "portrait", "landscape"}:
        normalized_size = "1024x1024"
    elif normalized_size not in allowed_sizes:
        normalized_size = "1024x1024"

    attempt = 0
    while attempt < MAX_IMAGE_ATTEMPTS:
        attempt += 1
        try:
            normalized_size_literal = cast(
                Literal["256x256", "512x512", "1024x1024"],
                normalized_size,
            )
            response = await client.images.generate(
                model=OPENAI_IMAGE_MODEL,
                prompt=prompt,
                size=normalized_size_literal,
                quality="high",
            )
            data = getattr(response, "data", None)
            if not data:
                raise RuntimeError("Image generation returned no results.")
            first = data[0]
            image_b64 = getattr(first, "b64_json", None)
            if not image_b64:
                raise RuntimeError("Image generation produced an unexpected payload.")
            
            # Save image to file and get URL
            image_id = _gen_id("img")
            image_url = _save_image_to_file(image_b64, image_id)
            
            # Create base64 data URL for inline display
            data_url = f"data:image/png;base64,{image_b64}"
            
            caption = f"Generated for prompt: {prompt}".strip()
            widget = Card(
                children=[
                    WidgetImage(
                        src=data_url,
                        alt=prompt,
                        radius="xl",
                        fit="contain",
                    ),
                    WidgetText(
                        value=caption,
                        size="sm",
                        color="secondary",
                    ),
                ]
            )
            await ctx.context.stream_widget(widget)

            thread = ctx.context.thread
            metadata = dict(getattr(thread, "metadata", {}) or {})
            latest_asset_id = metadata.get("latest_asset_id")
            pending_images = list(metadata.get("pending_images") or [])

            updated_asset: AdAsset | None = None
            if latest_asset_id:
                # Store image URL (downloadable) instead of data URL
                updated_asset = await ad_asset_store.append_image(latest_asset_id, image_url)
                if updated_asset is None:
                    latest_asset_id = None

            if not latest_asset_id:
                pending_images.append(image_url)
                metadata["pending_images"] = pending_images
            else:
                metadata.pop("pending_images", None)
                if updated_asset is not None:
                    updated_arguments: dict[str, Any] = {"asset": updated_asset.as_dict()}
                    ctx.context.client_tool_call = ClientToolCall(
                        name="record_ad_asset",
                        arguments=updated_arguments,
                    )
                else:
                    metadata.setdefault("pending_images", []).append(image_url)

            thread.metadata = metadata
            await ctx.context.store.save_thread(thread, ctx.context.request_context)

            # Persist an image asset entry (lightweight) if we updated an existing asset
            try:
                persistence = get_persistence()
                persistence.save_asset(
                    asset_id=updated_asset.id if updated_asset else image_id,
                    thread_id=thread.id,
                    prompt=prompt,
                    image_path=image_url,
                    metadata={"generated_via": "generate_ad_image", "size": normalized_size},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[persistence] failed saving image asset asset_id=%s error=%s",
                    updated_asset.id if updated_asset else image_id,
                    exc,
                )

            return {
                "status": "generated",
                "image_available": True,
                "asset_id": metadata.get("latest_asset_id"),
            }
        except Exception as exc:  # noqa: BLE001
            if attempt >= MAX_IMAGE_ATTEMPTS:
                print(
                    "[generate_ad_image] failed",
                    {
                        "prompt": prompt,
                        "size": normalized_size,
                        "error": str(exc),
                    },
                )
                raise RuntimeError(f"Image generation failed repeatedly: {exc}") from exc
            await asyncio.sleep(attempt * 0.75)

    raise RuntimeError("Image generation failed unexpectedly.")


@function_tool(
    description_override=("Switch the chat interface between light and dark color schemes.")
)
async def switch_theme(
    ctx: RunContextWrapper[AdAgentContext],
    theme: str,
) -> dict[str, str]:
    requested = _normalize_color_scheme(theme)
    ctx.context.client_tool_call = ClientToolCall(
        name=CLIENT_THEME_TOOL_NAME,
        arguments={"theme": requested},
    )
    return {"theme": requested}


@function_tool(
    description_override=(
        "Fetch and analyze content from a URL to get insights about style, messaging, "
        "and marketing approach. Use this when user provides a competitor or reference URL."
    )
)
async def fetch_web_content(
    ctx: RunContextWrapper[AdAgentContext],
    url: str,
) -> dict[str, str]:
    """Fetch and parse web content from a URL using Redis-backed crawler service.
    
    Args:
        ctx: Agent context
        url: Web URL to fetch (e.g., https://example.com)
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - title: Page title
        - description: Meta description
        - headings: Main headings (H1, H2)
        - content: Cleaned text content (max 10,000 chars)
        - url: Original URL
        - strategy: Crawl strategy used
        - error: Error message (if failed)
    """
    try:
        from .crawl_service import send_crawl_job, get_crawl_result
        
        logger.info("[fetch_web_content] start url=%s", url)
        
        # Validate URL
        if not url.startswith(("http://", "https://")):
            logger.warning("[fetch_web_content] invalid_url url=%s", url)
            return {
                "status": "error",
                "error": "URL must start with http:// or https://",
                "url": url,
            }
        
        # Send crawl job to Redis queue
        job_id = send_crawl_job(url)
        logger.info(f"[fetch_web_content] sent job_id={job_id} url={url}")
        
        # Poll for result (30s timeout)
        result = get_crawl_result(job_id, timeout=30)
        
        if result and result.get("status") == "success":
            logger.info(
                "[fetch_web_content] success url=%s strategy=%s title=%s content_len=%d",
                url,
                result.get("strategy", "unknown"),
                result.get("title", "")[:50],
                len(result.get("content", ""))
            )
            return {
                "status": "success",
                "url": url,
                "title": result.get("title", "Untitled"),
                "description": result.get("description", "No description available"),
                "headings": result.get("headings", "No headings found"),
                "content": result.get("content", ""),
                "strategy": result.get("strategy", "unknown"),
            }
        elif result:
            # Got result but failed
            error_msg = result.get("error", "Crawl failed")
            logger.error(f"[fetch_web_content] failed url={url} error={error_msg}")
            return {
                "status": "error",
                "url": url,
                "error": error_msg,
            }
        else:
            # Timeout
            logger.error(f"[fetch_web_content] timeout url={url}")
            return {
                "status": "error",
                "url": url,
                "error": "Crawl job timeout after 30 seconds. The crawler service may be down or overloaded.",
            }
        
    except Exception as e:
        logger.exception("[fetch_web_content] failed url=%s error=%s", url, str(e))
        return {
            "status": "error",
            "url": url,
            "error": f"Failed to fetch URL: {str(e)}",
        }


def _user_message_text(item: UserMessageItem) -> str:
    parts: list[str] = []
    for part in item.content:
        text = getattr(part, "text", None)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


class AdCreativeServer(ChatKitServer[dict[str, Any]]):
    """ChatKit server wired up with the ad generation workflow."""

    def __init__(self) -> None:
        self.store: MemoryStore = MemoryStore()
        super().__init__(self.store)
        tools = [save_ad_asset, switch_theme, generate_ad_image, fetch_web_content]
        self.assistant = Agent[AdAgentContext](
            model=MODEL,
            name="Ad Generation Helper",
            instructions=INSTRUCTIONS,
            tools=tools,  # type: ignore[arg-type]
        )
        self._thread_item_converter = self._init_thread_item_converter()

    async def respond(
        self,
        thread: ThreadMetadata,
        input: ThreadItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        if input is None:
            return

        if isinstance(input, ClientToolCallItem):
            return

        if not isinstance(input, UserMessageItem):
            return

        agent_context = AdAgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )

        agent_input = await self._to_agent_input(thread, input, context)
        if agent_input is None:
            return

        metadata = dict(getattr(thread, "metadata", {}) or {})
        previous_response_id = metadata.get("previous_response_id")
        agent_context.previous_response_id = previous_response_id

        result = Runner.run_streamed(
            self.assistant,
            agent_input,
            context=agent_context,
            previous_response_id=previous_response_id,
        )

        async for event in stream_agent_response(agent_context, result):
            # Intercept assistant messages for persistence
            try:
                if isinstance(getattr(event, "item", None), AssistantMessageItem):
                    content_parts = []
                    for part in getattr(event.item, "content", []) or []:
                        text = getattr(part, "text", None)
                        if text:
                            content_parts.append(text)
                    if content_parts:
                        persistence = get_persistence()
                        persistence.save_message(thread.id, "assistant", "\n".join(content_parts))
                elif isinstance(getattr(event, "item", None), UserMessageItem):
                    # user message already present; ensure persistence
                    content_parts = []
                    for part in getattr(event.item, "content", []) or []:
                        text = getattr(part, "text", None)
                        if text:
                            content_parts.append(text)
                    if content_parts:
                        persistence = get_persistence()
                        persistence.save_message(thread.id, "user", "\n".join(content_parts))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[persistence] failed saving message thread=%s error=%s", thread.id, exc)
            yield event

        if result.last_response_id is not None:
            metadata["previous_response_id"] = result.last_response_id
            thread.metadata = metadata
            await self.store.save_thread(thread, context)

    async def to_message_content(self, _input: Attachment) -> ResponseInputContentParam:
        raise RuntimeError("File attachments are not supported by the ChatKit demo backend.")

    def _init_thread_item_converter(self) -> Any | None:
        converter_cls = ThreadItemConverter
        if converter_cls is None or not callable(converter_cls):
            return None

        attempts: tuple[dict[str, Any], ...] = (
            {"to_message_content": self.to_message_content},
            {"message_content_converter": self.to_message_content},
            {},
        )

        for kwargs in attempts:
            try:
                return converter_cls(**kwargs)
            except TypeError:
                continue
        return None

    async def _to_agent_input(
        self,
        thread: ThreadMetadata,
        item: ThreadItem,
        context: dict[str, Any],
    ) -> Any | None:
        converter = getattr(self, "_thread_item_converter", None)
        history: list[ThreadItem] = []
        try:
            loaded = await self.store.load_thread_items(
                thread.id,
                after=None,
                limit=50,
                order="desc",
                context=context,
            )
            history = list(reversed(loaded.data))
        except Exception:  # noqa: BLE001
            history = []

        latest_id = getattr(item, "id", None)
        if latest_id is None or not any(
            getattr(existing, "id", None) == latest_id for existing in history
        ):
            history.append(item)

        relevant: list[ThreadItem] = [
            entry
            for entry in history
            if isinstance(
                entry,
                (
                    UserMessageItem,
                    AssistantMessageItem,
                    ClientToolCallItem,
                ),
            )
        ]

        if len(relevant) > 12:
            relevant = relevant[-12:]

        if converter is not None and relevant:
            to_agent = getattr(converter, "to_agent_input", None)
            if callable(to_agent):
                try:
                    return await to_agent(relevant)
                except TypeError:
                    pass

        for entry in reversed(relevant):
            if isinstance(entry, UserMessageItem):
                return _user_message_text(entry)

        if isinstance(item, UserMessageItem):
            return _user_message_text(item)

        return None

    async def _add_hidden_item(
        self,
        thread: ThreadMetadata,
        context: dict[str, Any],
        content: str,
    ) -> None:
        await self.store.add_thread_item(
            thread.id,
            HiddenContextItem(
                id=_gen_id("msg"),
                thread_id=thread.id,
                created_at=datetime.now(),
                content=content,
            ),
            context,
        )


def create_chatkit_server() -> AdCreativeServer:
    """Return a configured ChatKit server instance if dependencies are available."""
    return AdCreativeServer()
