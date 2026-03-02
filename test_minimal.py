"""Minimal platform test — no f-strings with quotes."""
import subprocess
import os
import sys

os.environ["DISPLAY"] = ":99"
TMP = "/tmp/scrot_minimal.png"

print("1. scrot test...")
r = subprocess.run(["scrot", "-o", TMP], capture_output=True, text=True, timeout=5)
print("   exit=" + str(r.returncode) + " stderr=" + r.stderr.strip())
exists = os.path.exists(TMP)
print("   file exists: " + str(exists))
if exists:
    print("   size: " + str(os.path.getsize(TMP)))

print("2. xdotool mouse location...")
r2 = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True, timeout=5)
print("   " + r2.stdout.strip())

print("3. xdotool click 300 300...")
r3 = subprocess.run(["xdotool", "mousemove", "300", "300", "click", "1"],
                     capture_output=True, text=True, timeout=5)
print("   exit=" + str(r3.returncode))

print("4. xdotool type...")
r4 = subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "12", "echo hello"],
                     capture_output=True, text=True, timeout=5)
print("   exit=" + str(r4.returncode))

print("5. xdotool key Return...")
r5 = subprocess.run(["xdotool", "key", "--clearmodifiers", "Return"],
                     capture_output=True, text=True, timeout=5)
print("   exit=" + str(r5.returncode))

print("6. after screenshot...")
import time
time.sleep(0.5)
TMP2 = "/tmp/scrot_after.png"
r6 = subprocess.run(["scrot", "-o", TMP2], capture_output=True, text=True, timeout=5)
print("   exit=" + str(r6.returncode))
if os.path.exists(TMP2):
    print("   size: " + str(os.path.getsize(TMP2)))

print("7. clipboard test (xsel)...")
p = subprocess.run(["xsel", "--clipboard", "--input"],
                    input="CUE_TEST", capture_output=True, text=True, timeout=5)
p2 = subprocess.run(["xsel", "--clipboard", "--output"],
                     capture_output=True, text=True, timeout=5)
print("   clipboard: " + repr(p2.stdout.strip()))
assert p2.stdout.strip() == "CUE_TEST", "clipboard mismatch!"

print("\nALL PASSED")
