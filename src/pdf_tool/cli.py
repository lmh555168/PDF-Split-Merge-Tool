import os
import sys
import argparse

from pdf_tool.core import (
    split_pdf_by_pages,
    split_pdf_by_size,
    merge_pdfs,
    ensure_output_dir,
)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="PDF分割与合并工具")
    parser.add_argument("input_pdfs", nargs="+", help="输入的PDF文件路径。单个文件用于分割，多个文件用于合并。")
    parser.add_argument("-m", "--merge", action="store_true", help="合并多个PDF文件")
    parser.add_argument("-s", "--size", type=float, help="按大小分割的最大文件大小 (MB)，支持小数")
    parser.add_argument("-p", "--pages", type=int, help="按页数分割的每个文件的页数")
    parser.add_argument("-o", "--output", help="输出目录，默认与输入PDF相同", default=None)
    parser.add_argument("-f", "--filename", help="合并后的输出文件名，仅在合并时使用", default=None)

    args = parser.parse_args()

    if args.merge:
        if len(args.input_pdfs) < 2:
            print("合并操作需要至少两个PDF文件。")
            sys.exit(1)
        fallback = os.path.dirname(os.path.abspath(args.input_pdfs[0]))
        output_dir = ensure_output_dir(args.output, fallback)
        success, message = merge_pdfs(args.input_pdfs, output_dir, args.filename)
        print(message)
        if not success:
            sys.exit(1)
    else:
        if len(args.input_pdfs) != 1:
            print("分割操作需要一个输入PDF文件。")
            sys.exit(1)

        input_pdf = args.input_pdfs[0]
        if not os.path.exists(input_pdf):
            print("输入的PDF文件不存在!")
            sys.exit(1)

        fallback = os.path.dirname(os.path.abspath(input_pdf))
        output_dir = ensure_output_dir(args.output, fallback)

        if args.size:
            success, message = split_pdf_by_size(input_pdf, output_dir, args.size)
        elif args.pages:
            success, message = split_pdf_by_pages(input_pdf, output_dir, args.pages)
        else:
            print("请提供分割方式：按页数(-p)或按大小(-s)。")
            sys.exit(1)
        print(message)
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
