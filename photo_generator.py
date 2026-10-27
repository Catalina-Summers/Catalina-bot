import os
from PIL import Image, ImageDraw, ImageFont

def generate_hd_image(text, width=1920, height=1080, bg_color=(255,255,255), text_color=(0,0,0)):
    """Generate a simple high‑definition image with the given text.
    Returns the file path of the saved image.
    """
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('arial.ttf', size=80)
    except Exception:
        font = ImageFont.load_default()
    text_width, text_height = d.textsize(text, font=font)
    x = (width - text_width) / 2
    y = (height - text_height) / 2
    d.text((x, y), text, fill=text_color, font=font)
    output_path = f'generated_{text.replace(" ", "_")}.png'
    img.save(output_path)
    return output_path

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        txt = ' '.join(sys.argv[1:])
        path = generate_hd_image(txt)
        print(f'Image saved to {path}')
    else:
        print('Provide text to render')
