# Copyright (c) Opendatalab. All rights reserved.
"""
ah21 定制入口：在最新 RapidDoc demo 结构上，使用本地 ah21 模块：
- layered_pdf_pypdf_ah21（双层 PDF，支持 CJK 字体 / ignore block types）
- pipeline_middle_json_mkcontent_ah21（脚注 / 页码）
并额外支持 lang、f_create_layered_pdf 等参数。
"""
import copy
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
# ============== 设备配置 ==============
# 使用默认 GPU（cuda:0）
# os.environ['MINERU_DEVICE_MODE'] = "cuda"
# # 或指定 GPU 编号，例如使用第二块 GPU（cuda:1）
# os.environ['MINERU_DEVICE_MODE'] = "cuda:1"
# os.environ['MINERU_LAYOUT_ORIGINAL_IMAGE'] = "true"
# 是否启用图片方向矫正，开启后，可以自动识别并矫正 90°、270°的图片
# os.environ['USE_DOC_ORIENTATION_CLASSIFY'] = "true"
# # 模型文件存储目录
# os.environ['RAPID_MODELS_DIR'] = r'D:\CodeProjects\doc\RapidAI\models' #模型文件存储目录，如果不设置会默认下载到rapid_doc项目里面
from loguru import logger

from rapid_doc.data.data_reader_writer import FileBasedDataWriter
from rapid_doc.utils.draw_bbox import draw_layout_bbox, draw_span_bbox
from rapid_doc.utils.layered_pdf_pypdf_ah21 import create_layered_searchable_pdf
from rapid_doc.utils.enum_class import MakeMode
from rapid_doc.utils.config_reader import get_processing_window_size
from rapid_doc.utils.guess_suffix_or_lang import guess_suffix_by_bytes, guess_suffix_by_path
from rapid_doc.utils.office_converter import convert_legacy_office_to_modern
from rapid_doc.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, read_fn, office_suffixes, old_office_suffixes


def prepare_env(output_dir, pdf_file_name, parse_method=None):
    """创建输出目录：output_dir/pdf_file_name（不再按 parse_method 分子目录）。"""
    local_md_dir = str(os.path.join(output_dir, pdf_file_name))
    local_image_dir = os.path.join(local_md_dir, "images")
    os.makedirs(local_image_dir, exist_ok=True)
    os.makedirs(local_md_dir, exist_ok=True)
    return local_image_dir, local_md_dir
from rapid_doc.backend.office.office_analyze import office_analyze
from rapid_doc.backend.office.office_middle_json_mkcontent import union_make as office_union_make
from rapid_doc.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
from rapid_doc.backend.pipeline.pipeline_middle_json_mkcontent_ah21 import union_make as pipeline_union_make
from rapid_doc.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json


def _normalize_lang_list(lang: str | list[str] | None, n_docs: int) -> list[str] | None:
    """将 lang 归一化为与文档数等长的列表；None 表示使用管线默认。"""
    if lang is None:
        return None
    if isinstance(lang, str):
        return [lang] * n_docs
    if len(lang) != n_docs:
        raise ValueError(
            f"lang 为列表时须与文档数量一致：len(lang)={len(lang)}，文档数={n_docs}"
        )
    return list(lang)


