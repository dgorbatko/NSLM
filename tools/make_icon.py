from PIL import Image
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'assets'
root.mkdir(exist_ok=True)
logo = Image.open(root / 'logo-white.png').convert('RGBA')
bounds = logo.getbbox()
if not bounds:
    raise RuntimeError('logo-white.png has no visible pixels')
logo = logo.crop(bounds)
logo.thumbnail((218, 218), Image.Resampling.LANCZOS)
image = Image.new('RGBA', (256, 256))
image.alpha_composite(logo, ((256 - logo.width) // 2, (256 - logo.height) // 2))
image.save(root / 'icon.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
image.save(root / 'icon.png')
