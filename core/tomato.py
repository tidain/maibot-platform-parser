# tomato_core.py
import math
import io
from PIL import Image
import numpy as np


def gilbert2d(width: int, height: int) -> list:
    coordinates = []
    if width >= height:
        _generate2d(0, 0, width, 0, 0, height, coordinates)
    else:
        _generate2d(0, 0, 0, height, width, 0, coordinates)
    return coordinates


def _generate2d(x, y, ax, ay, bx, by, coordinates):
    w = abs(ax + ay)
    h = abs(bx + by)

    dax = _sign(ax)
    day = _sign(ay)
    dbx = _sign(bx)
    dby = _sign(by)

    if h == 1:
        for _ in range(w):
            coordinates.append((x, y))
            x += dax
            y += day
        return

    if w == 1:
        for _ in range(h):
            coordinates.append((x, y))
            x += dbx
            y += dby
        return

    ax2 = ax // 2
    ay2 = ay // 2
    bx2 = bx // 2
    by2 = by // 2

    w2 = abs(ax2 + ay2)
    h2 = abs(bx2 + by2)

    if 2 * w > 3 * h:
        if (w2 % 2) and (w > 2):
            ax2 += dax
            ay2 += day
        _generate2d(x, y, ax2, ay2, bx, by, coordinates)
        _generate2d(x + ax2, y + ay2, ax - ax2, ay - ay2, bx, by, coordinates)
    else:
        if (h2 % 2) and (h > 2):
            bx2 += dbx
            by2 += dby
        _generate2d(x, y, bx2, by2, ax2, ay2, coordinates)
        _generate2d(x + bx2, y + by2, ax, ay, bx - bx2, by - by2, coordinates)
        _generate2d(
            x + (ax - dax) + (bx2 - dbx),
            y + (ay - day) + (by2 - dby),
            -bx2, -by2, -(ax - ax2), -(ay - ay2),
            coordinates
        )


def _sign(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0


def _get_offset(total: int) -> int:
    return round((math.sqrt(5) - 1) / 2 * total)


def encrypt_image(pil_img: Image.Image, quality: int = 95) -> Image.Image:
    img_rgb = pil_img.convert("RGB")
    width, height = img_rgb.size
    total = width * height

    src = np.array(img_rgb, dtype=np.uint8).reshape(-1, 3)
    dst = np.zeros_like(src)

    curve = gilbert2d(width, height)
    offset = _get_offset(total)

    for i in range(total):
        old_pos = curve[i]
        new_pos = curve[(i + offset) % total]
        old_p = old_pos[0] + old_pos[1] * width
        new_p = new_pos[0] + new_pos[1] * width
        dst[new_p] = src[old_p]

    out = Image.fromarray(dst.reshape(height, width, 3), "RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).copy()