def do_parse(
    output_dir,  # Output directory for storing parsing results
    pdf_file_names: list[str],  # List of PDF file names to be parsed
    pdf_bytes_list: list[bytes],  # List of PDF bytes to be parsed
    parse_method="auto",  # The method for parsing PDF, default is 'auto'
    p_formula_enable=True,  # Enable formula parsing
    p_table_enable=True,  # Enable table parsing
    f_draw_layout_bbox=True,  # Whether to draw layout bounding boxes
    f_draw_span_bbox=True,  # Whether to draw span bounding boxes
    f_create_layered_pdf=True,  # Whether to create layered PDF (ah21)
    f_dump_md=True,  # Whether to dump markdown files
    f_dump_middle_json=False,  # Whether to dump middle JSON files
    f_dump_model_output=False,  # Whether to dump model output files
    f_dump_orig_pdf=False,  # Whether to dump original PDF files
    f_dump_content_list=False,  # Whether to dump content list files
    f_dump_md_html=False,  # Whether to convert markdown to HTML
    f_dump_md_docx=False,  # Whether to convert markdown to docx (via Pandoc)
    f_make_md_mode=MakeMode.MM_MD,  # The mode for making markdown content, default is MM_MD
    start_page_id=0,  # Start page ID for parsing, default is 0
    end_page_id=None,  # End page ID for parsing, default is None (parse all pages until the end of the document)
    f_include_footnotes=True,  # Whether to include footnotes in markdown output (ah21)
    f_include_page_numbers=True,  # Whether to include page number markers in markdown output (ah21)
    lang: str | list[str] | None = None,  # 单文档 str / 多文档等长 list；None=管线默认 ch
):
    layout_config, ocr_config, formula_config, table_config, checkbox_config, image_config = _build_config()
    need_remove_index = _process_office_doc(
        output_dir,
        pdf_file_names=pdf_file_names,
        pdf_bytes_list=pdf_bytes_list,
        f_dump_md=f_dump_md,
        f_dump_middle_json=f_dump_middle_json,
        f_dump_model_output=f_dump_model_output,
        f_dump_orig_file=f_dump_orig_pdf,
        f_dump_content_list=f_dump_content_list,
        f_make_md_mode=f_make_md_mode,
        f_dump_md_html=f_dump_md_html,
        f_dump_md_docx=f_dump_md_docx,
    )
    for index in sorted(need_remove_index, reverse=True):
        del pdf_bytes_list[index]
        del pdf_file_names[index]
    if not pdf_bytes_list:
        logger.warning("No valid PDF or image files to process.")
        return

    for idx, pdf_bytes in enumerate(pdf_bytes_list):
        if start_page_id != 0 or end_page_id is not None:
            new_pdf_bytes = convert_pdf_bytes_to_bytes_by_pypdfium2(pdf_bytes, start_page_id, end_page_id)
            pdf_bytes_list[idx] = new_pdf_bytes
    pdf_pages_batch = get_processing_window_size(default=64)
    lang_list = _normalize_lang_list(lang, len(pdf_bytes_list))

    _process_pipeline_docs_in_batches(
        output_dir=output_dir,
        pdf_file_names=pdf_file_names,
        pdf_bytes_list=pdf_bytes_list,
        parse_method=parse_method,
        p_formula_enable=p_formula_enable,
        p_table_enable=p_table_enable,
        f_draw_layout_bbox=f_draw_layout_bbox,
        f_draw_span_bbox=f_draw_span_bbox,
        f_dump_md=f_dump_md,
        f_dump_middle_json=f_dump_middle_json,
        f_dump_model_output=f_dump_model_output,
        f_dump_orig_pdf=f_dump_orig_pdf,
        f_dump_content_list=f_dump_content_list,
        f_dump_md_html=f_dump_md_html,
        f_dump_md_docx=f_dump_md_docx,
        f_make_md_mode=f_make_md_mode,
        layout_config=layout_config,
        ocr_config=ocr_config,
        formula_config=formula_config,
        table_config=table_config,
        checkbox_config=checkbox_config,
        image_config=image_config,
        pdf_pages_batch=pdf_pages_batch,
        f_create_layered_pdf=f_create_layered_pdf,
        f_include_footnotes=f_include_footnotes,
        f_include_page_numbers=f_include_page_numbers,
        lang_list=lang_list,
    )


