"""Runtime media checks shared by generic and legacy verification."""
from io import BytesIO
import time

from PIL import Image, ImageStat

from .scene import Check


def video_signal(client, name, *, check_id, seconds=2):
    samples, errors = [], []
    for index in range(3):
        if index:
            time.sleep(seconds / 2)
        try:
            content = client.get_source_screenshot(name, width=320, height=180)
            with Image.open(BytesIO(content)) as frame:
                frame.load()
                gray = frame.convert('L')
                gray.thumbnail((96, 54))
                mean = float(ImageStat.Stat(gray).mean[0])
                maximum = float(gray.getextrema()[1])
            samples.append({'mean_luma': mean, 'max_luma': maximum})
        except Exception as exc:
            errors.append(str(exc))
    passed = any(s['mean_luma'] >= 2 or s['max_luma'] >= 8 for s in samples)
    return Check(check_id, 'PASS' if passed else 'FAIL',
                 'Source produced a non-black frame.' if passed else 'Source did not produce a valid non-black frame.',
                 {'non_black': True}, {'samples': samples, 'errors': errors})
