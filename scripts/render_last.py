"""Render the latest benchmark's layout answers for visual inspection.

Pass an output directory as the first argument; by default PNGs go to the system temp directory.
"""
import os
import sys
import tempfile
from pathlib import Path

from slidearena import cases as C
from slidearena import config, llm, render

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "slidearena-render"
tasks = sys.argv[2:] or None
os.makedirs(out, exist_ok=True)
b = config.load("benchmarks.json", [])[-1]
lc = {c["id"]: c for c in C.LAYOUT}
for r in b["records"]:
    if r["kind"] == "layout" and r.get("answer") and (not tasks or r["task"] in tasks):
        png = render.render_layout(llm.extract_json(r["answer"]), lc[r["task"]])
        with open(os.path.join(out, f"{r['task']}_{r['model_id']}_{r['rep']}.png"), "wb") as f:
            f.write(png)
print("ok")
