#!/usr/bin/env python3
"""
make_video.py - render a captioned vertical video from a scene JSON.

Free stack: edge-tts (narration, keyless) + loremflickr/picsum (imagery, keyless)
          + ffmpeg (everything else). No paid API, no GPU.

    python demo/make_video.py --script demo/script.example.json --out out/demo.mp4
"""
import argparse
import asyncio
import json
import math
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

WPS = 2.6  # words per second, used only when TTS gives no word timings
FPS = 25
# Wikimedia requires a descriptive User-Agent (ToS). Be polite.
UA = {"User-Agent": "free-video-pipeline/1.0 (self-hosted demo; contact: local)"}
COMMON_HEADERS = {"User-Agent": "Mozilla/5.0 free-video-pipeline/1.0"}


# --------------------------------------------------------------------------- ff
def run(cmd: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed ({r.returncode}):\n{r.stderr[-1500:]}")
    return r.stdout


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path.name], cwd=path.parent)
    return float(out.strip())


# -------------------------------------------------------------------------- tts
async def synth(text: str, voice: str, mp3: Path) -> list[tuple[float, float, str]]:
    """Synthesize narration; return [(start_s, end_s, word), ...] from TTS word boundaries."""
    import edge_tts  # imported lazily so --help works without deps

    # boundary="WordBoundary" is essential: edge-tts defaults to SentenceBoundary,
    # which would give us no word-level timings for karaoke captions.
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    words: list[tuple[float, float, str]] = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            ctype = chunk["type"]
            if ctype == "audio":
                f.write(chunk["data"])
            elif ctype in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / 1e7
                end = start + chunk["duration"] / 1e7
                words.append((start, end, chunk["text"]))
    return words


# ----------------------------------------------------------------------- images
def _fetch_bytes(url: str, headers: dict, timeout: int = 25) -> tuple[bytes, str] | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except Exception:  # noqa: BLE001 - any network error falls through to next source
        return None


def _is_image(data: bytes, ctype: str) -> bool:
    return len(data) > 8000 and ("image" in ctype or data[:3] == b"\xff\xd8\xff"
                                  or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF")


def fetch_image(scene: dict, idx: int, dest: Path) -> bool:
    """Get a free image (no API key). Tries, in order:
       1. Wikimedia Commons search (themed real photos)
       2. Picsum (random but varied)
       3. ffmpeg solid color gradient (last resort)"""
    query = (scene.get("stock_query") or "abstract nature").replace(",", " ")

    # --- 1. Wikimedia Commons: keyless API, real themed photos ----------------
    try:
        api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               "&prop=imageinfo&iiprop=url&iiurlwidth=1080"
               "&generator=search&gsrnamespace=6"
               f"&gsrlimit=3&gsrsearch={urllib.parse.quote(query)}")
        raw = _fetch_bytes(api, UA)
        if raw:
            import json as _json
            data = _json.loads(raw[0])
            pages = (data.get("query") or {}).get("pages") or {}
            for _, page in pages.items():
                info_list = page.get("imageinfo") or []
                if info_list:
                    thumb = info_list[0].get("thumburl") or info_list[0].get("url")
                    if thumb:
                        got = _fetch_bytes(thumb, COMMON_HEADERS)
                        if got and _is_image(got[0], got[1]):
                            dest.write_bytes(got[0])
                            return True
    except Exception as e:  # noqa: BLE001
        print(f"    wikimedia search failed: {e}", file=sys.stderr)

    # --- 2. Picsum (random, but always varied) --------------------------------
    for variant in ("picsum", "picsum-grayscale"):
        url = (f"https://{variant}.photos/seed/{idx}{abs(hash(query)) % 9999}/1080/1920")
        got = _fetch_bytes(url, COMMON_HEADERS)
        if got and _is_image(got[0], got[1]):
            dest.write_bytes(got[0])
            return True
    return False