def _process_pipeline_docs_in_batches(
        output_dir,
        pdf_file_names,
        pdf_bytes_list,
        parse_method,
        p_formula_enable,
        p_table_enable,
        f_draw_layout_bbox,
        f_draw_span_bbox,
        f_dump_md,
        f_dump_middle_json,
        f_dump_model_output,
        f_dump_orig_pdf,
        f_dump_content_list,
        f_dump_md_html,
        f_dump_md_docx,
        f_make_md_mode,
        layout_config,
        ocr_config,
        formula_config,
        table_config,
        checkbox_config,
        image_config,
        pdf_pages_batch,
        f_create_layered_pdf=True,
        f_include_footnotes=True,
        f_include_page_numbers=True,
        lang_list=None,
):
    local_image_dirs = []
    local_md_dirs = []
    image_writers = []
    md_writers = []
    for pdf_file_name in pdf_file_names:
        local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
        local_image_dirs.append(local_image_dir)
        local_md_dirs.append(local_md_dir)
        image_writers.append(FileBasedDataWriter(local_image_dir))
        md_writers.append(FileBasedDataWriter(local_md_dir))

    tmp_start_page_id = 0
    batch_idx = 0
    middle_json_list = [None] * len(pdf_bytes_list)
    model_json_list = [[] if f_dump_model_output else None for _ in pdf_bytes_list]
    finished = [False] * len(pdf_bytes_list)

    while not all(finished):
        active_indexes = [idx for idx, is_finished in enumerate(finished) if not is_finished]
        active_pdf_bytes_list = [pdf_bytes_list[idx] for idx in active_indexes]
        active_lang_list = (
            [lang_list[idx] for idx in active_indexes] if lang_list is not None else None
        )
        infer_results, all_image_lists, all_page_dicts, out_lang_list, ocr_enabled_list, file_end_list = pipeline_doc_analyze(
            active_pdf_bytes_list,
            lang_list=active_lang_list,
            parse_method=parse_method,
            formula_enable=p_formula_enable,
            table_enable=p_table_enable,
            layout_config=layout_config,
            ocr_config=ocr_config,
            formula_config=formula_config,
            table_config=table_config,
            checkbox_config=checkbox_config,
            start_page_id=tmp_start_page_id,
            end_page_id=None,
            pdf_pages_batch=pdf_pages_batch,
        )

        for active_idx, model_list in enumerate(infer_results):
            original_idx = active_indexes[active_idx]
            if f_dump_model_output:
                model_json_list[original_idx].extend(copy.deepcopy(model_list))

            tmp_middle_json = pipeline_result_to_middle_json(
                model_list,
                all_image_lists[active_idx],
                all_page_dicts[active_idx],
                image_writers[original_idx],
                out_lang_list[active_idx],
                ocr_enabled_list[active_idx],
                p_formula_enable,
                ocr_config=ocr_config,
                image_config=image_config,
                batch_idx=batch_idx,
                pdf_pages_batch=pdf_pages_batch,
            )
            if middle_json_list[original_idx] is None:
                middle_json_list[original_idx] = tmp_middle_json
            else:
                middle_json_list[original_idx]["pdf_info"].extend(tmp_middle_json["pdf_info"])

            if file_end_list[active_idx]:
                pdf_file_name = pdf_file_names[original_idx]
                _process_output(
                    middle_json_list[original_idx]["pdf_info"],
                    pdf_bytes_list[original_idx],
                    pdf_file_name,
                    local_md_dirs[original_idx],
                    local_image_dirs[original_idx],
                    md_writers[original_idx],
                    f_draw_layout_bbox,
                    f_draw_span_bbox,
                    f_dump_orig_pdf,
                    f_dump_md,
                    f_dump_content_list,
                    f_dump_middle_json,
                    f_dump_model_output,
                    f_make_md_mode,
                    middle_json_list[original_idx],
                    model_json_list[original_idx],
                    process_mode="pipeline",
                    f_dump_md_html=f_dump_md_html,
                    f_dump_md_docx=f_dump_md_docx,
                    f_create_layered_pdf=f_create_layered_pdf,
                    f_include_footnotes=f_include_footnotes,
                    f_include_page_numbers=f_include_page_numbers,
                    layout_config=layout_config,
                )
                finished[original_idx] = True
            elif not model_list:
                logger.warning(f"No pages parsed for {pdf_file_names[original_idx]}, stop batch processing.")
                finished[original_idx] = True

        tmp_start_page_id += pdf_pages_batch
        batch_idx += 1


