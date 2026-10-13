import struct
import zlib
from pathlib import Path


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


width = height = 192
raw = bytearray()
center = 96
for y in range(height):
    raw.append(0)
    for x in range(width):
        distance = ((x - center) ** 2 + (y - center) ** 2) ** 0.5
        if distance <= 78:
            blend = distance / 78
            red = int(14 + (56 - 14) * blend)
            green = int(24 + (189 - 24) * (1 - blend))
            blue = int(40 + (248 - 40) * (1 - blend))
            alpha = 255
        elif distance <= 88:
            red, green, blue, alpha = 56, 189, 248, 255
        else:
            red = green = blue = alpha = 0
        raw.extend((red, green, blue, alpha))

signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
image = signature
image += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
image += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
image += chunk(b"IEND", b"")
destination = Path(__file__).resolve().parent / "includes.chroot/usr/share/plymouth/themes/devos/watermark.png"
destination.write_bytes(image)
print(list(destination.read_bytes()[:8]), destination.stat().st_size)
