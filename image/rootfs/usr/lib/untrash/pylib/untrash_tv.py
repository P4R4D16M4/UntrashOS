"""UntrashOS broadcast mode ("Sendemodus"): channels with their own playlist.

A channel is a playlist of video or music files.  It runs "like TV": the
programme follows the clock (channel epoch + playlist durations), so whoever
tunes in sees what is on right now, and every device sees the same.  One
ffmpeg per channel writes an HLS live stream (index.m3u8 + short .ts
segments) into a RAM directory; any number of clients fetch the same files,
so ten viewers cost the same CPU as one.

Channels start on demand (first playlist request) and stop after IDLE_S
without requests.  At most MAX_RUNNING channels run at the same time (the
NAS has two Cortex-A9 cores and no hardware encoder).

Store (/etc/untrash/tv.json):
  {"lan_open": true, "channels": [{"id", "name", "items": [{"share", "path"}],
   "profile": "480"|"720"|"copy"|"radio", "shuffle": false, "epoch": unix time}]}
"""
import hashlib
import json
import os
import random
import secrets
import shutil
import subprocess
import threading
import time

FFMPEG = os.environ.get("ZT_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("ZT_FFPROBE", "ffprobe")
IDLE_S = int(os.environ.get("ZT_TV_IDLE_S", "60"))
MAX_RUNNING = int(os.environ.get("ZT_TV_MAX", "2"))
SEG_S = 4
PATHS_TTL = 300
PROFILES = ("480", "720", "copy", "radio")
VIDEO = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".ts", ".mts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg", ".vob"}
AUDIO = {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wav", ".wma"}


class Fail(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


class TV:
    def __init__(self, store, rundir, cache, resolve):
        """resolve(share, path) -> absolute file path or None (admin view)."""
        self.store, self.rundir, self.cache, self.resolve = store, rundir, cache, resolve
        self.lock = threading.Lock()
        self.run = {}               # id -> {"proc", "dir", "last", "started", "viewers": {ip: time}}
        self.durs = None
        self.prep = {}              # id -> {"done", "total"}: durations being read
        self.pcache = {}            # id -> (playlist key, time, paths)
        threading.Thread(target=self._reaper, daemon=True).start()

    # ---------------------------------------------------------------- store
    def load(self):
        try:
            d = json.load(open(self.store))
        except (OSError, ValueError):
            d = {}
        d.setdefault("lan_open", True)
        d.setdefault("channels", [])
        return d

    def _save(self, d):
        os.makedirs(os.path.dirname(self.store), exist_ok=True)
        tmp = self.store + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, self.store)

    def channel(self, cid):
        return next((c for c in self.load()["channels"] if c["id"] == cid), None)

    def save_channel(self, req):
        d = self.load()
        name = (req.get("name") or "").strip()[:40]
        if not name:
            raise Fail("Name des Senders fehlt.")
        items = [{"share": str(x.get("share", "")), "path": str(x.get("path", ""))} for x in req.get("items") or []][:500]
        if not items:
            raise Fail("Die Playlist ist leer.")
        for x in items:
            if not self.resolve(x["share"], x["path"]):
                raise Fail("Nicht gefunden: %s/%s" % (x["share"], x["path"]), 404)
        prof = req.get("profile") if req.get("profile") in PROFILES else "480"
        cid = req.get("id") or ""
        c = next((c for c in d["channels"] if c["id"] == cid), None)
        if cid and not c:
            raise Fail("Unbekannter Sender.", 404)
        if not c:
            if len(d["channels"]) >= 20:
                raise Fail("Höchstens 20 Sender.")
            c = {"id": secrets.token_hex(3), "epoch": int(time.time())}
            d["channels"].append(c)
        c.update(name=name, items=items, profile=prof, shuffle=bool(req.get("shuffle")))
        if "lan_open" in req:
            d["lan_open"] = bool(req["lan_open"])
        self._save(d)
        self.stop(c["id"])          # the next request starts it with the new playlist
        old = self.prep.get(c["id"])
        if old:
            old["cancel"] = True
            self.prep.pop(c["id"], None)
        self.prepare(c)
        return c

    def set_lan_open(self, on):
        d = self.load()
        d["lan_open"] = bool(on)
        self._save(d)

    def delete(self, cid):
        d = self.load()
        n = len(d["channels"])
        d["channels"] = [c for c in d["channels"] if c["id"] != cid]
        if len(d["channels"]) == n:
            raise Fail("Unbekannter Sender.", 404)
        self._save(d)
        self.stop(cid)

    # ------------------------------------------------------------ durations
    # Reading the duration of a big file costs seconds on this NAS (ffprobe on
    # a sleeping disk, two slow cores).  One background thread per channel
    # reads each file exactly once into a persistent cache ("preparing");
    # status requests and the window never probe, they only read the cache.
    def _key(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return hashlib.sha1(("%s|%d|%d" % (path, st.st_size, int(st.st_mtime))).encode()).hexdigest()[:16]

    def _cached(self, path):
        if self.durs is None:
            try:
                self.durs = json.load(open(self.cache))
            except (OSError, ValueError):
                self.durs = {}
        k = self._key(path)
        return None if k is None else self.durs.get(k)

    def _probe(self, path):
        try:
            out = subprocess.run(["nice", "-n", "10", FFPROBE, "-v", "error", "-analyzeduration", "0", "-probesize", "1M",
                                  "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=120).stdout.strip()
            return float(out or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return 0.0

    def _flush(self):
        try:
            os.makedirs(os.path.dirname(self.cache), exist_ok=True)
            with open(self.cache + ".tmp", "w") as f:
                json.dump(self.durs, f)
            os.replace(self.cache + ".tmp", self.cache)
        except OSError:
            pass

    def _prepare(self, cid, paths):
        pr = self.prep[cid]
        for n, p in enumerate(paths):
            if pr.get("cancel"):
                break
            if self._cached(p) is None:
                d = self._probe(p)
                k = self._key(p)
                if k:
                    with self.lock:
                        self.durs[k] = d
                if n % 10 == 9:
                    self._flush()
            pr["done"] = n + 1
        self._flush()
        with self.lock:
            if self.prep.get(cid) is pr:
                del self.prep[cid]

    def prepare(self, c, paths=None):
        """Start reading the missing durations of a channel (no-op if running).
        Returns (known, total)."""
        paths = self.paths(c) if paths is None else paths
        missing = [p for p in paths if self._cached(p) is None]
        if missing:
            with self.lock:
                if c["id"] not in self.prep:
                    self.prep[c["id"]] = {"done": 0, "total": len(missing)}
                    threading.Thread(target=self._prepare, args=(c["id"], missing), daemon=True).start()
        return len(paths) - len(missing), len(paths)

    def paths(self, c):
        """Playlist files in order; folders expand to their media files.
        Cached for PATHS_TTL s: walking big folders keeps the disks awake."""
        key = json.dumps([c["items"], c.get("profile"), c.get("shuffle"), c.get("epoch")], sort_keys=True)
        hit = self.pcache.get(c["id"])
        if hit and hit[0] == key and time.time() - hit[1] < PATHS_TTL:
            return hit[2]
        out = self._paths(c)
        self.pcache[c["id"]] = (key, time.time(), out)
        return out

    def _paths(self, c):
        out = []
        exts = AUDIO if c.get("profile") == "radio" else VIDEO | AUDIO
        for x in c["items"]:
            p = self.resolve(x["share"], x["path"])
            if not p:
                continue
            if os.path.isdir(p):
                for d, dirs, fs in os.walk(p):
                    dirs[:] = sorted(y for y in dirs if not y.startswith(".") and y != "@Recycle")
                    out += [os.path.join(d, f) for f in sorted(fs) if os.path.splitext(f)[1].lower() in exts
                            and not f.startswith(".")]
            elif os.path.splitext(p)[1].lower() in exts:
                out.append(p)
        if c.get("shuffle"):
            random.Random(c.get("epoch", 0)).shuffle(out)      # same order for everyone, stable per channel
        return out[:2000]

    def files(self, c, paths=None):
        """[(path, duration)] of the files whose duration is known and > 0."""
        paths = self.paths(c) if paths is None else paths
        return [(p, d) for p, d in ((p, self._cached(p)) for p in paths) if d]

    def now_playing(self, c, files=None, now=None):
        """(index, offset in seconds, total) of what the clock says is on."""
        files = self.files(c) if files is None else files
        total = sum(d for _p, d in files)
        if not total:
            return None, 0.0, 0.0
        off = ((now or time.time()) - c.get("epoch", 0)) % total
        for i, (_p, d) in enumerate(files):
            if off < d:
                return i, off, total
            off -= d
        return 0, 0.0, total

    # -------------------------------------------------------------- running
    def _cmd(self, c, listfile, outdir):
        prof = c.get("profile", "480")
        cmd = [FFMPEG, "-nostdin", "-hide_banner", "-v", "error", "-re", "-f", "concat", "-safe", "0", "-i", listfile]
        if prof == "radio":
            cmd += ["-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100"]
        elif prof == "copy":
            # picture unchanged; sound to AAC (cheap) since AC3/DTS do not play in browsers
            cmd += ["-map", "0:v:0?", "-map", "0:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000"]
        else:
            h = int(prof)
            cmd += ["-map", "0:v:0?", "-map", "0:a:0?",
                    "-vf", "scale=-2:'min(%d,ih)',setsar=1,fps=25,format=yuv420p" % h,
                    "-c:v", "libx264", "-preset", os.environ.get("ZT_TV_PRESET", "ultrafast"), "-tune", "zerolatency",
                    "-crf", "26", "-maxrate", "1800k" if h <= 480 else "3000k", "-bufsize", "4000k",
                    "-force_key_frames", "expr:gte(t,n_forced*%d)" % SEG_S,
                    "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000"]
        return cmd + ["-f", "hls", "-hls_time", str(SEG_S), "-hls_list_size", "6",
                      "-hls_flags", "delete_segments+omit_endlist+independent_segments+program_date_time",
                      "-hls_segment_filename", os.path.join(outdir, "seg%06d.ts"), os.path.join(outdir, "index.m3u8")]

    def start(self, cid):
        """Start a channel (no-op when running); returns its HLS directory."""
        with self.lock:
            r = self.run.get(cid)
            if r and r["proc"].poll() is None:
                r["last"] = time.time()
                return r["dir"]
        c = self.channel(cid)
        if not c:
            raise Fail("Unbekannter Sender.", 404)
        paths = self.paths(c)
        known, n = self.prepare(c, paths)
        if known < n:
            raise Fail("Sender wird vorbereitet: %d von %d Dateien gelesen." % (known, n), 503)
        with self.lock:
            files = self.files(c, paths)
            i, off, total = self.now_playing(c, files)
            if i is None:
                raise Fail("Keine abspielbaren Dateien in der Playlist.")
            r = self.run.get(cid)
            if r and r["proc"].poll() is None:      # another request started it meanwhile
                r["last"] = time.time()
                return r["dir"]
            if sum(1 for x in self.run.values() if x["proc"].poll() is None) >= MAX_RUNNING:
                raise Fail("Es laufen schon %d Sender, mehr schafft die NAS nicht gleichzeitig." % MAX_RUNNING, 503)
            d = os.path.join(self.rundir, cid)
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            # what is on now (from its current position), then the playlist
            # again and again: at least 12 hours; afterwards the channel restarts
            seq, acc = [(files[i][0], off)], files[i][1] - off
            j = i
            while acc < 12 * 3600 and len(seq) < 20000:
                j = (j + 1) % len(files)
                seq.append((files[j][0], 0.0))
                acc += files[j][1]
            with open(os.path.join(d, "list.txt"), "w") as f:
                f.write("ffconcat version 1.0\n")
                for p, o in seq:
                    f.write("file '%s'\n" % p.replace("'", "'\\''"))
                    if o > 0.5:
                        f.write("inpoint %.2f\n" % o)
            p = subprocess.Popen(["nice", "-n", "5"] + self._cmd(c, os.path.join(d, "list.txt"), d),
                                 stdout=subprocess.DEVNULL, stderr=open(os.path.join(d, "ffmpeg.log"), "w"),
                                 start_new_session=True)
            self.run[cid] = {"proc": p, "dir": d, "last": time.time(), "started": time.time(), "viewers": {}}
            return d

    def wait_ready(self, cid, timeout=20):
        d = self.start(cid)
        end = time.time() + timeout
        while time.time() < end:
            if os.path.exists(os.path.join(d, "index.m3u8")):
                return d
            r = self.run.get(cid)
            if not r or r["proc"].poll() is not None:
                break
            time.sleep(0.2)
        log = ""
        try:
            log = open(os.path.join(d, "ffmpeg.log")).read().strip().splitlines()[-1]
        except (OSError, IndexError):
            pass
        self.stop(cid)
        raise Fail("Der Sender startet nicht%s" % (": " + log if log else "."), 500)

    def touch(self, cid, ip):
        r = self.run.get(cid)
        if r:
            r["last"] = time.time()
            r["viewers"][ip] = time.time()

    def stop(self, cid):
        with self.lock:
            r = self.run.pop(cid, None)
        if r:
            try:
                os.killpg(r["proc"].pid, 15)
            except OSError:
                pass
            try:
                r["proc"].wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(r["proc"].pid, 9)
            shutil.rmtree(r["dir"], ignore_errors=True)

    def stop_all(self):
        for cid in list(self.run):
            self.stop(cid)

    def _reaper(self):
        while True:
            time.sleep(5)
            now = time.time()
            for cid, r in list(self.run.items()):
                if now - r["last"] > IDLE_S or r["proc"].poll() is not None:
                    self.stop(cid)

    def running(self):
        """[(name, viewers)] of running channels; cheap (activity bar polls it)."""
        now = time.time()
        names = {c["id"]: c["name"] for c in self.load()["channels"]}
        return [(names.get(cid, cid), sum(1 for t in r["viewers"].values() if now - t < 3 * SEG_S + 5))
                for cid, r in list(self.run.items()) if r["proc"].poll() is None]

    def state(self):
        out = []
        now = time.time()
        d = self.load()
        for c in d["channels"]:
            r = self.run.get(c["id"])
            running = bool(r and r["proc"].poll() is None)
            paths = self.paths(c)
            files = self.files(c, paths)
            i, off, total = self.now_playing(c, files)
            pr = self.prep.get(c["id"])
            if not pr and len(files) < len(paths) and any(self._cached(p) is None for p in paths):
                self.prepare(c, paths)          # e.g. after a restart: continue in the background
                pr = self.prep.get(c["id"])
            out.append({"id": c["id"], "name": c["name"], "profile": c.get("profile", "480"), "items": c["items"],
                        "preparing": {"done": pr["done"], "total": pr["total"]} if pr else None,
                        "shuffle": c.get("shuffle", False), "running": running, "files": len(files), "total_s": int(total),
                        "now": os.path.basename(files[i][0]) if i is not None else "", "now_left_s": int(files[i][1] - off) if i is not None else 0,
                        "viewers": sum(1 for t in (r["viewers"].values() if r else []) if now - t < 3 * SEG_S + 5)})
        return {"lan_open": d["lan_open"], "channels": out, "max_running": MAX_RUNNING}