def _build_config():
    from rapidocr import EngineType as OCREngineType, OCRVersion, ModelType as OCRModelType
    from rapid_doc.model.layout.rapid_layout_self import ModelType as LayoutModelType
    from rapid_doc.model.formula.rapid_formula_self import ModelType as FormulaModelType, EngineType as FormulaEngineType
    from rapid_doc.model.table.rapid_table_self import ModelType as TableModelType, EngineType as TableEngineType
    from rapid_doc.model.custom.paddleocr_vl.paddleocr_vl import PaddleOCRVLTableModel, PaddleOCRVLOCRModel, PaddleOCRVLFormulaModel
    layout_config = {
        # "model_type": LayoutModelType.PP_DOCLAYOUTV3,
        # "conf_thresh": 0.4,
        # "batch_num": 1,
        # "model_dir_or_path": r"C:\ocr\models\ppmodel\layout\PP-DocLayoutV3\pp_doclayoutv3.onnx",
        # "markdown_ignore_labels": ["number", "footnote", "header", "header_image", "footer", "footer_image", "aside_text",],
        # 双层 PDF 文本层：不写入以下 block 类型的文字（与 markdown_ignore_labels 类似）
        # "layered_pdf_ignore_block_types": ["image_footnote", "table_footnote", "image_caption", "table_caption"],
        # 图版 PDF 建议配置 CJK 字体路径，否则中文可能显示为错误字符
        "layered_pdf_cjk_font_path": r"C:\Windows\Fonts\msyh.ttc",
    }

    ocr_config = {
        # "custom_model": PaddleOCRVLOCRModel(),
        # "Det.model_path": r"C:\ocr\models\ppmodel\ocr\v4\ch_PP-OCRv4_det_infer\openvino\ch_PP-OCRv4_det_infer.onnx",
        # "Rec.model_path": r"C:\ocr\models\ppmodel\ocr\v4\ch_PP-OCRv4_rec_infer\openvino\ch_PP-OCRv4_rec_infer.onnx",
        # "Rec.rec_batch_num": 1,

        # ah21：可按需固定 OCR 版本
        # "Det.ocr_version": OCRVersion.PPOCRV6,
        # "Rec.ocr_version": OCRVersion.PPOCRV6,
        # "Det.model_type": OCRModelType.SERVER,
        # "Rec.model_type": OCRModelType.SERVER,

        # 新增的自定义参数
        # "engine_type": OCREngineType.TORCH, # 统一设置推理引擎
        # "Det.rec_batch_num": 8, # Det批处理大小

        # 文本检测框模式：auto（默认）、txt、ocr
        # "use_det_mode": 'auto' #（1、txt只会从pypdfium2获取文本框，保留pdf中的图片，2、ocr只会从OCR-det获取文本框，3、auto先从pypdfium2获取文本框，提取不到再使用OCR-det提取）
    }

    formula_config = {
        # "custom_model": PaddleOCRVLFormulaModel(),
        # "model_type": FormulaModelType.PP_FORMULANET_PLUS_M,
        # "engine_type": FormulaEngineType.TORCH,
        # "formula_level": 1, # 公式识别等级，默认为0，全识别。1:仅识别行间公式，行内公式不识别
        # "batch_num": 1,
        # "model_dir_or_path": r"C:\ocr\models\ppmodel\formula\PP-FormulaNet_plus-S\pp_formulanet_plus_s.onnx",
        # "dict_keys_path": "D:\CodeProjects\doc\RapidAI\model\pp_formulanet_plus_m_inference.yml", #yml字典路径（torch使用）
    }

    table_config = {
        # "use_rule_table": True, # 非 OCR PDF 的高置信度有线表格优先使用 PDFium 原生字符与矢量线解析
        # "rule_table_score_threshold": 0.90, # 规则 HTML 低于该分数时回退当前配置的表格模型
        # "custom_model": PaddleOCRVLTableModel(),
        # "force_ocr": False, # 表格文字，是否强制使用ocr，默认 False 根据 parse_method 来判断是否需要ocr还是从pdf中直接提取文本
        # 注：文字版pdf可以使用pypdfium2提取到表格内图片，扫描版或图片需要使用PP_DOCLAYOUT_PLUS_L/PP_DOCLAYOUTV2版面识别模型，才能识别到表格内的图片
        # "skip_text_in_image": True, # 是否跳过表格里图片中的文字（如表格单元格中嵌入的图片、图标、扫描底图等）
        # "use_img2table": False, # 是否优先使用img2table库提取表格，需要手动安装（pip install img2table），基于opencv识别准确度不如使用模型，但是速度很快，默认关闭

        # "model_type": TableModelType.SLANETPLUS,
        # "model_type": TableModelType.UNET_SLANET_PLUS,  # （默认） 有线表格使用unet，无线表格使用slanet_plus
        # "model_type": TableModelType.UNET_UNITABLE, # 有线表格使用unet，无线表格使用unitable
        # "model_type": TableModelType.UNITABLE,
        # "model_dir_or_path": "", #单个模型使用。如SLANET_PLUS、UNITABLE

        # "use_word_box": True, # 使用单字坐标匹配单元格，默认 True
        # "use_compare_table": False,  # 启用表格结果比较（同时跑有线/无线并比对），默认 False
        # "table_formula_enable": False, # 表格内公式识别
        # "table_image_enable": False, # 表格内图片识别
        # "extract_original_image": False # 是否提取表格内原始图片，默认 False
        # "cls.model_type": TableModelType.PADDLE_Q_CLS, # 表格分类模型
        # "cls.model_dir_or_path": "", # 表格分类模型地址
        # "unet.model_dir_or_path": "", # UNET表格模型地址
        # "unitable.model_dir_or_path": "", # UNITABLE表格模型地址
        # "slanet_plus.model_dir_or_path": "", # SLANET_PLUS表格模型地址

        # "engine_type": TableEngineType.ONNXRUNTIME,  # 统一设置推理引擎
    }

    checkbox_config = {
        # "checkbox_enable": True, # 是否识别复选框，默认不识别，基于opencv，有可能会误检
    }

    # 版面识别元素为图片的配置
    image_config = {
        # "extract_original_image": True, # 是否提取原始图片（使用 pypdfium2 提取原始图片。截图可能导致清晰度降低和边界丢失，默认关闭）
        # "extract_original_image_iou_thresh": 0.5, # 是否提取原始图片和版面识别的图片，bbox重叠度，默认0.9
    }
    return layout_config, ocr_config, formula_config, table_config, checkbox_config, image_config


