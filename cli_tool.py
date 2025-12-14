#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RapidDoc 命令行工具
将PDF和图片文件转换为Markdown格式
"""
import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

from loguru import logger

from rapid_doc.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env, read_fn
from rapid_doc.data.data_reader_writer import FileBasedDataWriter
from rapid_doc.utils.draw_bbox import draw_layout_bbox, draw_span_bbox
from rapid_doc.utils.enum_class import MakeMode
from rapid_doc.utils.pdf_searchable import create_searchable_pdf
from rapid_doc.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from rapid_doc.backend.pipeline.pipeline_middle_json_mkcontent_with_footnote import union_make as pipeline_union_make
from rapid_doc.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json

from rapid_doc.model.layout.rapid_layout_self import ModelType as LayoutModelType
from rapid_doc.model.formula.rapid_formula_self import ModelType as FormulaModelType
from rapid_doc.model.table.rapid_table_self import ModelType as TableModelType
from rapidocr import ModelType as OCRModelType


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='RapidDoc - PDF和图片转Markdown工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s input.pdf -o output/
  %(prog)s input.pdf -o output/ --batch-num 1
  %(prog)s input.pdf input2.pdf -o output/ --method txt
  %(prog)s input.pdf input2.pdf -o output/ --method ocr
  %(prog)s input.pdf -o output/ --start-page 0 --end-page 10
  %(prog)s input.pdf -o output/ --no-formula --no-table
  %(prog)s input.pdf -o output/ --searchable-pdf
        """
    )

    # 必需参数
    parser.add_argument(
        'input_files',
        nargs='+',
        type=str,
        help='要处理的PDF或图片文件路径（支持多个文件）'
    )

    parser.add_argument(
        '-o', '--output',
        dest='output_dir',
        required=True,
        type=str,
        help='输出目录'
    )

    # 解析方法
    parser.add_argument(
        '-m', '--method',
        dest='parse_method',
        choices=['auto', 'txt', 'ocr'],
        default='auto',
        help='解析方法: auto(自动), txt(文本提取), ocr(OCR识别). 默认: auto'
    )

    # 页面范围
    parser.add_argument(
        '--start-page',
        dest='start_page_id',
        type=int,
        default=0,
        help='起始页码（从0开始）. 默认: 0'
    )

    parser.add_argument(
        '--end-page',
        dest='end_page_id',
        type=int,
        default=None,
        help='结束页码（包含）. 默认: None（处理到文档末尾）'
    )

    # 功能开关
    parser.add_argument(
        '--no-formula',
        dest='formula_enable',
        action='store_false',
        default=True,  # 默认启用公式识别
        help='禁用公式识别'
    )

    parser.add_argument(
        '--no-table',
        dest='table_enable',
        action='store_false',
        default=True,  # 默认启用表格识别
        help='禁用表格识别'
    )

    parser.add_argument(
        '--no-footnotes',
        dest='include_footnotes',
        action='store_false',
        default=True,  # 默认包含脚注
        help='不包含脚注'
    )

    parser.add_argument(
        '--no-page-numbers',
        dest='include_page_numbers',
        action='store_false',
        default=True,  # 默认包含页码标记
        help='不包含页码标记'
    )

    # 输出选项
    parser.add_argument(
        '--no-layout-bbox',
        dest='draw_layout_bbox',
        action='store_false',
        default=True,  # 默认生成版面边界框PDF
        help='不生成版面边界框PDF'
    )

    parser.add_argument(
        '--no-span-bbox',
        dest='draw_span_bbox',
        action='store_false',
        default=True,  # 默认生成span边界框PDF
        help='不生成span边界框PDF'
    )

    parser.add_argument(
        '--no-md',
        dest='dump_md',
        action='store_false',
        default=True,  # 默认生成Markdown文件
        help='不生成Markdown文件'
    )

    parser.add_argument(
        '--no-middle-json',
        dest='dump_middle_json',
        action='store_false',
        default=True,  # 默认生成中间JSON文件
        help='不生成中间JSON文件'
    )

    parser.add_argument(
        '--no-model-output',
        dest='dump_model_output',
        action='store_false',
        default=True,  # 默认生成模型输出JSON文件
        help='不生成模型输出JSON文件'
    )

    parser.add_argument(
        '--no-orig-pdf',
        dest='dump_orig_pdf',
        action='store_false',
        default=True,  # 默认保存原始PDF文件
        help='不保存原始PDF文件'
    )

    parser.add_argument(
        '--no-content-list',
        dest='dump_content_list',
        action='store_false',
        default=True,  # 默认生成内容列表JSON文件
        help='不生成内容列表JSON文件'
    )

    parser.add_argument(
        '--searchable-pdf',
        dest='create_searchable_pdf',
        action='store_true',
        default=False,  # 默认不生成可搜索PDF
        help='生成双层可搜索PDF（在原始PDF下方添加不可见文本层）'
    )

    # 日志选项
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='显示详细日志'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='仅显示错误信息'
    )

    parser.add_argument(
        '--batch-num',
        dest='batch_num',
        type=int,
        default=None,
        help='批处理大小（用于layout、OCR和formula模型，内存报错时从1开始尝试）. 默认: None（使用模型默认值）'
    )

    return parser.parse_args()


