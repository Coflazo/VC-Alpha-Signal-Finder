"""Build the optional C++ extension.

Separate from install on purpose. The package works without it via the pure-Python
fallback in fastpath.py, and requiring a compiler to install would exclude most of
the people this is for. Run this when you want the speed:

    uv run python scripts/build_ext.py

Measured against the fallback: 43x on cosine over stored vectors, 279x on MinHash.
"""

import subprocess
import sys
import sysconfig
from pathlib import Path

try:
    import pybind11
except ImportError:
    sys.exit("pybind11 is needed to build the extension: uv pip install pybind11")

root = Path(__file__).resolve().parent.parent
suffix = sysconfig.get_config_var("EXT_SUFFIX")
out = root / "vc_alpha" / f"_fastops{suffix}"

cmd = [
    "c++", "-O3", "-Wall", "-shared", "-std=c++17", "-fPIC",
    f"-I{pybind11.get_include()}",
    f"-I{sysconfig.get_paths()['include']}",
    str(root / "src" / "fastops.cpp"), "-o", str(out),
]
if sys.platform == "darwin":
    cmd.insert(-3, "-undefined")
    cmd.insert(-3, "dynamic_lookup")

print(" ".join(cmd))
result = subprocess.run(cmd)
if result.returncode:
    sys.exit("build failed — the pure-Python fallback will be used instead")
print(f"built {out.name}")
