import os
import pikepdf
from io import BytesIO


def get_output_file_name(input_pdf_path, output_dir, suffix):
    base_name = os.path.splitext(os.path.basename(input_pdf_path))[0]
    return os.path.join(output_dir, f"{base_name}_part_{suffix}.pdf")


def split_pdf_by_pages(input_pdf_path, output_dir, pages_per_split, progress_callback=None):
    with pikepdf.Pdf.open(input_pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            return False, "PDF 文件没有任何页面。"

        total_parts = (total_pages + pages_per_split - 1) // pages_per_split

        for part_index, i in enumerate(range(0, total_pages, pages_per_split)):
            new_pdf = pikepdf.Pdf.new()
            for j in range(i, min(i + pages_per_split, total_pages)):
                new_pdf.pages.append(pdf.pages[j])

            output_pdf_path = get_output_file_name(
                input_pdf_path, output_dir, f"{part_index + 1}"
            )
            new_pdf.save(output_pdf_path)

            file_size = os.path.getsize(output_pdf_path) / (1024 * 1024)

            if progress_callback:
                progress_callback((part_index + 1) / total_parts * 100)

    return True, "PDF 分割成功。"


def _count_page_bytes(pdf, start, end):
    temp_pdf = pikepdf.Pdf.new()
    for page_num in range(start, end):
        temp_pdf.pages.append(pdf.pages[page_num])
    buf = BytesIO()
    temp_pdf.save(buf)
    return buf.tell() / (1024 * 1024)


def split_pdf_by_size(input_pdf_path, output_dir, max_size_mb, progress_callback=None):
    with pikepdf.Pdf.open(input_pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            return False, "PDF 文件没有任何页面。"

        split_count = 1
        current_page = 0
        warnings = []

        while current_page < total_pages:
            low = current_page + 1
            high = total_pages
            best = current_page + 1

            while low <= high:
                mid = (low + high) // 2
                current_size = _count_page_bytes(pdf, current_page, mid)

                if current_size <= max_size_mb:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1

            output_pdf_path = get_output_file_name(
                input_pdf_path, output_dir, f"{split_count}"
            )

            out_pdf = pikepdf.Pdf.new()
            for page_num in range(current_page, best):
                out_pdf.pages.append(pdf.pages[page_num])
            out_pdf.save(output_pdf_path)

            file_size = os.path.getsize(output_pdf_path) / (1024 * 1024)
            if file_size > max_size_mb:
                warnings.append(
                    f"第 {split_count} 部分 ({file_size:.2f} MB) 超过指定大小 "
                    f"({max_size_mb} MB)，因单页过大无法继续拆分。"
                )

            if progress_callback:
                progress_callback(best / total_pages * 100)

            split_count += 1
            current_page = best

    msg = "PDF 分割成功。"
    if warnings:
        msg += "\n注意:\n" + "\n".join(warnings)
    return True, msg


def merge_pdfs(input_pdf_paths, output_dir, output_file_name=None, progress_callback=None):
    if not input_pdf_paths:
        return False, "没有提供要合并的PDF文件。"

    merged_pdf = pikepdf.Pdf.new()
    total_files = len(input_pdf_paths)

    for idx, pdf_path in enumerate(input_pdf_paths):
        if not os.path.exists(pdf_path):
            return False, f"文件不存在: {pdf_path}"
        with pikepdf.Pdf.open(pdf_path) as pdf:
            merged_pdf.pages.extend(pdf.pages)

        if progress_callback:
            progress_callback((idx + 1) / total_files * 100)

    if not output_file_name:
        first_base = os.path.splitext(os.path.basename(input_pdf_paths[0]))[0]
        output_file_name = f"{first_base}_merge.pdf"

    output_path = os.path.join(output_dir, output_file_name)
    merged_pdf.save(output_path)

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    return True, f"PDF 合并成功。输出文件: {output_path} (大小: {file_size:.2f} MB)"


def ensure_output_dir(output_dir, fallback_dir=None):
    if not output_dir:
        output_dir = fallback_dir or "."
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    return output_dir


def default_output_dir(input_pdf_path):
    base_dir = os.path.dirname(os.path.abspath(input_pdf_path))
    base_name = os.path.splitext(os.path.basename(input_pdf_path))[0]
    output_dir = os.path.join(base_dir, f"{base_name}_output")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def extract_pages(input_pdf_path, output_dir, page_numbers, output_file_name=None, progress_callback=None):
    if not page_numbers:
        return False, "没有选择要提取的页面。"

    with pikepdf.Pdf.open(input_pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            return False, "PDF 文件没有任何页面。"

        for p in page_numbers:
            if p < 0 or p >= total_pages:
                return False, f"页码超出范围: {p + 1}"

        new_pdf = pikepdf.Pdf.new()
        for idx, p in enumerate(page_numbers):
            new_pdf.pages.append(pdf.pages[p])
            if progress_callback:
                progress_callback((idx + 1) / len(page_numbers) * 100)

        if not output_file_name:
            base = os.path.splitext(os.path.basename(input_pdf_path))[0]
            output_file_name = f"{base}_extracted.pdf"

        output_path = os.path.join(output_dir, output_file_name)
        new_pdf.save(output_path)

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    return True, f"页面提取成功。输出文件: {output_path} (大小: {file_size:.2f} MB)"