def setup_logging(verbose=False, quiet=False):
    """配置日志"""
    if quiet:
        logger.remove()
        logger.add(sys.stderr, level="ERROR")
    elif not verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
    # verbose模式使用默认配置（DEBUG级别）


def do_parse(
    output_dir,
    pdf_file_names: list[str],
    pdf_bytes_list: list[bytes],
    parse_method="auto",
    formula_enable=True,  # 默认启用公式识别，与命令行参数保持一致
    table_enable=True,
    f_draw_layout_bbox=True,
    f_draw_span_bbox=True,
    f_dump_md=True,
    f_dump_middle_json=True,
    f_dump_model_output=True,
    f_dump_orig_pdf=True,
    f_dump_content_list=True,
    f_make_md_mode=MakeMode.MM_MD,
    start_page_id=0,
    end_page_id=None,
    f_include_footnotes=True,
    f_include_page_numbers=True,
    batch_num=None,
    f_create_searchable_pdf=False,
):
    """执行解析任务"""
    layout_config = {
        "model_type": LayoutModelType.PP_DOCLAYOUT_PLUS_L,
    }
    if batch_num is not None:
        layout_config["batch_num"] = batch_num

    ocr_config = {
        # https://rapidai.github.io/RapidOCRDocs/main/model_list/
        # "Det.ocr_version": OCRVersion.PPOCRV5,
        # "Det.lang_type": LangDet.CH,简体中文、中文拼音、繁体中文、英文、日文
        # "Rec.ocr_version": OCRVersion.PPOCRV5,
        # "Rec.lang_type": LangDet.CH,简体中文、中文拼音、繁体中文、英文、日文
        # "Rec.ocr_version": OCRVersion.PPOCRV4,
        # "Rec.lang_type": LangDet.chinese_cht,中文繁体
        "Det.model_type": OCRModelType.MOBILE,  # MOBILE、SERVER
        "Rec.model_type": OCRModelType.MOBILE,  # MOBILE、SERVER
    }
    if batch_num is not None:
        ocr_config["Rec.rec_batch_num"] = batch_num
        ocr_config["Det.rec_batch_num"] = batch_num

    formula_config = {
        "model_type": FormulaModelType.PP_FORMULANET_PLUS_M,
    }
    if batch_num is not None:
        formula_config["batch_num"] = batch_num

    table_config = {}

    checkbox_config = {}

    image_config = {}

    # 预处理PDF字节数据（分页）
    for idx, pdf_bytes in enumerate(pdf_bytes_list):
        new_pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(
            pdf_bytes, start_page_id, end_page_id
        )
        pdf_bytes_list[idx] = new_pdf_bytes

    # 记录开始时间
    start_time = time.time()

    logger.info("开始解析文档...")
    infer_results, all_image_lists, all_page_dicts, lang_list, ocr_enabled_list = pipeline_doc_analyze(
        pdf_bytes_list,
        parse_method=parse_method,
        formula_enable=formula_enable,
        table_enable=table_enable,
        layout_config=layout_config,
        ocr_config=ocr_config,
        formula_config=formula_config,
        table_config=table_config,
        checkbox_config=checkbox_config
    )

    for idx, model_list in enumerate(infer_results):
        model_json = copy.deepcopy(model_list)
        pdf_file_name = pdf_file_names[idx]
        local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
        image_writer, md_writer = FileBasedDataWriter(local_image_dir), FileBasedDataWriter(local_md_dir)

        images_list = all_image_lists[idx]
        pdf_dict = all_page_dicts[idx]
        _lang = lang_list[idx]
        _ocr_enable = ocr_enabled_list[idx]

        logger.info(f"处理文件: {pdf_file_name}")
        middle_json = pipeline_result_to_middle_json(
            model_list, images_list, pdf_dict, image_writer,
            _lang, _ocr_enable, formula_enable,
            ocr_config=ocr_config, image_config=image_config
        )

        pdf_info = middle_json["pdf_info"]
        pdf_bytes = pdf_bytes_list[idx]

        if f_draw_layout_bbox:
            logger.debug("生成版面边界框PDF...")
            draw_layout_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_layout.pdf")

        if f_draw_span_bbox:
            logger.debug("生成span边界框PDF...")
            draw_span_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_span.pdf")

        if f_dump_orig_pdf:
            logger.debug("保存原始PDF...")
            md_writer.write(f"{pdf_file_name}_origin.pdf", pdf_bytes)

        if f_dump_md:
            logger.debug("生成Markdown文件...")
            image_dir = str(os.path.basename(local_image_dir))
            md_content_str = pipeline_union_make(
                pdf_info,
                f_make_md_mode,
                image_dir,
                include_footnotes=f_include_footnotes,
                include_page_numbers=f_include_page_numbers
            )
            if md_content_str is not None:
                md_writer.write_string(
                    f"{pdf_file_name}.md",
                    md_content_str if isinstance(md_content_str, str) else str(md_content_str),
                )

        if f_dump_content_list:
            logger.debug("生成内容列表JSON...")
            image_dir = str(os.path.basename(local_image_dir))
            content_list = pipeline_union_make(pdf_info, MakeMode.CONTENT_LIST, image_dir)
            md_writer.write_string(
                f"{pdf_file_name}_content_list.json",
                json.dumps(content_list, ensure_ascii=False, indent=4),
            )

        if f_dump_middle_json:
            logger.debug("生成中间JSON文件...")
            md_writer.write_string(
                f"{pdf_file_name}_middle.json",
                json.dumps(middle_json, ensure_ascii=False, indent=4),
            )

        if f_dump_model_output:
            logger.debug("生成模型输出JSON...")
            md_writer.write_string(
                f"{pdf_file_name}_model.json",
                json.dumps(model_json, ensure_ascii=False, indent=4),
            )

        if f_create_searchable_pdf:
            logger.debug("生成双层可搜索PDF...")
            searchable_pdf_path = os.path.join(local_md_dir, f"{pdf_file_name}_searchable.pdf")
            success = create_searchable_pdf(pdf_bytes, middle_json, searchable_pdf_path)
            if success:
                logger.info(f"可搜索PDF已生成: {searchable_pdf_path}")
            else:
                logger.warning(f"可搜索PDF生成失败，可能需要安装PyMuPDF: pip install pymupdf")

        logger.info(f"输出目录: {local_md_dir}")

    elapsed_time = time.time() - start_time
    logger.info(f"总处理时间: {elapsed_time:.2f}秒")


