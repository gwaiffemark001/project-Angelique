import subprocess
from pathlib import Path

def main(**kwargs):
    if 'input_path' not in kwargs or 'output_path' not in kwargs:
        raise ValueError("Both input_path and output_path must be provided")
    input_path = Path(kwargs['input_path']).expanduser().resolve()
    output_path = Path(kwargs['output_path']).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        'ffmpeg',
        '-y',
        '-nostdin',
        '-i',
        str(input_path),
        '-vf',
        'scale=trunc(iw/2)*2:trunc(ih/2)*2',
        '-r',
        '30',
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-crf',
        '28',
        '-pix_fmt',
        'yuv420p',
        '-threads',
        '4',
        '-c:a',
        'aac',
        '-b:a',
        '128k',
        str(output_path),
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return f'Converted {input_path} to {output_path}'
