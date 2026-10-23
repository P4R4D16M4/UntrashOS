#!/usr/bin/env python3
"""Host test for event scores and safe PWM5 sysfs hand-off (no hardware)."""
import os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "rootfs/usr/lib/untrash/untrash-sound")
BOOT_UNIT = os.path.join(ROOT, "rootfs/usr/lib/systemd/system/untrash-sound.service")
EXPECT = {"boot": 25, "shutdown": 5, "error": 3, "critical": 6,
          "success": 7, "connect": 2, "disconnect": 2, "warning": 6, "standby": 7}
fails = 0
def check(n, ok):
    global fails; print(("ok   " if ok else "FAIL ") + n); fails += not ok
with tempfile.TemporaryDirectory() as w:
    log = os.path.join(w, "tones")
    env = dict(os.environ, ZT_SOUND_DEVICE=os.path.join(w, "tone"), ZT_SOUND_LOG=log,
               ZT_SOUND_LOCK=os.path.join(w, "sound.lock"), ZT_SOUND_NO_SLEEP="1")
    for event, notes in EXPECT.items():
        r = subprocess.run([TOOL, "play", event], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        got = [int(x) for x in open(log).read().splitlines()]; open(log, "w").close()
        score = __import__('runpy').run_path(TOOL)['SCORES'][event]
        sounding = sum(hz != 0 for hz, _ in score)
        check(event + " score has every note and a final off", r.returncode == 0 and len(got) == sounding * 2 + len(score) - sounding + 1 and got[-1] == 0 and any(got))
    r = subprocess.run([TOOL, "play", "nope"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("unknown event refused", r.returncode == 2)
    # Desk synthesizer: user score with tempo, play-json, show, broken file
    import json
    env2 = dict(env, ZT_SOUND_USER=os.path.join(w, "sounds.json"), ZT_SOUND_LOG_MS="1")
    json.dump({"events": {"boot": {"notes": [[1047, 100], [0, 50], [831, 200]], "tempo": 2.0}}},
              open(env2["ZT_SOUND_USER"], "w"))
    open(log, "w").close()
    r = subprocess.run([TOOL, "play", "boot"], env=env2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    got = open(log).read().split(chr(10))
    check("user score replaces the built-in one, tempo 2.0 doubles the lengths",
          r.returncode == 0 and "1047 200" in got and "831 400" in got)
    open(log, "w").close()
    r = subprocess.run([TOOL, "play-json"], env=env2, input='{"notes": [[440, 120]], "tempo": 0.5}',
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    check("play-json plays a score from stdin (tempo 0.5)", r.returncode == 0 and "440 60" in open(log).read())
    r = subprocess.run([TOOL, "play-json"], env=env2, input='{"notes": [[99999, 120]]}',
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    check("play-json refuses a frequency the buzzer cannot play", r.returncode == 2)
    r = subprocess.run([TOOL, "show"], env=env2, stdout=subprocess.PIPE, text=True)
    sh = json.loads(r.stdout)
    check("show: built-in and user scores", "boot" in sh["builtin"] and sh["user"]["boot"]["tempo"] == 2.0)
    open(env2["ZT_SOUND_USER"], "w").write("{broken")
    open(log, "w").close()
    r = subprocess.run([TOOL, "play", "boot"], env=env2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    check("broken sounds.json: built-in score plays", r.returncode == 0 and open(log).read().startswith("1047 115"))
unit = open(BOOT_UNIT).read()
check("boot sound also enabled in installer", "ConditionKernelCommandLine" not in unit and
      "ExecStart=/usr/lib/untrash/untrash-sound --optional play boot" in unit)
print("SOUND HOST TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
sys.exit(1 if fails else 0)
