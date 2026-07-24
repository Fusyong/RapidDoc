import html as html_stdlib
import os
import re
from io import BytesIO

from loguru import logger
from pypdf import PdfReader, PdfWriter, PageObject
from reportlab.pdfgen import canvas
from reportlab.lib.colors import transparent

from .draw_bbox import cal_canvas_rect
from .enum_class import BlockType, ContentType

# 与 span_block_fix.py 保持一致：用高宽比启发式识别竖排 span
_VERTICAL_SPAN_HEIGHT_TO_WIDTH_RATIO_THRESHOLD = 2.0

def _html_to_plain_text_for_layer(html_str: str) -> str:
    """从表格 HTML 提取可检索纯文本（与 Markdown 中表格语义一致，供透明文本层使用）。"""
    if not html_str:
        return ""
    t = re.sub(r"<br\s*/?>", " ", html_str, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html_stdlib.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _table_span_plain_text_for_layer(span: dict) -> str:
    """TABLE 类型 span：content / latex / 去标签 html，与 mkcontent 输出同源。"""
    c = span.get("content")
    if c is not None:
        s = c if isinstance(c, str) else str(c)
        if s.strip():
            return s.strip()
    lx = span.get("latex")
    if lx:
        s = lx if isinstance(lx, str) else str(lx)
        if s.strip():
            return s.strip()
    h = span.get("html")
    if h:
        return _html_to_plain_text_for_layer(h if isinstance(h, str) else str(h))
    return ""


def _count_html_table_rows(html: str) -> int:
    """统计 HTML 表格行数（`<tr`），用于把整表 bbox 高度均分到各行文本层。"""
    if not html:
        return 1
    n = len(re.findall(r"<tr\b", html if isinstance(html, str) else str(html), flags=re.I))
    return max(1, n)


def _estimate_table_text_lines(span: dict, plain: str) -> int:
    """无 HTML 时估计行数（LaTeX / 纯文本兜底）。"""
    h = span.get("html")
    if h:
        return _count_html_table_rows(h if isinstance(h, str) else str(h))
    lx = span.get("latex")
    if lx and isinstance(lx, str) and lx.strip():
        # 行间常见 \\ 分隔
        n = lx.count("\\\\") + 1
        return max(1, min(n, 64))
    if plain and "\n" in plain:
        return max(1, plain.count("\n") + 1)
    return 1


def _split_plain_into_n_lines(text: str, n: int) -> list[str]:
    """将合并后的表格纯文本均分为 n 行（按字符数，兼容中英文）。"""
    if n <= 1:
        return [text]
    chars = list(text)
    total = len(chars)
    if total == 0:
        return [""] * n
    base, rem = divmod(total, n)
    lines: list[str] = []
    idx = 0
    for i in range(n):
        take = base + (1 if i < rem else 0)
        lines.append("".join(chars[idx : idx + take]))
        idx += take
    return lines


def _draw_table_text_in_bbox(
    canv,
    x0: float,
    y0: float,
    rect_w: float,
    rect_h: float,
    stripped: str,
    span: dict,
    font_name: str,
) -> None:
    """
    在表格 bbox 内按「行数」铺多行透明文本；字号 ≈ 行高，避免整表高度误作单行字号。
    """
    n_rows = _estimate_table_text_lines(span, stripped)
    line_height = rect_h / max(n_rows, 1)
    # 字号略小于行高，留出行间空隙，选中/检索高度更接近真实表格
    font_size = max(1.0, line_height * 0.78)
    lines = _split_plain_into_n_lines(stripped, n_rows)

    from reportlab.pdfbase import pdfmetrics

    for k, line in enumerate(lines):
        part = line.strip() if line else ""
        if not part:
            continue
        if rect_w <= 0:
            continue
        # y0 为 bbox 底边；第 k 行占据从下往上第 (n_rows-k) 条行带，基线取行带内略偏下（与正文单行 rect_h≈字号一致）
        y_baseline = y0 + rect_h - (k + 0.5) * line_height - 0.15 * font_size
        try:
            tw = pdfmetrics.stringWidth(part, font_name, font_size)
            if tw and tw > 0:
                horiz_scale = (rect_w / tw) * 100.0
                t = canv.beginText(x0, y_baseline)
                t.setFont(font_name, font_size)
                t.setFillColor(transparent)
                t.setHorizScale(horiz_scale)
                t.textOut(part)
                canv.drawText(t)
            else:
                canv.drawString(x0, y_baseline, part)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(f"表格文本层单行写入失败: {e}")
            canv.drawString(x0, y_baseline, part)


# 常见 CJK 字体路径（用于图版 PDF 文字层正确显示中文）
_DEFAULT_CJK_FONT_PATHS = [
    "C:/Windows/Fonts/msyh.ttc",   # Microsoft YaHei
    "C:/Windows/Fonts/simsun.ttc", # 宋体
    "C:/Windows/Fonts/simhei.ttf", # 黑体
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

_CJK_FONT_REGISTERED = None  # 已注册的 CJK 字体名称，供本模块复用


def _get_and_register_cjk_font(cjk_font_path=None):
    """
    解析并注册 CJK 字体，供 ReportLab 绘制文本层使用。
    若未指定路径则尝试默认路径列表；若均不可用则返回 None（调用方用 Helvetica 并打 warning）。
    """
    global _CJK_FONT_REGISTERED
    if _CJK_FONT_REGISTERED is not None:
        return _CJK_FONT_REGISTERED

    paths_to_try = []
    if cjk_font_path and os.path.isfile(cjk_font_path):
        paths_to_try.append(cjk_font_path)
    for p in _DEFAULT_CJK_FONT_PATHS:
        if os.path.isfile(p) and p not in paths_to_try:
            paths_to_try.append(p)

    for font_path in paths_to_try:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            name = "RapidDocCJK"
            pdfmetrics.registerFont(TTFont(name, font_path))
            _CJK_FONT_REGISTERED = name
            logger.debug(f"双层PDF使用CJK字体: {font_path}")
            return name
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(f"注册CJK字体失败 {font_path}: {e}")
            continue

    return None


def create_layered_pdf_pypdf(
    pdf_info,
    pdf_bytes,
    output_path,
    layered_pdf_ignore_block_types=None,
    layered_pdf_cjk_font_path=None,
):
    """
    使用 pypdf 和 reportlab 创建双层可搜索 PDF。
    文本层与 draw_span_bbox 使用同一套坐标与旋转逻辑；仅写入 ContentType.TEXT 的 span；
    使用支持 CJK 的字体写入文本层，避免图版 PDF 下中文显示为大写 I 等错误字符。

    Args:
        pdf_info: PDF 信息列表，每个元素为一页
        pdf_bytes: 原始 PDF 字节
        output_path: 输出文件路径
        layered_pdf_ignore_block_types: 不写入文本层的 block 类型列表，如 ["image_footnote","table_footnote"]
        layered_pdf_cjk_font_path: 可选，CJK 字体文件路径；不传则尝试默认路径

    Returns:
        bool: 是否成功创建
    """
    ignore_set = set(layered_pdf_ignore_block_types or [])

    cjk_font = _get_and_register_cjk_font(layered_pdf_cjk_font_path)
    if cjk_font is None:
        logger.warning(
            "未配置或未找到 CJK 字体，图版/OCR 场景下文字层中的中文可能显示为错误字符（如大写 I），请配置 layered_pdf_cjk_font_path 或安装 CJK 字体"
        )

    try:
        pdf_reader = PdfReader(BytesIO(pdf_bytes))
        pdf_writer = PdfWriter()

        for page_idx, page_info in enumerate(pdf_info):
            if page_idx >= len(pdf_reader.pages):
                break

            original_page = pdf_reader.pages[page_idx]
            # 将 /Rotate 烘焙进内容流并清零 Rotate。否则 OCR 得到的是“正向”
            # 图像坐标，而文字层仍按未旋转用户空间 LTR 写入；页面带 Rotate=180
            # 时，阅读器再旋转一次会导致同行文字左右颠倒（复制顺序仍正确）。
            try:
                page_rotate = int(original_page.get("/Rotate", 0) or 0) % 360
            except (ValueError, TypeError):
                page_rotate = 0
            if page_rotate:
                original_page.transfer_rotation_to_content()

            crop = original_page.cropbox
            page_width = float(crop[2]) - float(crop[0])
            page_height = float(crop[3]) - float(crop[1])

            packet = BytesIO()
            c = canvas.Canvas(packet, pagesize=(page_width, page_height))

            def draw_text_spans(block, block_type, page_obj, canv):
                if block_type in ignore_set:
                    return
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        st = span.get("type")
                        if st == ContentType.TEXT:
                            text = span.get("content")
                            if text is None or (isinstance(text, str) and not text.strip()):
                                continue
                            text = text if isinstance(text, str) else str(text)
                        elif st == ContentType.TABLE:
                            text = _table_span_plain_text_for_layer(span)
                            if not text:
                                continue
                        else:
                            continue
                        bbox = span.get("bbox")
                        original_label = span.get("original_label") or block.get("original_label")
                        if not bbox:
                            continue
                        try:
                            rect = cal_canvas_rect(page_obj, bbox)
                        except Exception as e:  # pylint: disable=broad-except
                            logger.debug(f"cal_canvas_rect 跳过 span: {e}")
                            continue
                        x0, y0, rect_w, rect_h = rect[0], rect[1], rect[2], rect[3]
                        canv.setFillColor(transparent)

                        # 竖排文本：优先看 original_label，其次用 bbox 高宽比启发式兜底。
                        # 按 bbox 宽度作为字号，逐字从上到下写入，避免横排写入导致选中框错位。
                        # 整表 HTML 合并文本始终按横排整块写入（与 Markdown 表格语义一致）。
                        if st == ContentType.TABLE:
                            is_vertical = False
                        else:
                            is_vertical = (
                                original_label == "vertical_text"
                                or (rect_w > 0 and (rect_h / rect_w) > _VERTICAL_SPAN_HEIGHT_TO_WIDTH_RATIO_THRESHOLD)
                            )
                        if is_vertical:
                            font_size = max(1, rect_w)
                            if cjk_font:
                                canv.setFont(cjk_font, font_size)
                            else:
                                canv.setFont("Helvetica", font_size)

                            chars = list(text.strip())
                            if not chars:
                                continue

                            # 从 bbox 顶部开始逐字往下排；行距按 bbox 高度均分，避免“越往下越漂”的累计误差
                            # 注：leading 不能过大，否则最后几字会溢出 bbox；这里用 rect_h / n 做基准并略微压缩
                            n = len(chars)
                            base_leading = rect_h / n if n > 0 else font_size
                            leading = max(0.5, min(font_size * 1.0, base_leading) * 0.98)
                            y = y0 + rect_h - font_size
                            for ch in chars:
                                if y < y0 - 0.5 * font_size:
                                    break
                                canv.drawString(x0, y, ch)
                                y -= leading
                            continue

                        # 表格：整表 bbox 高度是「多行之和」，不能再用 rect_h 作为单行字号；按 HTML 行数分行写入
                        if st == ContentType.TABLE:
                            font_name_tbl = cjk_font or "Helvetica"
                            _draw_table_text_in_bbox(
                                canv,
                                x0,
                                y0,
                                rect_w,
                                rect_h,
                                text.strip(),
                                span,
                                font_name_tbl,
                            )
                            continue

                        # 横排文本（默认）
                        font_size = max(1, rect_h)
                        font_name = cjk_font or "Helvetica"
                        canv.setFont(font_name, font_size)

                        # 关键：对横排文本做“水平缩放到 bbox 宽度”，否则搜索子串时会按字体度量累计偏移
                        stripped = text.strip()
                        if rect_w > 0 and len(stripped) > 0:
                            try:
                                from reportlab.pdfbase import pdfmetrics

                                text_width = pdfmetrics.stringWidth(stripped, font_name, font_size)
                                if text_width and text_width > 0:
                                    horiz_scale = (rect_w / text_width) * 100.0
                                    t = canv.beginText(x0, y0)
                                    t.setFont(font_name, font_size)
                                    t.setFillColor(transparent)
                                    t.setHorizScale(horiz_scale)
                                    t.textOut(stripped)
                                    canv.drawText(t)
                                else:
                                    canv.drawString(x0, y0, stripped)
                            except Exception as e:  # pylint: disable=broad-except
                                logger.debug(f"写入横排文本层失败，回退 drawString: {e}")
                                canv.drawString(x0, y0, stripped)
                        else:
                            canv.drawString(x0, y0, stripped)

            if "preproc_blocks" in page_info:
                for block in page_info["preproc_blocks"]:
                    bt = block.get("type")
                    if bt in (
                        BlockType.TEXT,
                        BlockType.TITLE,
                        BlockType.INTERLINE_EQUATION,
                        BlockType.LIST,
                        BlockType.INDEX,
                    ):
                        draw_text_spans(block, bt, original_page, c)
                    elif bt in (BlockType.IMAGE, BlockType.TABLE):
                        for sub_block in block.get("blocks", []):
                            draw_text_spans(sub_block, sub_block.get("type"), original_page, c)

            c.save()
            packet.seek(0)
            text_layer_pdf = PdfReader(packet)

            if len(text_layer_pdf.pages) > 0:
                new_page = PageObject(pdf=None)
                new_page.update(original_page)
                new_page.merge_page(text_layer_pdf.pages[0])
                pdf_writer.add_page(new_page)
            else:
                pdf_writer.add_page(original_page)

        with open(output_path, "wb") as f:
            pdf_writer.write(f)

        return True
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"创建双层PDF时出错: {e}")
        return False


def create_layered_searchable_pdf(
    pdf_info,
    pdf_bytes,
    out_path,
    filename,
    use_pypdf=True,
    layered_pdf_ignore_block_types=None,
    layered_pdf_cjk_font_path=None,
):
    """
    创建双层可搜索 PDF（基于 span 级 bbox 与文本）。

    Args:
        pdf_info: 每页信息列表
        pdf_bytes: 原始 PDF 字节
        out_path: 输出目录
        filename: 输出文件名
        use_pypdf: 是否使用 pypdf+reportlab 实现
        layered_pdf_ignore_block_types: 不写入文本层的 block 类型列表
        layered_pdf_cjk_font_path: 可选，CJK 字体路径（图版 PDF 建议配置）
    """
    if use_pypdf:
        output_path = os.path.join(out_path, filename)
        success = create_layered_pdf_pypdf(
            pdf_info,
            pdf_bytes,
            output_path,
            layered_pdf_ignore_block_types=layered_pdf_ignore_block_types,
            layered_pdf_cjk_font_path=layered_pdf_cjk_font_path,
        )
    else:
        logger.warning("PyMuPDF 实现暂未实现，使用 pypdf 实现")
        output_path = os.path.join(out_path, filename)
        success = create_layered_pdf_pypdf(
            pdf_info,
            pdf_bytes,
            output_path,
            layered_pdf_ignore_block_types=layered_pdf_ignore_block_types,
            layered_pdf_cjk_font_path=layered_pdf_cjk_font_path,
        )

    if success:
        logger.info(f"双层PDF已保存: {output_path}")
    else:
        logger.error(f"双层PDF保存失败: {output_path}")

    return success
