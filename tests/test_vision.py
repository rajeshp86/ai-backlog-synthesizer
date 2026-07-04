"""Tests for vision input — `VisionAttachment` + multimodal Claude calls.

No real API calls. Tests cover:

  1. `VisionAttachment.from_path` validates MIME type, rejects empty
     files, and base64-encodes the bytes
  2. `VisionAttachment.from_bytes` enforces the same MIME allowlist
  3. `ClaudeTool` builds the correct multimodal `content` array when
     images are present (image blocks before the text block, matching
     Anthropic's recommendation)
  4. `DiscoveryEngine.run` forwards vision attachments through to the LLM
     tool when present, and falls back to text-only otherwise
  5. Vision-only input (empty transcript + an image) still triggers
     the parser
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tools.base import ToolError, VisionAttachment  # noqa: E402


# Smallest possible valid PNG — a 1x1 transparent pixel. Reused by every
# test so we don't have to maintain a fixture file on disk.
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)


# --------------------------------------------------------------- VisionAttachment


def test_from_path_loads_png_and_base64_encodes(tmp_path):
    p = tmp_path / "diagram.png"
    p.write_bytes(_TINY_PNG_BYTES)

    att = VisionAttachment.from_path(p)
    assert att.media_type == "image/png"
    assert att.label == "diagram.png"
    # Decoding the base64 back should round-trip to the original bytes.
    assert base64.standard_b64decode(att.data_b64) == _TINY_PNG_BYTES


def test_from_path_rejects_missing_file(tmp_path):
    with pytest.raises(ToolError, match="not found"):
        VisionAttachment.from_path(tmp_path / "no-such-file.png")


def test_from_path_rejects_non_image(tmp_path):
    """A .txt file shouldn't be accepted — `mimetypes` reports text/plain
    which is outside the image allowlist."""
    p = tmp_path / "notes.txt"
    p.write_text("some text")
    with pytest.raises(ToolError, match="image MIME type"):
        VisionAttachment.from_path(p)


def test_from_path_rejects_unsupported_image_type(tmp_path):
    """SVG is `image/svg+xml` — Anthropic doesn't accept it. Reject up front."""
    p = tmp_path / "diagram.svg"
    p.write_text("<svg></svg>")
    with pytest.raises(ToolError, match="Unsupported image type"):
        VisionAttachment.from_path(p)


def test_from_path_rejects_empty_file(tmp_path):
    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    with pytest.raises(ToolError, match="empty"):
        VisionAttachment.from_path(p)


def test_from_bytes_validates_media_type():
    """The `from_bytes` factory is what the Streamlit uploader uses.
    Same allowlist as `from_path`."""
    att = VisionAttachment.from_bytes(
        _TINY_PNG_BYTES, media_type="image/png", label="upload.png"
    )
    assert att.media_type == "image/png"
    assert att.label == "upload.png"

    with pytest.raises(ToolError, match="Unsupported"):
        VisionAttachment.from_bytes(_TINY_PNG_BYTES, media_type="text/plain", label="x")


def test_from_bytes_rejects_empty_payload():
    with pytest.raises(ToolError, match="empty"):
        VisionAttachment.from_bytes(b"", media_type="image/png", label="x")


def test_attachment_is_immutable():
    """VisionAttachment is a frozen dataclass — accidental mutation must error."""
    att = VisionAttachment.from_bytes(_TINY_PNG_BYTES, "image/png", "x.png")
    with pytest.raises(Exception):
        att.label = "different"  # type: ignore[misc]


# --------------------------------------------------------------- ClaudeTool wiring


class _FakeAnthropicResponse:
    """Minimal stand-in for an Anthropic SDK response."""
    def __init__(self, text: str):
        class _Block:
            pass
        block = _Block()
        block.text = text
        self.content = [block]

        class _Usage:
            pass
        usage = _Usage()
        usage.input_tokens = 100
        usage.output_tokens = 50
        self.usage = usage


