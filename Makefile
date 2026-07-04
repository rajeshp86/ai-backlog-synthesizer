# Backlog Synthesizer — common tasks.
# Run `make help` to see everything.

.DEFAULT_GOAL := help
.PHONY: help install test lint eval eval-fast ui clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install pinned dependencies into the active environment (Python 3.13)
	pip install -r requirements-lock.txt

test:  ## Run the full test suite (mocked, offline, ~1s)
	python -m pytest tests/ -q

lint:  ## Lint with ruff (matches CI's narrow ruleset)
	ruff check src/ app.py || true

ui:  ## Launch the Streamlit UI at http://localhost:8502
	streamlit run app.py --server.port 8502

eval-fast:  ## Run the golden evaluation suite (deterministic metrics only)
	python evaluation/run_evaluation.py --no-save-results

eval:  ## Run the full golden evaluation with the LLM-as-judge (spends API credit)
	python evaluation/run_evaluation.py --use-llm-judge

clean:  ## Remove caches and generated artifacts (keeps committed outputs/eval results)
	rm -rf .pytest_cache .ruff_cache **/__pycache__ .cache/memory 2>/dev/null || true
