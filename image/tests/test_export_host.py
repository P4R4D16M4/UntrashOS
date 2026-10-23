#!/usr/bin/env python3
"""untrash-export with real ffmpeg (Desk export): track selection, scaling,
subtitles, target size, music conversion, plain copy, ffmpeg errors."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-export")
FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name)
    FAIL += 0 if ok else 1


def streams(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,height:stream_tags=language",
                        "-of", "json", p], stdout=subprocess.PIPE, text=True)
    return json.loads(r.stdout or "{}").get("streams", [])


def run(job, w):
    jf = os.path.join(w, "job.json")
    json.dump(job, open(jf, "w"))
    r = subprocess.run([TOOL, "run", jf], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    return r.returncode, lines


with tempfile.TemporaryDirectory() as w:
    src = os.path.join(w, "src", "Filme")
    os.makedirs(src)
    open(os.path.join(w, "s.srt"), "w").write("1\n00:00:00,000 --> 00:00:02,000\nHallo\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=6:s=1280x720:r=25", "-f", "lavfi", "-i", "sine=d=6:f=440",
                    "-f", "lavfi", "-i", "sine=d=6:f=880", "-i", os.path.join(w, "s.srt"), "-map", "0", "-map", "1", "-map", "2", "-map", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "ac3", "-ac", "2", "-c:s", "srt",
                    "-metadata:s:a:0", "language=deu", "-metadata:s:a:1", "language=eng", os.path.join(src, "film.mkv")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=3", "-c:a", "flac", os.path.join(src, "lied.flac")], check=True)
    open(os.path.join(src, "info.txt"), "w").write("text\n")

    o1 = os.path.join(w, "o1")
    rc, lines = run({"sources": [src], "target": o1, "mode": "convert", "video": {"height": 480, "quality": 26},
                     "audio": {"codec": "aac", "kbps": 128, "stereo": True, "tracks": [1]}, "subs": True, "container": "mp4",
                     "music": {"codec": "mp3", "kbps": 192}}, w)
    st = streams(os.path.join(o1, "Filme", "film.mp4"))
    check("convert: exit 0, done line without errors", rc == 0 and lines[-1].get("done") and lines[-1]["errors"] == [])
    check("video: H.264 scaled to 480p", any(s["codec_type"] == "video" and s["codec_name"] == "h264" and s["height"] == 480 for s in st))
    check("audio: only the chosen track (deu), AAC", [s.get("tags", {}).get("language") for s in st if s["codec_type"] == "audio"] == ["deu"]
          and all(s["codec_name"] == "aac" for s in st if s["codec_type"] == "audio"))
    check("subtitles kept as MP4 text", any(s["codec_name"] == "mov_text" for s in st))
    check("music: FLAC -> MP3", [s["codec_name"] for s in streams(os.path.join(o1, "Filme", "lied.mp3"))] == ["mp3"])
    check("other files copied, structure kept", open(os.path.join(o1, "Filme", "info.txt")).read() == "text\n")
    check("progress lines with percent", any("percent" in x for x in lines))

    o2 = os.path.join(w, "o2")
    rc, lines = run({"sources": [os.path.join(src, "film.mkv")], "target": o2, "mode": "convert",
                     "video": {"height": 0, "size_mb": 1.0}, "audio": {"codec": "aac", "kbps": 96, "tracks": None},
                     "subs": False, "container": "mkv"}, w)
    f2 = os.path.join(o2, "film.mkv")
    size = os.path.getsize(f2) if os.path.exists(f2) else 0
    # a size target is an upper bound: easy content (test pattern) stays below it
    check("target size 1 MB: result at most ~1.1 MB", rc == 0 and 0.1e6 < size < 1.15e6)
    st = streams(f2)
    check("MKV: all audio tracks, no subtitles", sum(s["codec_type"] == "audio" for s in st) == 2 and not any(s["codec_type"] == "subtitle" for s in st))

    o3 = os.path.join(w, "o3")
    rc, lines = run({"sources": [src], "target": o3, "mode": "copy"}, w)
    check("copy mode: files unchanged", rc == 0 and open(os.path.join(o3, "Filme", "film.mkv"), "rb").read() ==
          open(os.path.join(src, "film.mkv"), "rb").read())

    open(os.path.join(src, "kaputt.mp4"), "wb").write(b"\0" * 1000)
    rc, lines = run({"sources": [os.path.join(src, "kaputt.mp4")], "target": os.path.join(w, "o4"), "mode": "convert"}, w)
    check("broken file: reported, no .part left", rc == 1 and lines[-1]["errors"] and not os.listdir(os.path.join(w, "o4")))
print("FAILURES %d" % FAIL)
sys.exit(1 if FAIL else 0)
