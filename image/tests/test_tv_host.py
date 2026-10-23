#!/usr/bin/env python3
"""PC test of usr/lib/untrash/pylib/untrash_tv.py (broadcast channels).

- the clock decides what is on (epoch + playlist durations)
- a channel starts on demand: HLS playlist + segments from one ffmpeg
- two viewers read the same files: still one ffmpeg process
- radio profile (audio only), shuffle is stable, idle channels stop
- bad input (empty playlist, missing file, unknown channel) is refused
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "pylib"))
os.environ["ZT_TV_IDLE_S"] = "3"
os.environ["ZT_TV_MAX"] = "1"
import untrash_tv as T  # noqa: E402

FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    FAIL += 0 if ok else 1


def gen(path, secs, video=True):
    src = (["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=%d" % secs] if video else []) + \
        ["-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % secs]
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + src + (["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] if video else [])
                   + ["-c:a", "aac" if video else "libmp3lame", "-shortest", path], check=True)


def main():
    with tempfile.TemporaryDirectory() as w:
        share = os.path.join(w, "share")
        os.makedirs(share + "/Filme/Serie")
        gen(share + "/Filme/a.mp4", 6)
        gen(share + "/Filme/Serie/b.mp4", 4)
        gen(share + "/lied.mp3", 5, video=False)
        open(share + "/Filme/notes.txt", "w").write("x")

        def resolve(sh, p):
            if sh != "media":
                return None
            f = os.path.realpath(os.path.join(share, p))
            return f if f.startswith(share) and os.path.exists(f) else None

        tv = T.TV(w + "/tv.json", w + "/run", w + "/cache/d.json", resolve)
        def ready(c):
            for _ in range(200):
                if c["id"] not in tv.prep:
                    return
                time.sleep(0.05)

        c = tv.save_channel({"name": "Filmkanal", "items": [{"share": "media", "path": "Filme"}], "profile": "480"})
        try:
            tv.start(c["id"])
            early = False
        except T.Fail as e:
            early = e.code == 503 and "being prepared" in str(e)
        check("before the durations are read: 503 'being prepared'", early or c["id"] not in tv.prep)
        ready(c)
        files = tv.files(c)
        check("folder expands to its videos, sorted, with durations",
              [os.path.basename(p) for p, _d in files] == ["a.mp4", "b.mp4"] and abs(files[0][1] - 6) < 0.3)
        i, off, total = tv.now_playing(c, files, now=c["epoch"] + 7.5)
        check("clock: 7.5 s after the epoch the second file runs at 1.5 s", i == 1 and abs(off - 1.5 + (files[0][1] - 6)) < 0.3)
        i, off, _t = tv.now_playing(c, files, now=c["epoch"] + total + 1)
        check("clock: the playlist loops", i == 0 and abs(off - 1) < 0.01)

        d = tv.wait_ready(c["id"])
        m3u = open(os.path.join(d, "index.m3u8")).read()
        check("on demand: HLS playlist with segments", "#EXTM3U" in m3u and ".ts" in m3u)
        pid = tv.run[c["id"]]["proc"].pid
        tv.touch(c["id"], "10.0.0.2")
        tv.touch(c["id"], "10.0.0.3")
        check("second viewer: same ffmpeg", tv.wait_ready(c["id"]) == d and tv.run[c["id"]]["proc"].pid == pid)
        st = tv.state()["channels"][0]
        check("state: running, two viewers, what is on", st["running"] and st["viewers"] == 2 and st["now"] in ("a.mp4", "b.mp4"))
        r = tv.save_channel({"name": "Radio", "items": [{"share": "media", "path": "lied.mp3"}], "profile": "radio"})
        ready(r)
        try:
            tv.start(r["id"])
            limited = False
        except T.Fail as e:
            limited = e.code == 503
        check("at most ZT_TV_MAX channels at once", limited)
        time.sleep(9)       # idle 3 s + reaper tick 5 s
        check("idle channel stops and cleans up", c["id"] not in tv.run and not os.path.exists(d))
        d2 = tv.wait_ready(r["id"])
        check("radio: audio-only HLS", ".ts" in open(os.path.join(d2, "index.m3u8")).read())
        tv.stop_all()

        s1 = tv.save_channel({"name": "Mix", "items": [{"share": "media", "path": "Filme"}, {"share": "media", "path": "lied.mp3"}],
                              "shuffle": True})
        ready(s1)
        check("shuffle: same order every time", [p for p, _ in tv.files(s1)] == [p for p, _ in tv.files(s1)])
        for bad, why in (({"name": "", "items": [{"share": "media", "path": "lied.mp3"}]}, "no name"),
                         ({"name": "x", "items": []}, "empty playlist"),
                         ({"name": "x", "items": [{"share": "media", "path": "../../etc/passwd"}]}, "path outside the share"),
                         ({"name": "x", "items": [{"share": "media", "path": "lied.mp3"}], "id": "ffffff"}, "unknown channel")):
            try:
                tv.save_channel(bad)
                ok = False
            except T.Fail:
                ok = True
            check("refused: " + why, ok)
        tv2 = T.TV(w + "/tv.json", w + "/run", w + "/cache/d.json", resolve)
        check("durations cached across restarts: no new reading", tv2.state() and not tv2.prep)
        tv.delete(s1["id"])
        check("delete", all(x["id"] != s1["id"] for x in tv.load()["channels"]))
    print("FAILURES %d" % FAIL)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
