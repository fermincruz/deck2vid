"""PDF inspection and rasterisation using PyMuPDF."""

from pathlib import Path

import fitz


def page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF."""
    with fitz.open(pdf_path) as document:
        return document.page_count


def render_pages(pdf_path: Path, output_dir: Path, dpi: int = 150) -> list[Path]:
    """Render all PDF pages to numbered PNG files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72
    matrix = fitz.Matrix(scale, scale)
    rendered: list[Path] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document):
            destination = output_dir / f"slide-{index + 1:04d}.png"
            page.get_pixmap(matrix=matrix, alpha=False).save(destination)
            rendered.append(destination)
    return rendered