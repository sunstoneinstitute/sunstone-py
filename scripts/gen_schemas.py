"""Regenerate schemas/*.json and docs/datasets-yaml-reference.md. Usage: uv run python scripts/gen_schemas.py"""

from pathlib import Path

from sunstone.vocab.generate import write_all

if __name__ == "__main__":
    for p in write_all(Path(__file__).resolve().parent.parent):
        print(f"wrote {p.relative_to(Path.cwd()) if p.is_relative_to(Path.cwd()) else p}")
