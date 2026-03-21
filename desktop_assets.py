from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app_paths import APP_ICON_ICO, APP_ICON_PNG


def create_app_icon_image(size: int = 256) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    padding = max(12, size // 18)
    radius = size // 4

    draw.rounded_rectangle(
        (padding, padding, size - padding, size - padding),
        radius=radius,
        fill=(7, 14, 26, 255),
        outline=(101, 193, 255, 130),
        width=max(3, size // 64),
    )

    glow_box = (size * 0.54, size * 0.08, size * 0.90, size * 0.44)
    draw.ellipse(glow_box, fill=(69, 220, 177, 175))
    draw.ellipse((size * 0.62, size * 0.16, size * 0.82, size * 0.36), fill=(255, 255, 255, 52))

    disc_box = (size * 0.12, size * 0.34, size * 0.78, size * 1.00)
    draw.ellipse(
        disc_box,
        fill=(13, 29, 52, 255),
        outline=(116, 204, 255, 145),
        width=max(3, size // 64),
    )
    draw.ellipse(
        (size * 0.23, size * 0.45, size * 0.67, size * 0.89),
        outline=(84, 167, 236, 110),
        width=max(3, size // 72),
    )
    draw.ellipse(
        (size * 0.34, size * 0.56, size * 0.56, size * 0.78),
        fill=(9, 18, 32, 255),
        outline=(191, 236, 255, 110),
        width=max(2, size // 96),
    )

    bar_width = max(10, size // 20)
    bars = [
        (size * 0.58, size * 0.50, size * 0.58 + bar_width, size * 0.75),
        (size * 0.67, size * 0.42, size * 0.67 + bar_width, size * 0.79),
        (size * 0.76, size * 0.55, size * 0.76 + bar_width, size * 0.73),
    ]
    bar_colors = [(255, 255, 255, 235), (96, 211, 255, 240), (69, 220, 177, 240)]
    for box, color in zip(bars, bar_colors):
        draw.rounded_rectangle(box, radius=bar_width // 2, fill=color)

    draw.ellipse((size * 0.21, size * 0.43, size * 0.31, size * 0.53), fill=(255, 255, 255, 230))
    return image


def write_icon_assets(target_dir: Path, *, prefer_bundled_assets: bool = True) -> tuple[str, str]:
    if prefer_bundled_assets and APP_ICON_PNG.is_file() and APP_ICON_ICO.is_file():
        return str(APP_ICON_PNG), str(APP_ICON_ICO)

    target_dir.mkdir(parents=True, exist_ok=True)
    png_path = target_dir / "app-icon.png"
    ico_path = target_dir / "app-icon.ico"
    icon_image = create_app_icon_image()
    icon_image.save(png_path, format="PNG")
    icon_image.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (96, 96), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    return str(png_path), str(ico_path)
