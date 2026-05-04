# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PDF Split and Merge Tool — a Python tool for splitting PDFs (by page count, file size, or selected pages) and merging multiple PDFs. Provides a CLI and a PySide6 GUI with PDF page preview and thumbnail selection.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run pdf-tool input.pdf -p 10 -o output_dir        # split by pages
uv run pdf-tool input.pdf -s 20 -o output_dir         # split by size (MB)
uv run pdf-tool file1.pdf file2.pdf -m -o output_dir  # merge

# Run GUI
uv run pdf-tool-gui
# or
uv run python -m pdf_tool.gui
```

Poppler is bundled in `poppler/poppler_bin/` and auto-detected by the GUI.

No test suite or linter is configured.

## Architecture

```
src/pdf_tool/
├── __init__.py    # Package exports
├── core.py        # Shared business logic (pikepdf)
├── cli.py         # argparse CLI entry point (pdf-tool command)
└── gui.py         # PySide6 GUI with QThread workers
```

- **`core.py`** — All PDF operations: `split_pdf_by_pages()`, `split_pdf_by_size()`, `merge_pdfs()`, `extract_pages()`. All functions return `(success: bool, message: str)` and accept optional `progress_callback`. Empty PDF (0 pages) is handled gracefully.
- **`cli.py`** — Thin argparse wrapper. Reconfigures stdout/stderr to UTF-8 for Windows. Exits with code 1 on failure.
- **`gui.py`** — `MainWindow` with two tabs (Split/Merge). Uses `PdfWorker` (QThread) for PDF operations and `ThumbnailWorker` for page thumbnails. Version-based invalidation prevents stale thumbnail results when switching files.

## Key Technical Details

- PDF operations use `pikepdf`; preview rendering uses `pdf2image` (Poppler)
- File naming: `{baseName}_part_{N}.pdf` for splits, `{baseName}_merge.pdf` for merges, `{baseName}_extracted.pdf` for extracts
- Default output directory: `{source_pdf_dir}/{source_name}_output/`
- GUI language is Chinese
- `PdfWorker.task_finished` signal (renamed from `finished` to avoid QThread name collision)