def main():
    """主函数"""
    args = parse_args()

    # 配置日志
    setup_logging(args.verbose, args.quiet)

    # 验证输入文件
    input_files = []
    for file_path in args.input_files:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"文件不存在: {file_path}")
            sys.exit(1)
        input_files.append(path)

    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 读取文件
    file_name_list = []
    pdf_bytes_list = []

    logger.info(f"读取 {len(input_files)} 个文件...")
    for path in input_files:
        try:
            file_name = path.stem
            pdf_bytes = read_fn(path)
            file_name_list.append(file_name)
            pdf_bytes_list.append(pdf_bytes)
            logger.info(f"已读取: {path.name}")
        except Exception as e:
            logger.error(f"读取文件失败 {path}: {e}")
            sys.exit(1)

    # 执行解析
    try:
        do_parse(
            output_dir=str(output_dir),
            pdf_file_names=file_name_list,
            pdf_bytes_list=pdf_bytes_list,
            parse_method=args.parse_method,
            formula_enable=args.formula_enable,
            table_enable=args.table_enable,
            f_draw_layout_bbox=args.draw_layout_bbox,
            f_draw_span_bbox=args.draw_span_bbox,
            f_dump_md=args.dump_md,
            f_dump_middle_json=args.dump_middle_json,
            f_dump_model_output=args.dump_model_output,
            f_dump_orig_pdf=args.dump_orig_pdf,
            f_dump_content_list=args.dump_content_list,
            start_page_id=args.start_page_id,
            end_page_id=args.end_page_id,
            f_include_footnotes=args.include_footnotes,
            f_include_page_numbers=args.include_page_numbers,
            batch_num=args.batch_num,
            f_create_searchable_pdf=args.create_searchable_pdf,
        )
        logger.info("处理完成！")
    except Exception as e:
        logger.exception(f"处理失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

