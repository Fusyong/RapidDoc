import cv2
import numpy as np

from rapid_doc.model.ocr.rapid_ocr import RapidOcrModel
from rapid_doc.utils.ocr_utils import get_rotate_crop_image


def preprocess_image(img):
    """图像预处理"""
    # 转换为灰度图
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 二值化处理——这步很关键
    _, binary = cv2.threshold(gray, 0, 255,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # BGR转换
    processed = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    return processed


if __name__ == '__main__':
    ocr_model = RapidOcrModel()
    bgr_image = cv2.imread('reader_order_01.png')

    # img_list = [img0]
    # for img in img_list:
    #     ocr_res = ocr_model.ocr(img=img)
    #     print(ocr_res)

    # bgr_image = cv2.resize(bgr_image, None, fx=0.1, fy=0.1, interpolation=cv2.INTER_AREA)  # 缩小10倍
    # bgr_image = cv2.resize(bgr_image, None, fx=10, fy=10, interpolation=cv2.INTER_CUBIC)  # 放大10倍

    # bgr_image = preprocess_image(bgr_image)

    det_res = ocr_model.ocr(bgr_image, rec=False)[0]

    rec_img_list = []
    for dt_box in det_res:
        rec_img_list.append(
            {
                "cropped_img": get_rotate_crop_image(
                    bgr_image, np.asarray(dt_box, dtype=np.float32)
                ),
                "dt_box": np.asarray(dt_box, dtype=np.float32),
            }
        )
    cropped_img_list = [item["cropped_img"] for item in rec_img_list]
    ocr_res_list = ocr_model.ocr(cropped_img_list, det=False, tqdm_enable=False)[0]

    print(ocr_res_list)



