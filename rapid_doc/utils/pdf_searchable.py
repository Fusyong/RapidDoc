# -*- coding: utf-8 -*-
"""
生成双层可搜索PDF的工具函数
利用OCR识别的文本和坐标信息，在原始PDF下方添加不可见的文本层
"""
import json
from io import BytesIO
from typing import Dict, List, Any, Optional

from loguru import logger

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("PyMuPDF (fitz) 未安装，无法生成可搜索PDF。请运行: pip install pymupdf")


def extract_text_spans_from_middle_json(middle_json: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """
    从middle_json中提取每页的文本span信息（包含文本内容和坐标）

    Args:
        middle_json: 中间JSON数据，包含pdf_info字段

    Returns:
        每页的文本span列表，格式为: [[{bbox, content, ...}, ...], ...]
    """
    pages_spans = []

    if "pdf_info" not in middle_json:
        logger.warning("middle_json中缺少pdf_info字段")
        return pages_spans

    for page_info in middle_json["pdf_info"]:
        page_spans = []

        # 从preproc_blocks中提取文本
        for block in page_info.get("preproc_blocks", []):
            if block.get("type") in ["text", "title"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("content") and span.get("bbox"):
                            page_spans.append({
                                "bbox": span["bbox"],  # [x0, y0, x1, y1]
                                "content": span["content"],
                                "type": span.get("type", "text")
                            })

        # 从para_blocks中提取文本（包含更多处理后的信息）
        for block in page_info.get("para_blocks", []):
            if block.get("type") in ["text", "title", "ref_text"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("content") and span.get("bbox"):
                            # 避免重复添加相同的span
                            bbox = span["bbox"]
                            content = span["content"]
                            # 检查是否已存在相同的span
                            is_duplicate = False
                            for existing_span in page_spans:
                                if (existing_span["content"] == content and
                                    existing_span["bbox"] == bbox):
                                    is_duplicate = True
                                    break
                            if not is_duplicate:
                                page_spans.append({
                                    "bbox": bbox,
                                    "content": content,
                                    "type": span.get("type", "text")
                                })

        pages_spans.append(page_spans)

    return pages_spans


def logical_bbox_to_pymupdf_point(bbox: List[float], page_height: float) -> tuple:
    """
    将逻辑坐标系（左上角为原点）的bbox转换为PyMuPDF insert_text所需的坐标和旋转角度

    这个函数解决了PyMuPDF insert_text的坐标系统问题：
    - 输入bbox使用左上角为原点（与middle_json、draw_span_bbox等一致）
    - PyMuPDF内部会将坐标转换为PDF标准坐标系（左下角为原点）并进行旋转
    - 通过逆变换，使得文本最终显示在正确位置

    Args:
        bbox: [x0, y0, x1, y1] 左上角为原点的边界框坐标
        page_height: PDF页面高度（用于坐标转换）

    Returns:
        tuple: (x, y, rotate)
            - x: PyMuPDF insert_text的x坐标
            - y: PyMuPDF insert_text的y坐标
            - rotate: 旋转角度（度），用于补偿PyMuPDF内部的坐标旋转

    变换原理：
        1. bbox使用左上角为原点，文本基线位置为 (x0, y1)
        2. PyMuPDF内部会进行坐标转换和旋转，导致文本位置错误
        3. 通过逆变换：
           - x = page_height - y1  (y坐标翻转 + 轴交换)
           - y = x0                 (x坐标作为y)
           - rotate = -90           (逆时针旋转，补偿内部的顺时针旋转)
        4. 最终文本会正确显示在原始bbox位置
    """
    x0, y0, x1, y1 = bbox
    # 使用bbox的左边缘和底边作为文本基线位置
    baseline_y = y1  # bbox底部（左上角坐标系）

    # 坐标变换：补偿PyMuPDF内部的坐标系统转换和旋转
    # 这个变换是经过实际测试验证的，能够使文本正确显示在bbox位置
    x = page_height - baseline_y  # y坐标翻转 + 轴交换
    y = x0                        # x坐标作为y
    rotate = -90                  # 逆时针旋转90度，补偿内部的顺时针旋转

    return (x, y, rotate)


def _contains_cjk(text: str) -> bool:
    """
    检查文本是否包含CJK（中文、日文、韩文）字符

    Args:
        text: 要检查的文本

    Returns:
        bool: 是否包含CJK字符
    """
    for char in text:
        # 检查是否在CJK统一表意文字范围内
        if '\u4e00' <= char <= '\u9fff':  # 中文
            return True
        if '\u3040' <= char <= '\u309f':  # 日文平假名
            return True
        if '\u30a0' <= char <= '\u30ff':  # 日文片假名
            return True
        if '\uac00' <= char <= '\ud7a3':  # 韩文
            return True
    return False


def create_searchable_pdf(
    pdf_bytes: bytes,
    middle_json: Dict[str, Any],
    output_path: str,
    font_size: Optional[float] = None,
    font_name: Optional[str] = None
) -> bool:
    """
    创建双层可搜索PDF，在原始PDF下方添加不可见的文本层

    Args:
        pdf_bytes: 原始PDF的字节数据
        middle_json: 包含OCR识别结果的中间JSON数据
        output_path: 输出PDF文件路径
        font_size: 字体大小，如果为None则根据bbox高度自动计算
        font_name: 字体名称，如果为None则自动选择（包含中文时使用CJK字体）

    Returns:
        bool: 是否成功创建
    """
    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF未安装，无法生成可搜索PDF")
        return False

    try:
        # 打开原始PDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        # 提取文本span信息
        pages_spans = extract_text_spans_from_middle_json(middle_json)

        if len(pages_spans) != len(doc):
            logger.warning(f"页面数量不匹配: PDF有{len(doc)}页，JSON有{len(pages_spans)}页")

        # 预加载CJK字体（如果需要）
        cjk_font = None
        cjk_font_buffer = None
        try:
            cjk_font = fitz.Font("cjk")  # PyMuPDF内置的CJK字体
            cjk_font_buffer = cjk_font.buffer  # 获取字体缓冲区
        except Exception as e:
            logger.warning(f"无法加载CJK字体: {e}，中文文本可能无法正确显示")

        # 处理每一页
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            # page.rect使用左上角为原点，但insert_text的point参数使用左下角为原点
            # 获取页面尺寸（左上角坐标系）
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height  # 这是左上角坐标系的高度

            # 检查本页是否需要CJK字体
            page_needs_cjk = False
            if page_idx < len(pages_spans):
                for span in pages_spans[page_idx]:
                    if span.get("content") and _contains_cjk(span["content"]):
                        page_needs_cjk = True
                        break

            # 如果需要CJK字体，在页面上插入字体
            cjk_fontname = None
            if page_needs_cjk and cjk_font_buffer is not None:
                try:
                    cjk_fontname = "CJKFont"  # 在页面中使用的字体名称
                    page.insert_font(fontname=cjk_fontname, fontbuffer=cjk_font_buffer)
                except Exception as e:
                    logger.warning(f"第{page_idx + 1}页无法插入CJK字体: {e}")
                    cjk_fontname = None

            if page_idx < len(pages_spans):
                spans = pages_spans[page_idx]

                for span_idx, span in enumerate(spans):
                    bbox = span["bbox"]
                    content = span["content"]

                    if not content or not bbox:
                        continue

                    try:
                        # bbox是左上角为原点：[x0, y0, x1, y1]
                        # 其中y0是上边缘，y1是下边缘
                        x0, y0, x1, y1 = bbox
                        width = abs(x1 - x0)
                        height = abs(y1 - y0)

                        # 计算字体大小（如果未指定）
                        if font_size is None:
                            # 根据bbox高度估算字体大小，留一些边距
                            estimated_font_size = height * 0.8
                            # 限制字体大小范围
                            estimated_font_size = max(6, min(estimated_font_size, 72))
                        else:
                            estimated_font_size = font_size

                        # 选择字体名称
                        use_fontname = None
                        if font_name is None:
                            # 自动检测：如果包含CJK字符，使用CJK字体
                            if _contains_cjk(content) and cjk_fontname:
                                use_fontname = cjk_fontname
                            # 否则使用默认字体（不指定fontname参数）
                        else:
                            # 用户指定了字体名称
                            if font_name.lower() == "cjk":
                                if cjk_fontname:
                                    use_fontname = cjk_fontname
                                else:
                                    logger.warning("CJK字体不可用，使用默认字体")
                            else:
                                # 使用用户指定的字体名称
                                use_fontname = font_name

                        # 使用坐标变换函数将逻辑坐标转换为PyMuPDF坐标
                        pymupdf_x, pymupdf_y, pymupdf_rotate = logical_bbox_to_pymupdf_point(bbox, page_height)

                        # 构建insert_text的参数
                        text_params = {
                            "point": (pymupdf_x, pymupdf_y),  # 变换后的坐标
                            "text": content,
                            "fontsize": estimated_font_size,
                            "render_mode": 0,  # 可见模式（用于调试），最上层
                            "color": (1, 0, 0),  # 红色，便于观察
                            "rotate": pymupdf_rotate,  # 逆时针旋转90度，补偿坐标系统的旋转
                        }

                        # 如果指定了字体名称，添加到参数中
                        if use_fontname:
                            text_params["fontname"] = use_fontname

                        # 写入文本
                        page.insert_text(**text_params)
                    except Exception as e:
                        logger.warning(f"添加文本span失败 (页面{page_idx + 1}, span {span_idx + 1}): {e}")
                        continue

                logger.info(f"页面 {page_idx + 1} 处理完成，共处理 {len(spans)} 个span")

        # 保存PDF
        doc.save(output_path)
        doc.close()
        logger.info(f"成功生成可搜索PDF: {output_path}")
        return True

    except Exception as e:
        logger.error(f"创建可搜索PDF失败: {e}")
        return False


def create_searchable_pdf_from_json_file(
    pdf_bytes: bytes,
    middle_json_path: str,
    output_path: str,
    font_size: Optional[float] = None,
    font_name: Optional[str] = None
) -> bool:
    """
    从JSON文件创建可搜索PDF的便捷函数

    Args:
        pdf_bytes: 原始PDF的字节数据
        middle_json_path: middle_json文件路径
        output_path: 输出PDF文件路径
        font_size: 字体大小，如果为None则根据bbox高度自动计算
        font_name: 字体名称，默认为"helv"

    Returns:
        bool: 是否成功创建
    """
    try:
        with open(middle_json_path, 'r', encoding='utf-8') as f:
            middle_json = json.load(f)
        return create_searchable_pdf(pdf_bytes, middle_json, output_path, font_size, font_name)
    except Exception as e:
        logger.error(f"读取middle_json文件失败: {e}")
        return False
