from io import BytesIO
from loguru import logger
from pypdf import PdfReader, PdfWriter, PageObject
from reportlab.pdfgen import canvas
from reportlab.lib.colors import transparent


def create_layered_pdf_pypdf(pdf_info, pdf_bytes, output_path):
    """
    使用pypdf和reportlab创建双层可搜索PDF
    
    Args:
        pdf_info: PDF信息列表，每个元素是一个页面的信息
        pdf_bytes: PDF文件的字节数据
        output_path: 输出文件路径
        
    Returns:
        bool: 是否成功创建
    """
    try:
        # 读取原始PDF
        pdf_reader = PdfReader(BytesIO(pdf_bytes))
        pdf_writer = PdfWriter()
        
        # 遍历每一页
        for page_idx, page_info in enumerate(pdf_info):
            if page_idx >= len(pdf_reader.pages):
                break
                
            original_page = pdf_reader.pages[page_idx]
            
            # 获取页面尺寸
            page_width = float(original_page.cropbox[2])
            page_height = float(original_page.cropbox[3])
            
            # 创建文本层PDF
            packet = BytesIO()
            c = canvas.Canvas(packet, pagesize=(page_width, page_height))
            
            # 从pdf_info中提取文本和位置信息
            if 'preproc_blocks' in page_info:
                for block in page_info['preproc_blocks']:
                    if 'lines' in block:
                        for line in block['lines']:
                            if 'spans' in line:
                                for span in line['spans']:
                                    if 'bbox' in span and 'content' in span:
                                        bbox = span['bbox']
                                        text = span['content']
                                        
                                        # 计算文本位置（PDF坐标系，原点在左下角）
                                        x0, y0, _x1, y1 = bbox
                                        # 转换为reportlab坐标系
                                        y0_canvas = page_height - y1
                                        
                                        # 设置文本颜色为透明（文本层不可见，但可搜索）
                                        c.setFillColor(transparent)
                                        c.setFont("Helvetica", max(1, y1 - y0))  # 使用bbox高度作为字体大小
                                        
                                        # 绘制文本（透明，但可搜索）
                                        c.drawString(x0, y0_canvas, text)
            
            c.save()
            packet.seek(0)
            text_layer_pdf = PdfReader(packet)
            
            # 合并原始页面和文本层
            if len(text_layer_pdf.pages) > 0:
                new_page = PageObject(pdf=None)
                new_page.update(original_page)
                new_page.merge_page(text_layer_pdf.pages[0])
                pdf_writer.add_page(new_page)
            else:
                pdf_writer.add_page(original_page)
        
        # 保存PDF
        with open(output_path, "wb") as f:
            pdf_writer.write(f)
        
        return True
    except Exception as e:
        logger.error(f"创建双层PDF时出错: {e}")
        return False


def create_layered_searchable_pdf(pdf_info, pdf_bytes, out_path, filename, use_pypdf=True):
    """
    创建双层可搜索PDF（基于span级别的bbox和文本）
    
    Args:
        pdf_info: PDF信息列表，每个元素是一个页面的信息
        pdf_bytes: PDF文件的字节数据
        out_path: 输出目录
        filename: 输出文件名
        use_pypdf: 是否使用pypdf+reportlab实现（默认True，使用pypdf）
    """
    if use_pypdf:
        output_path = f"{out_path}/{filename}"
        success = create_layered_pdf_pypdf(pdf_info, pdf_bytes, output_path)
    else:
        # PyMuPDF实现暂未实现
        logger.warning("PyMuPDF实现暂未实现，使用pypdf实现")
        output_path = f"{out_path}/{filename}"
        success = create_layered_pdf_pypdf(pdf_info, pdf_bytes, output_path)
    
    if success:
        logger.info(f"双层PDF已保存: {output_path}")
    else:
        logger.error(f"双层PDF保存失败: {output_path}")
    
    return success