# ----------------------------------------------------------------------- render
def motion_filter(motion: str, frames: int) -> str:
    """Ken-Burns filter chain. Keeps a 1.15x zoom headroom so panning never shows edges."""
    base = "scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560"
    z_in = "z='min(zoom+0.0006,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    z_out = "z='if(lte(on,1),1.18,max(zoom-0.0006,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    pan_r = f"z=1.15:x='(iw-iw/1.15)*on/{max(frames,1)}':y='(ih-ih/1.15)/2'"
    pan_l = f"z=1.15:x='(iw-iw/1.15)*(1-on/{max(frames,1)})':y='(ih-ih/1.15)/2'"
    table = {
        "zoom_in": z_in,
        "zoom_out": z_out,
        "pan_right": pan_r,
        "pan_left": pan_l,
        "static": "z='1.0001':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    }
    return f"{base},zoompan={table.get(motion, z_in)}:d=1:s=1080x1920:fps={FPS}"


CAPTION_FORCE = ("FontName=Arial,FontSize=54,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00000000,Outline=3,Shadow=1,Alignment=2,MarginV=300,Bold=1")
FONT_PATH_WIN = "C\\:/Windows/Fonts/arial.ttf"  # ffmpeg-escaped for Windows path
FONTSIZE = 54
MARGIN_V = 300  # px from bottom edge


def _drawtext_chain(chunks: list[tuple[float, float, str]], prefix: str,
                    work: Path) -> str:
    """Build a comma-separated drawtext filter chain from caption chunks.

    Each caption gets its own chunk_NN.txt (textfile avoids quote/colon escaping
    hell), plus a drawtext instance gated by `enable='between(t,start,end)'`.
    """
    filters = []
    for i, (start, end, text) in enumerate(chunks, 1):
        textfile = work / f"{prefix}{i:02d}.txt"
        textfile.write_text(text, encoding="utf-8")
        # box + shadow for legibility; centered; pinned 300px from bottom
        expr = (f"drawtext=fontfile='{FONT_PATH_WIN}'"
                f":textfile='{textfile.name}'"
                f":fontsize={FONTSIZE}:fontcolor=white"
                f":box=1:boxcolor=black@0.55:boxborderw=14"
                f":x=(w-text_w)/2:y=h-{MARGIN_V}"
                f":enable='between(t,{start:.3f},{end:.3f})'")
        filters.append(expr)
    return ",".join(filters)


def srt_to_drawtext(srt: Path, work: Path, prefix: str) -> str:
    """Parse an SRT (one scene, 0-based times) into a drawtext filter chain."""
    chunks: list[tuple[float, float, str]] = []
    n, t_start, t_end, buf = 0, None, None, []
    for raw in srt.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            if buf and t_start is not None:
                chunks.append((t_start, t_end, " ".join(buf)))
                buf, t_start, t_end = [], None, None
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            a, b = line.split("-->", 1)
            t_start = _srt_to_sec(a.strip())
            t_end = _srt_to_sec(b.strip())
        else:
            buf.append(line)
    if buf and t_start is not None:
        chunks.append((t_start, t_end, " ".join(buf)))
    return _drawtext_chain(chunks, prefix, work)


def _srt_to_sec(ts: str) -> float:
    """Convert SRT timestamp 'HH:MM:SS,mmm' -> seconds (float)."""
    hms, ms = ts.rsplit(",", 1) if "," in ts else (ts, "0")
    h, m, s = (float(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s + float(ms) / 1000


def render_scene(img: Path, duration: float, motion: str, caption_filter: str | None,
                 out: Path) -> None:
    """Burn Ken-Burns motion AND captions into a scene in a single ffmpeg pass.

    drawtext (libfreetype) is used instead of the subtitles filter (libass) because
    libass silently drops overlays on the zoompan output's color format on this
    ffmpeg build. drawtext + an explicit yuv420p format pass renders reliably."""
    frames = max(int(duration * FPS), 1)
    vf = motion_filter(motion, frames) + ",format=yuv420p"
    if caption_filter:
        vf += "," + caption_filter
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS),
         "-t", f"{duration:.3f}", "-i", img.name,
         "-vf", vf,
         "-t", f"{duration:.3f}", "-frames:v", str(frames),
         "-c:v", "libx264", "-crf", "20", "-preset", "medium",
         "-pix_fmt", "yuv420p", "-r", str(FPS), out.name], cwd=img.parent)