def _patch_anthropic_client(monkeypatch, capture: list):
    """Patch ChatAnthropic so invoke() records the LangChain messages it
    receives and returns a canned AIMessage response."""
    from tools import claude_tool
    from langchain_core.messages import AIMessage

    class _FakeChatAnthropic:
        def __init__(self, *a, **kw):
            pass

        def bind(self, **kw):
            return self

        def invoke(self, messages, **kw):
            capture.append(messages)
            return AIMessage(
                content='{"summary": "ok", "topics": []}',
                response_metadata={"usage": {"input_tokens": 100, "output_tokens": 50}},
            )

    monkeypatch.setattr(claude_tool, "ChatAnthropic", _FakeChatAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")


def test_claude_tool_builds_multimodal_array_when_images_present(monkeypatch):
    """The Anthropic API expects `content` as a list of blocks when
    images are attached. Image blocks come before the text block."""
    from tools.claude_tool import ClaudeTool

    capture: list = []
    _patch_anthropic_client(monkeypatch, capture)
    img = VisionAttachment.from_bytes(_TINY_PNG_BYTES, "image/png", "diagram.png")

    tool = ClaudeTool(model="claude-haiku-4-5")
    tool.call_for_json("Extract topics from these inputs.", images=[img])

    assert len(capture) == 1
    # capture[0] is the list of LangChain messages: [SystemMessage, HumanMessage]
    human = capture[0][1]
    blocks = human.content
    assert isinstance(blocks, list)
    # Image first, text second.
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[0]["source"]["data"] == img.data_b64
    assert blocks[1]["type"] == "text"
    assert "Extract topics" in blocks[1]["text"]


def test_claude_tool_sends_plain_string_when_no_images(monkeypatch):
    """Without images, the content stays as a plain string — the
    backward-compatible path."""
    from tools.claude_tool import ClaudeTool

    capture: list = []
    _patch_anthropic_client(monkeypatch, capture)

    tool = ClaudeTool(model="claude-haiku-4-5")
    tool.call_for_json("text only prompt")

    # capture[0] is [SystemMessage, HumanMessage]
    human = capture[0][1]
    # Without images the content stays as a plain string.
    assert isinstance(human.content, str)
    assert "text only" in human.content


def test_claude_tool_handles_multiple_images(monkeypatch):
    """Multiple attachments → multiple image blocks, then one text block."""
    from tools.claude_tool import ClaudeTool

    capture: list = []
    _patch_anthropic_client(monkeypatch, capture)
    img1 = VisionAttachment.from_bytes(_TINY_PNG_BYTES, "image/png", "a.png")
    img2 = VisionAttachment.from_bytes(_TINY_PNG_BYTES, "image/png", "b.png")

    tool = ClaudeTool(model="claude-haiku-4-5")
    tool.call_for_json("prompt", images=[img1, img2])

    blocks = capture[0][1].content  # HumanMessage.content
    assert len(blocks) == 3
    assert blocks[0]["type"] == "image"
    assert blocks[1]["type"] == "image"
    assert blocks[2]["type"] == "text"


# --------------------------------------------------------------- DiscoveryEngine wiring


class _SpyClaude:
    """Records `call_for_json` invocations so we can verify what got
    forwarded. Returns a fixed parser-shaped response."""
    name = "claude"

    def __init__(self):
        self.calls: list[dict] = []

    def call_for_json(self, prompt, max_tokens=4000, *, images=None):
        self.calls.append({"prompt": prompt, "images": images})
        return {"summary": "ok", "topics": [{"theme": "x", "raw_quote": "y"}]}, {
            "input_tokens": 50, "output_tokens": 25,
        }


def test_discovery_engine_forwards_vision_attachments():
    from agents.discovery_engine import DiscoveryEngine
    from memory.store import MemoryStore
    from memory.audit_log import AuditLog

    spy = _SpyClaude()
    parser = DiscoveryEngine(tool=spy, memory=MemoryStore(), audit=AuditLog())
    img = VisionAttachment.from_bytes(_TINY_PNG_BYTES, "image/png", "wb.png")

    parser.run("transcript text", vision_attachments=[img])

    assert len(spy.calls) == 1
    assert spy.calls[0]["images"] == [img]
    # The transcript should also carry the visual-attachment hint so the
    # model knows to treat the image as a first-class source.
    assert "Visual attachments are included" in spy.calls[0]["prompt"]


def test_discovery_engine_no_images_means_no_kwarg(monkeypatch):
    """When there are no vision attachments, the parser should NOT pass
    `images=` to the tool — keeps the path compatible with tools that
    don't accept the kwarg (e.g. the Gemini wrapper)."""
    from agents.discovery_engine import DiscoveryEngine
    from memory.store import MemoryStore
    from memory.audit_log import AuditLog

    class _StrictClaude:
        """Errors if `images` is passed at all."""
        name = "claude"
        def __init__(self):
            self.calls = []
        def call_for_json(self, prompt, max_tokens=4000):
            self.calls.append(prompt)
            return {"topics": []}, {"input_tokens": 1, "output_tokens": 1}

    strict = _StrictClaude()
    parser = DiscoveryEngine(tool=strict, memory=MemoryStore(), audit=AuditLog())
    parser.run("transcript", vision_attachments=None)
    assert len(strict.calls) == 1


def test_discovery_engine_with_only_images_uses_placeholder_transcript():
    """An image-only run (empty transcript) should still trigger the
    parser; the transcript placeholder text should mention that the
    image is the source."""
    from agents.discovery_engine import DiscoveryEngine
    from memory.store import MemoryStore
    from memory.audit_log import AuditLog

    spy = _SpyClaude()
    parser = DiscoveryEngine(tool=spy, memory=MemoryStore(), audit=AuditLog())
    img = VisionAttachment.from_bytes(_TINY_PNG_BYTES, "image/png", "x.png")

    parser.run("", vision_attachments=[img])

    assert len(spy.calls) == 1
    # The prompt should explicitly say "no text transcript — see attached images"
    # so the model knows where the actual source content lives.
    prompt = spy.calls[0]["prompt"]
    assert "no text transcript" in prompt or "see attached images" in prompt