def _process_office_doc(
        output_dir,
        pdf_file_names: list[str],
        pdf_bytes_list: list[bytes],
        f_dump_md=True,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_dump_orig_file=False,
        f_dump_content_list=False,
        f_make_md_mode=MakeMode.MM_MD,
        f_dump_md_html=False,
        f_dump_md_docx=False,
):
    need_remove_index = []
    for i, file_bytes in enumerate(pdf_bytes_list):
        pdf_file_name = pdf_file_names[i]
        file_suffix = guess_suffix_by_bytes(file_bytes)
        if file_suffix in office_suffixes:

            need_remove_index.append(i)

            local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name)
            image_writer, md_writer = FileBasedDataWriter(local_image_dir), FileBasedDataWriter(local_md_dir)
            middle_json, infer_result = office_analyze(
                file_bytes,
                image_writer=image_writer,
            )

            f_draw_layout_bbox = False
            f_draw_span_bbox = False
            pdf_info = middle_json["pdf_info"]

            _process_output(
                pdf_info, file_bytes, pdf_file_name, local_md_dir, local_image_dir,
                md_writer, f_draw_layout_bbox, f_draw_span_bbox, f_dump_orig_file,
                f_dump_md, f_dump_content_list, f_dump_middle_json, f_dump_model_output,
                f_make_md_mode, middle_json, infer_result, process_mode=file_suffix,
                f_dump_md_html=f_dump_md_html, f_dump_md_docx=f_dump_md_docx,
                f_create_layered_pdf=False,
            )

    return need_remove_index