def concat(names: list[str], out: Path, cwd: Path, audio: bool = False) -> None:
    listfile = cwd / ("audio.txt" if audio else "video.txt")
    listfile.write_text("\n".join(f"file '{n}'" for n in names) + "\n", encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listfile.name]
    cmd += ["-c", "copy", out.name] if audio else \
           ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", out.name]
    run(cmd, cwd=cwd)


# --------------------------------------------------------------------- captions
def srt_time(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"


def build_scene_srt(narration: str, words: list[tuple[float, float, str]],
                    duration: float) -> str:
    """Build a 0-based SRT for a single scene, grouping words into ~5-word chunks
    or splitting on terminal punctuation. Falls back to even word-split when the
    TTS returned no boundary timings."""
    if not words:
        toks = narration.split()
        step = duration / max(len(toks), 1)
        words = [(i * step, (i + 1) * step, t) for i, t in enumerate(toks)]

    chunks, buf, n = [], [], 0
    for start, end, word in words:
        buf.append((start, end, word.strip()))
        if len(buf) >= 5 or word.rstrip().endswith((".", "!", "?")):
            n += 1
            chunks.append((n, buf[0][0], buf[-1][1], " ".join(w for *_, w in buf)))
            buf = []
    if buf:
        n += 1
        chunks.append((n, buf[0][0], buf[-1][1], " ".join(w for *_, w in buf)))
    return "\n\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}" for i, a, b, txt in chunks) + "\n"


# ------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--out", default="out/demo.mp4")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep intermediate build files")
    a = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"error: {tool} not found on PATH", file=sys.stderr)
            return 1

    spec = json.loads(Path(a.script).read_text(encoding="utf-8"))
    voice = spec.get("voice", "en-US-AndrewMultilingualNeural")
    scenes = spec["scenes"]

    out_path = Path(a.out).resolve()
    work = out_path.parent / "build"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[video] {len(scenes)} scenes -> {out_path}")

    starts: list[float] = []
    boundaries: list[list[tuple[float, float, str]]] = []
    cursor = 0.0

    for i, scene in enumerate(scenes, 1):
        text = scene["narration"].strip()
        mp3 = work / f"s{i:02d}.mp3"
        print(f"  [{i}/{len(scenes)}] tts: {text[:58]}...")
        words = asyncio.run(synth(text, voice, mp3))
        dur = probe_duration(mp3)
        scene["duration"] = dur
        starts.append(cursor)
        boundaries.append(words)
        cursor += dur

        img = work / f"s{i:02d}.jpg"
        if not fetch_image(scene, i, img):
            print("    using generated gradient backdrop")
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                 f"gradients=size=1080x1920:c0=0x1b2735:c1=0x0f172a:x0=0:y0=0:x1=1080:y1=1920:nb_colors=2",
                 "-frames:v", "1", img.name], cwd=work)

        subs_path = None if a.no_subs else (work / f"sub{i:02d}.srt")
        if subs_path is not None:
            subs_path.write_text(build_scene_srt(text, words, dur), encoding="utf-8")
        captions = srt_to_drawtext(subs_path, work, f"ch{i:02d}_") if subs_path else None
        render_scene(img, dur, scene.get("motion", "zoom_in"), captions,
                     work / f"v{i:02d}.mp4")
        print(f"    {dur:.1f}s clip ({len(words)} word timings)")

    print(f"[video] assembly @ {cursor:.1f}s total")
    # Scenes already have captions burned in. Concat with stream copy for speed.
    listfile = work / "video.txt"
    listfile.write_text("\n".join(f"file 'v{i:02d}.mp4'" for i in range(1, len(scenes) + 1))
                        + "\n", encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "video.txt",
         "-c", "copy", "-an", "merged.mp4"], cwd=work)
    concat([f"s{i:02d}.mp3" for i in range(1, len(scenes) + 1)], work / "voice.mp3", work,
           audio=True)

    run(["ffmpeg", "-y", "-v", "error", "-i", "merged.mp4", "-i", "voice.mp3",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "final.mp4"], cwd=work)

    shutil.copy2(work / "final.mp4", out_path)
    size_mb = out_path.stat().st_size / 1e6
    print(f"[video] done: {out_path}  ({cursor:.1f}s, {size_mb:.1f} MB)")

    if not a.keep:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
