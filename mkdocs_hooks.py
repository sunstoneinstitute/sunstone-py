"""MkDocs hooks for the Sunstone docs site."""

from __future__ import annotations

import posixpath
import shutil
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.pages import Page
from mkdocs.utils.meta import get_data


def on_post_page(output: str, page: Page, config: MkDocsConfig) -> str:
    """Advertise the raw Markdown sibling via ``<link rel="alternate">``.

    Why: GitHub Pages cannot do Accept-header content negotiation, so the
    HTML page itself points discoverable agents at the ``.md`` source.
    """
    del config
    md_src = page.file.src_uri
    html_dest = page.file.dest_uri
    html_dir = posixpath.dirname(html_dest)
    rel = posixpath.relpath(md_src, html_dir) if html_dir else md_src
    tag = f'<link rel="alternate" type="text/markdown" href="{rel}">'
    return output.replace("</head>", f"  {tag}\n  </head>", 1)


def on_post_build(config: MkDocsConfig) -> None:
    """Copy raw Markdown sources next to the rendered HTML.

    Why: GitHub Pages is static and cannot do Accept-header content
    negotiation, so AI agents and curl users get a predictable
    ``<page>.md`` URL alongside ``<page>/index.html``.
    """
    docs_dir = Path(config["docs_dir"])
    site_dir = Path(config["site_dir"])
    for md in docs_dir.rglob("*.md"):
        dest = site_dir / md.relative_to(docs_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md, dest)
    _write_llms_txt(config, docs_dir, site_dir)


def _llms_entry(docs_dir: Path, src: str, title: str | None = None) -> str:
    text = (docs_dir / src).read_text(encoding="utf-8")
    body, meta = get_data(text)
    if title is None:
        title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), src)
    desc = meta.get("description")
    return f"- [{title}]({src})" + (f": {desc}" if desc else "")


def _write_llms_txt(config: MkDocsConfig, docs_dir: Path, site_dir: Path) -> None:
    """Write ``llms.txt`` (https://llmstxt.org) indexing the raw Markdown pages.

    Why: agents fetch one index per docs version to find the right page.
    Sections follow ``nav``. Top-level pages share a "Docs" section, and
    pages missing from ``nav`` go under "Other pages". Links are relative so
    they resolve inside the same mike version directory.
    """
    lines = [f"# {config['site_name']}", "", f"> {config['site_description']}", ""]
    seen: set[str] = set()
    top: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for item in config["nav"] or []:
        ((title, value),) = item.items()
        if isinstance(value, str):
            top.append(_llms_entry(docs_dir, value, title))
            seen.add(value)
        else:
            entries = []
            for sub in value:
                ((sub_title, src),) = sub.items()
                entries.append(_llms_entry(docs_dir, src, sub_title))
                seen.add(src)
            sections.append((title, entries))
    rest = [_llms_entry(docs_dir, md.name) for md in sorted(docs_dir.glob("*.md")) if md.name not in seen]
    for title, entries in [("Docs", top), *sections, ("Other pages", rest)]:
        if entries:
            lines += [f"## {title}", "", *entries, ""]
    (site_dir / "llms.txt").write_text("\n".join(lines), encoding="utf-8")
