"""Root entry point for ARIA.

Prefer running the package form:
    python -m src.agent.main --validate-only
    python -m src.agent.main --goal "avoid obstacles" --steps 50

This wrapper exists so `python main.py ...` also works.
"""

from src.agent.main import main


if __name__ == "__main__":
    raise SystemExit(main())
