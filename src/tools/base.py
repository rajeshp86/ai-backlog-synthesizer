"""Common base class for tools.

Tools are deterministic surfaces the agents call. Each tool has one job
and a small typed interface. Most tools in this project are mocked so the
demo is self-contained — swapping them for real implementations (real JIRA
REST API, real Confluence API, etc.) is a one-file change.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path


class ToolError(Exception):
    """Raised when a tool call cannot succeed (vs. retryable transient errors)."""


class Tool:
    """Base tool. Subclasses set `name` for audit log identification."""

    name: str = "tool"

    def __reduce__(self) -> tuple:
        # Tool objects are stored in LangGraph state (_jira, _confluence).
        # MemorySaver tries to serialize every state field; returning a fresh
        # instance prevents a msgpack TypeError without disrupting the run.
        return (self.__class__.__new__, (self.__class__,))


# ----------------------------------------------------- vision attachments


@dataclass(frozen=True)
class VisionAttachment:
    """A single image attached to an LLM call.

    `data_b64` is the base64-encoded image bytes; `media_type` is the
    MIME type (e.g. "image/png"). `label` is a short human-readable
    name that the audit log uses to identify the attachment without
    echoing the raw bytes.

    Build with `VisionAttachment.from_path(...)` — keeps the loading
    logic in one place and validates the MIME type up front.
    """

    data_b64: str
    media_type: str
    label: str

    @classmethod
    def from_path(cls, path: str | Path) -> "VisionAttachment":
        p = Path(path)
        if not p.exists():
            raise ToolError(f"Image not found: {p}")
        if not p.is_file():
            raise ToolError(f"Not a file: {p}")
        media_type, _ = mimetypes.guess_type(p.name)
        if media_type is None or not media_type.startswith("image/"):
            raise ToolError(
                f"Could not detect an image MIME type for {p.name}. "
                "Supported: png, jpeg, jpg, webp, gif."
            )
        # Anthropic accepts image/png, image/jpeg, image/webp, image/gif.
        if media_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ToolError(
                f"Unsupported image type {media_type!r}. "
                "Convert to png/jpeg/webp/gif first."
            )
        data = p.read_bytes()
        if not data:
            raise ToolError(f"Image is empty: {p}")
        return cls(
            data_b64=base64.standard_b64encode(data).decode("ascii"),
            media_type=media_type,
            label=p.name,
        )

    @classmethod
    def from_bytes(cls, data: bytes, media_type: str, label: str) -> "VisionAttachment":
        """Build directly from bytes (e.g. a Streamlit file uploader)."""
        if media_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ToolError(f"Unsupported image type {media_type!r}.")
        if not data:
            raise ToolError("Image bytes are empty.")
        return cls(
            data_b64=base64.standard_b64encode(data).decode("ascii"),
            media_type=media_type,
            label=label,
        )
