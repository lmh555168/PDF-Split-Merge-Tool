# PDF Split and Merge Tool

A PDF splitting and merging tool written in Python, featuring a CLI and a PySide6 GUI with page preview and thumbnail selection.

## Features

- **Split by Page Count** — Divide a PDF into smaller files with a fixed number of pages each.
- **Split by File Size** — Divide a PDF by maximum file size (MB), using binary search optimization.
- **Split by Selected Pages** — Preview all pages as thumbnails, select specific pages, and extract them into a new PDF.
- **Merge PDFs** — Combine multiple PDF files into one, with drag-and-drop reordering.
- **PDF Page Preview** — Visual thumbnail preview of every page before processing.
- **Cross-platform** — Works on Windows, macOS, and Linux.

## Installation

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Quick Start

```bash
# Clone the repository
git clone https://github.com/lmh555168/PDF-Split-Merge-Tool.git
cd PDF-Split-Merge-Tool

# Install dependencies (Poppler is bundled for Windows)
uv sync
```

## Usage

### GUI

```bash
uv run pdf-tool-gui
```

Or:

```bash
uv run python -m pdf_tool.gui
```

The GUI provides two tabs:

1. **Split PDF** — Load a PDF, preview page thumbnails, choose a split method (by pages, by size, or by selected pages), and execute.
2. **Merge PDF** — Add multiple PDF files, reorder with up/down buttons, preview selected files, and merge.

### CLI

```bash
uv run pdf-tool <input_pdfs> [options]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `input_pdfs` | Input PDF file path(s). One file for splitting, multiple files for merging. |
| `-m`, `--merge` | Enable merge mode |
| `-s`, `--size` | Split by maximum file size (MB) |
| `-p`, `--pages` | Split by number of pages per file |
| `-o`, `--output` | Output directory (default: `{filename}_output/` next to source PDF) |
| `-f`, `--filename` | Output filename for merge (default: `{first_input}_merge.pdf`) |

#### Examples

```bash
# Split by page count (10 pages per file)
uv run pdf-tool input.pdf -p 10

# Split by file size (max 20 MB each)
uv run pdf-tool input.pdf -s 20

# Split with custom output directory
uv run pdf-tool input.pdf -p 5 -o ./output

# Merge multiple PDFs
uv run pdf-tool file1.pdf file2.pdf file3.pdf -m

# Merge with custom output filename
uv run pdf-tool file1.pdf file2.pdf -m -f merged_report.pdf

# Merge with custom output directory
uv run pdf-tool file1.pdf file2.pdf -m -o ./merged_output
```

## Project Structure

```
PDF-Split-Merge-Tool/
├── src/pdf_tool/
│   ├── __init__.py    # Package exports
│   ├── core.py        # Core PDF logic (pikepdf)
│   ├── cli.py         # CLI entry point
│   └── gui.py         # PySide6 GUI
├── poppler/           # Bundled Poppler binaries (Windows)
├── pyproject.toml     # Project configuration
└── README.md
```

## Tech Stack

- **[pikepdf](https://github.com/pikepdf/pikepdf)** — PDF manipulation
- **[PySide6](https://doc.qt.io/qtforpython-6/)** — GUI framework (Qt for Python)
- **[pdf2image](https://github.com/Belval/pdf2image)** — PDF page rendering (Poppler wrapper)
- **[Poppler](https://poppler.freedesktop.org/)** — PDF rendering engine (bundled for Windows)

## License

MIT
