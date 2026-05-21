"""MkDocs hooks for the Sunstone docs site."""

from __future__ import annotations

import posixpath
import shutil
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.pages import Page


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
