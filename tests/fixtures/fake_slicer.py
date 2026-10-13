#!/usr/bin/env python3
"""Stand-in for CrealityPrint's AppRun in unit tests. FAKE_MODE picks the behaviour."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

GCODE = Path(__file__).parent / "gcode" / "creality_k2.gcode"


def main() -> int:
    args = sys.argv[1:]
    out = Path(args[args.index("--outputdir") + 1])
    (out / "argv.json").write_text(json.dumps(args))
    mode = os.environ.get("FAKE_MODE", "ok")
    if mode == "ok":
        shutil.copy(GCODE, out / "plate_1.gcode")
        plates = [{"id": 1, "warning_message": "", "triangle_count": 12}]
        result = {"return_code": 0, "error_string": "Success.", "sliced_plates": plates}
        (out / "result.json").write_text(json.dumps(result))
        return 0
    if mode == "rc17":
        result = {
            "return_code": -17,
            "error_string": "The selected printer is not compatible",
            "sliced_plates": [],
        }
        (out / "result.json").write_text(json.dumps(result))
        return 250
    if mode == "noresult":
        print("[trace] noise")
        print("[error] boom")
        return 254
    if mode == "warn":
        # Plates 2 and 10: numeric order, and a warning only on plate 10.
        for n in (10, 2):
            shutil.copy(GCODE, out / f"plate_{n}.gcode")
        plates = [{"id": 2, "warning_message": ""}, {"id": 10, "warning_message": "overhang"}]
        result = {"return_code": 0, "error_string": "Success.", "sliced_plates": plates}
        (out / "result.json").write_text(json.dumps(result))
        return 0
    if mode == "nogcode":
        result = {"return_code": 0, "error_string": "Success.", "sliced_plates": []}
        (out / "result.json").write_text(json.dumps(result))
        return 0
    if mode == "sleep":
        # A child in the same process group must die with the slicer.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (out / "child_pid").write_text(str(child.pid))
        (out / "pid").write_text(str(os.getpid()))
        time.sleep(30)
    return 1


if __name__ == "__main__":
    sys.exit(main())
