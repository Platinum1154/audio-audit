from __future__ import annotations

from pathlib import Path
import subprocess


def render_visualization(
    audio_path: Path,
    *,
    kind: str,
    width: int,
    height: int,
) -> bytes:
    safe_width = max(320, min(int(width), 2400))
    safe_height = max(160, min(int(height), 1400))
    size = f"{safe_width}x{safe_height}"

    if kind == "waveform":
        filter_spec = (
            f"showwavespic=s={size}:colors=0xffbf47:scale=sqrt:draw=scale:filter=peak"
        )
    elif kind == "spectrogram":
        filter_spec = (
            f"showspectrumpic=s={size}:mode=combined:color=viridis:"
            "scale=log:fscale=log:legend=disabled"
        )
    else:
        raise ValueError(f"Unsupported visualization kind: {kind}")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-frames:v",
        "1",
        "-lavfi",
        filter_spec,
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]

    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(stderr or "ffmpeg failed to generate visualization")

    return result.stdout
