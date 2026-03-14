"""Download video files with retry and idempotency (skip if file exists)."""

import time
from pathlib import Path

import requests


def download_vimeo(
    vimeo_id: str,
    dest_path: Path,
    *,
    skip_existing: bool = True,
    referer: str = "https://www.hep2go.com/",
) -> tuple[bool, str | None, int | None]:
    """
    Download a Vimeo video by ID using yt-dlp (embed-only videos need referer).
    Returns (success, content_type_or_none, file_size_bytes_or_none).
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if skip_existing and dest_path.is_file() and dest_path.stat().st_size > 0:
        return True, "video/mp4", dest_path.stat().st_size
    try:
        import yt_dlp
    except ImportError:
        return False, None, None
    # Use player URL with referer for embed-only videos
    url = f"https://player.vimeo.com/video/{vimeo_id}"
    # Video only; no audio extraction or merging
    opts = {
        "outtmpl": str(dest_path),
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo/best",
        "format_sort": ["vcodec:h264", "res"],
        "http_headers": {"Referer": referer},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        if dest_path.is_file() and dest_path.stat().st_size > 0:
            return True, "video/mp4", dest_path.stat().st_size
    except Exception:
        if dest_path.is_file():
            try:
                dest_path.unlink()
            except OSError:
                pass
    return False, None, None


def download_video_url(
    url: str,
    dest_path: Path,
    *,
    skip_existing: bool = True,
) -> tuple[bool, str | None, int | None]:
    """
    Download a video from a URL (YouTube, Vimeo, or direct) using yt-dlp.
    Returns (success, content_type_or_none, file_size_bytes_or_none).
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if skip_existing and dest_path.is_file() and dest_path.stat().st_size > 0:
        return True, "video/mp4", dest_path.stat().st_size
    try:
        import yt_dlp
    except ImportError:
        return False, None, None
    opts = {
        "outtmpl": str(dest_path),
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo/best",
        "format_sort": ["vcodec:h264", "res"],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        if dest_path.is_file() and dest_path.stat().st_size > 0:
            return True, "video/mp4", dest_path.stat().st_size
    except Exception:
        if dest_path.is_file():
            try:
                dest_path.unlink()
            except OSError:
                pass
    return False, None, None


def download_file(
    url: str,
    dest_path: Path,
    *,
    timeout_sec: int = 60,
    max_retries: int = 2,
    skip_existing: bool = True,
) -> tuple[bool, str | None, int | None]:
    """
    Download a file from url to dest_path.

    Returns:
        (success, content_type_or_none, file_size_bytes_or_none)
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if skip_existing and dest_path.is_file() and dest_path.stat().st_size > 0:
        return True, None, dest_path.stat().st_size

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, stream=True, timeout=timeout_sec)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
            content_length = resp.headers.get("Content-Length")
            size = int(content_length) if content_length else None

            with open(dest_path, "wb") as f:
                written = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
            actual_size = written if size is None else size
            if dest_path.is_file():
                actual_size = dest_path.stat().st_size
            return True, content_type or None, actual_size
        except requests.RequestException as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
        except OSError as e:
            last_error = e
            break

    if dest_path.is_file():
        try:
            dest_path.unlink()
        except OSError:
            pass
    return False, None, None