def _process_output(
        pdf_info,
        pdf_bytes,
        pdf_file_name,
        local_md_dir,
        local_image_dir,
        md_writer,
        f_draw_layout_bbox,
        f_draw_span_bbox,
        f_dump_orig_pdf,
        f_dump_md,
        f_dump_content_list,
        f_dump_middle_json,
        f_dump_model_output,
        f_make_md_mode,
        middle_json,
        model_output=None,
        process_mode="pipeline",
        f_dump_md_html=False,
        f_dump_md_docx=False,
        f_create_layered_pdf=True,
        f_include_footnotes=True,
        f_include_page_numbers=True,
        layout_config=None,
):
    if isinstance(pdf_bytes, dict):
        pdf_bytes = pdf_bytes["pdf_bytes"]
    if process_mode == "pipeline":
        make_func = pipeline_union_make
    elif process_mode in office_suffixes:
        make_func = office_union_make
    else:
        raise Exception(f"Unknown process_mode: {process_mode}")

    """处理输出文件"""
    if f_draw_layout_bbox:
        draw_layout_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_layout.pdf")

    if f_draw_span_bbox:
        draw_span_bbox(pdf_info, pdf_bytes, local_md_dir, f"{pdf_file_name}_span.pdf")

    if f_create_layered_pdf and process_mode in ["pipeline", "vlm"]:
        layout_config = layout_config or {}
        create_layered_searchable_pdf(
            pdf_info,
            pdf_bytes,
            local_md_dir,
            f"{pdf_file_name}_layered.pdf",
            layered_pdf_ignore_block_types=layout_config.get("layered_pdf_ignore_block_types"),
            layered_pdf_cjk_font_path=layout_config.get("layered_pdf_cjk_font_path"),
        )

    if f_dump_orig_pdf:
        if process_mode in ["pipeline", "vlm"]:
            md_writer.write(
                f"{pdf_file_name}_origin.pdf",
                pdf_bytes,
            )
        elif process_mode in office_suffixes:
            md_writer.write(
                f"{pdf_file_name}_origin.{process_mode}",
                pdf_bytes,
            )

    image_dir = str(os.path.basename(local_image_dir))

    if f_dump_md:
        if process_mode == "pipeline":
            md_content_str = make_func(
                pdf_info,
                f_make_md_mode,
                image_dir,
                include_footnotes=f_include_footnotes,
                include_page_numbers=f_include_page_numbers,
            )
        else:
            md_content_str = make_func(pdf_info, f_make_md_mode, image_dir)
        if md_content_str is not None:
            md_writer.write_string(
                f"{pdf_file_name}.md",
                md_content_str if isinstance(md_content_str, str) else str(md_content_str),
            )

        # ===================== Markdown 转 HTML =====================
        if f_dump_md_html and md_content_str:
            try:
                from rapid_doc.utils.markdown_to_html import markdown_to_html
                html_path = os.path.join(local_md_dir, f"{pdf_file_name}.html")
                markdown_to_html(
                    md_content_str,
                    output_path=html_path,
                    title=pdf_file_name,
                    image_base_path=local_md_dir,  # 图片相对于md目录
                    embed_images=False,  # 不嵌入图片，保持引用
                )
            except ImportError as e:
                logger.warning(f"Markdown转HTML失败: {e}")
            except Exception as e:
                logger.error(f"Markdown转HTML失败: {e}")

        # ===================== Markdown 转 docx (via Pandoc) =====================
        if f_dump_md_docx and md_content_str:
            try:
                from rapid_doc.utils.markdown_to_word import markdown_to_docx
                md_docx_path = os.path.join(local_md_dir, f"{pdf_file_name}_md.docx")
                markdown_to_docx(
                    md_content_str,
                    output_path=md_docx_path,
                    image_base_path=local_md_dir,  # 图片相对于md目录
                )
            except ImportError as e:
                logger.warning(f"Markdown转docx失败: {e}")
            except Exception as e:
                logger.error(f"Markdown转docx失败: {e}")

    if f_dump_content_list:
        content_list = make_func(pdf_info, MakeMode.CONTENT_LIST, image_dir)
        md_writer.write_string(
            f"{pdf_file_name}_content_list.json",
            json.dumps(content_list, ensure_ascii=False, indent=4),
        )
        if process_mode != "pipeline":
            content_list_v2 = make_func(pdf_info, MakeMode.CONTENT_LIST_V2, image_dir)
            md_writer.write_string(
                f"{pdf_file_name}_content_list_v2.json",
                json.dumps(content_list_v2, ensure_ascii=False, indent=4),
            )

    if f_dump_middle_json:
        md_writer.write_string(
            f"{pdf_file_name}_middle.json",
            json.dumps(middle_json, ensure_ascii=False, indent=4),
        )

    if f_dump_model_output:
        md_writer.write_string(
            f"{pdf_file_name}_model.json",
            json.dumps(model_output, ensure_ascii=False, indent=4),
        )

    logger.info(f"local output dir is {local_md_dir}")


