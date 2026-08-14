import os
import tempfile
from core import tools
from PIL import Image


def test_images_to_pdf_creates_file(tmp_path):
    # create two small images
    p1 = tmp_path / "one.png"
    p2 = tmp_path / "two.png"
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    img.save(p1)
    img = Image.new("RGB", (100, 100), color=(0, 255, 0))
    img.save(p2)

    out_pdf = tmp_path / "out.pdf"
    res = tools.execute_tool('adapter.img.imgtopdf', {'image_paths': [str(p1), str(p2)], 'output_path': str(out_pdf)})
    assert os.path.exists(str(out_pdf))
    assert str(out_pdf) == res
