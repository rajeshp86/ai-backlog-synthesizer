#!/usr/bin/env python3
"""Pre-load the sentence-transformers embedding model.

Called by entrypoint.sh before Streamlit starts (and baked into the Docker
image layer by the Dockerfile RUN step) so that the first synthesis run has
no cold-start delay in the "detecting duplicates" stage.

The model (~80 MB) is downloaded once and cached in HuggingFace's default
cache directory ($HF_HOME or ~/.cache/huggingface).  On subsequent container
starts the cache is already present and this script completes in < 1 second.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure src/ is on the path when run from the project root.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

def main() -> None:
    t0 = time.perf_counter()
    try:
        from tools.embedding_tool import EmbeddingTool
        tool = EmbeddingTool()
        tool.encode(["warmup sentence for embedding model pre-load"])
        elapsed = time.perf_counter() - t0
        print(f"Embedding model ready ({elapsed:.1f}s)", flush=True)
    except ImportError as exc:
        # sentence-transformers not installed — embeddings will fall back to
        # LLM-based dedup at run time.  Not fatal during warmup.
        print(f"Skipping warmup — sentence-transformers not available: {exc}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Warmup failed (non-fatal): {exc}", flush=True, file=sys.stderr)
        sys.exit(0)  # don't block container startup on warmup failure


if __name__ == "__main__":
    main()