def parse_doc(
        path_list: list[Path],
        output_dir,
        method="auto",
        start_page_id=0,  # Start page ID for parsing, default is 0
        end_page_id=None,  # End page ID for parsing, default is None (parse all pages until the end of the document)
        f_include_footnotes=True,  # Whether to include footnotes in markdown output, default is True
        f_include_page_numbers=True,  # Whether to include page number markers in markdown output, default is True
        lang: str | list[str] | None = None,
):
    """
        Parameter description:
        path_list: List of document paths to be parsed, can be PDF or image files.
        output_dir: Output directory for storing parsing results.
        method: the method for parsing pdf:
            auto: Automatically determine the method based on the file type.
            txt: Use text extraction method.
            ocr: Use OCR method for image-based PDFs.
            Without method specified, 'auto' will be used by default.
        lang: OCR/版面管线语言代码（如 ch、en）；多文件时传入与 path_list 等长的列表；None 时使用管线默认（通常为 ch）。
    """
    try:
        file_name_list = []
        pdf_bytes_list = []
        for path in path_list:
            file_suffix = guess_suffix_by_path(path)
            if file_suffix in old_office_suffixes:
                path = convert_legacy_office_to_modern(path)
            file_name = str(Path(path).stem)
            pdf_bytes = read_fn(path)
            file_name_list.append(file_name)
            pdf_bytes_list.append(pdf_bytes)
        do_parse(
            output_dir=output_dir,
            pdf_file_names=file_name_list,
            pdf_bytes_list=pdf_bytes_list,
            parse_method=method,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            f_include_footnotes=f_include_footnotes,
            f_include_page_numbers=f_include_page_numbers,
            lang=lang,
        )
    except Exception as e:
        logger.exception(e)


if __name__ == '__main__':
    doc_path_list = [
r"E:\语文出版社\2026\小古文项目\图书\最终整理\走进小古文阅读与训练\走进小古文阅读与训练-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\走进小古文文言文字词句入门\走进小古文文言文字词句入门-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\中学文言文必考140字\中学文言文必考140字-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\中考课内外文言文\中考课内外文言文-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\与经典面对面.高中课外文言文精选精练精讲先秦两汉篇\与经典面对面.高中课外文言文精选精练精讲先秦两汉篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\与经典面对面.高中课外文言文精选精练精讲唐宋篇\与经典面对面.高中课外文言文精选精练精讲唐宋篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\与经典面对面.高中课外文言文精选精练精讲明清篇\与经典面对面.高中课外文言文精选精练精讲明清篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\一天一篇小古文卷一春生\一天一篇小古文卷一春生h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\一天一篇小古文卷四冬藏\一天一篇小古文卷四冬藏h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\一天一篇小古文卷三秋收\一天一篇小古文卷三秋收h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\一天一篇小古文卷二夏长\一天一篇小古文卷二夏长h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\一本文言文完全解读高中\一本文言文完全解读高中-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\一本高中文言文基础知识手册\一本高中文言文基础知识手册-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学生必诵古文240篇中册(三、四年级)\小学生必诵古文240篇中册(三、四年级)h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学生必诵古文240篇下册(五、六年级)\小学生必诵古文240篇下册(五、六年级)h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学生必读文言文知识水平检测题\小学生必读文言文知识水平检测题-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学生必读文言文\小学生必读文言文-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学生必背文言文\小学生必背文言文-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学必背文言文一百篇下\小学必背文言文一百篇下-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学必背文言文一百篇上\小学必背文言文一百篇上-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学必背文言文一百篇背诵打卡本下\小学必背文言文一百篇背诵打卡本下-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小学必背文言文一百篇背诵打卡本上\小学必背文言文一百篇背诵打卡本上-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小升初文言文模块专训\小升初文言文模块专训-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小升初文言文\小升初文言文-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文一百篇\小古文一百篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文漫画笔记幽默\小古文漫画笔记幽默-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文漫画笔记趣文\小古文漫画笔记趣文-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文漫画笔记启示\小古文漫画笔记启示-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文漫画笔记名人\小古文漫画笔记名人-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文分层训练五年级\小古文分层训练五年级h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\小古文分层训练三年级\小古文分层训练三年级h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\文言文一百篇\文言文一百篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\文言文考试阅读六年级\文言文考试阅读六年级-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\口袋里的小古文\口袋里的小古文-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\课外文言文七年级\课外文言文七年级-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\课外文言文九年级+中考\课外文言文九年级+中考-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\课外文言文八年级\课外文言文八年级-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\开心语文文言文全解初中\开心语文文言文全解初中-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\开心语文必背小古文小学\开心语文必背小古文小学-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\绝妙好文念楼学短选读\绝妙好文念楼学短选读-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\古史文言今论高考文言文全景解读上编\古史文言今论高考文言文全景解读上编-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\跟小古文学作文3人物篇\跟小古文学作文3人物篇h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\高中文言文全解一本通\高中文言文全解一本通-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\高中文言文全解\高中文言文全解-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\高中必背古代文化常识\高中必背古代文化常识-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\蝶变语文高中必背古诗文全解\蝶变语文高中必背古诗文全解-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\蝶变语文.18天巧记高中文言文必背词\蝶变语文.18天巧记高中文言文必背词-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文元明清篇\穿越历史线学透小古文元明清篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文唐宋篇\穿越历史线学透小古文唐宋篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文三国两晋南北朝篇\穿越历史线学透小古文三国两晋南北朝篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文秦汉篇\穿越历史线学透小古文秦汉篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文练习册元明篇\穿越历史线学透小古文练习册元明篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文练习册唐宋篇\穿越历史线学透小古文练习册唐宋篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文练习册三国两晋南北朝篇\穿越历史线学透小古文练习册三国两晋南北朝篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文练习册秦汉篇\穿越历史线学透小古文练习册秦汉篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文练习册春秋战国篇\穿越历史线学透小古文练习册春秋战国篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\穿越历史线学透小古文春秋战国篇\穿越历史线学透小古文春秋战国篇-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\初中必背文言文漫画笔记中阶\初中必背文言文漫画笔记中阶-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\初中必背文言文漫画笔记高阶\初中必背文言文漫画笔记高阶-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\初中必背文言文漫画笔记初阶\初中必背文言文漫画笔记初阶-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\初中必背文言文背诵纯享版\初中必背文言文背诵纯享版-h.pdf",
# r"E:\语文出版社\2026\小古文项目\图书\最终整理\2026初中文言文完全解读7-9年级\2026初中文言文完全解读7-9年级-h.pdf",
            ]
    for doc_path in doc_path_list:
        start_time = time.time()
        # 运行方式：auto/txt/ocr
        METHOD = "auto"
        # 语言：ch chinese_cht en korean japan ta te ka
        LANG = None
        doc_path = Path(doc_path)
        # 默认输出到 PDF 同目录下的同名文件夹
        output_dir = str(doc_path.parent)
        parse_doc([doc_path], output_dir, method=METHOD, lang=LANG)
        print(f"总运行时间: {time.time() - start_time}秒")
