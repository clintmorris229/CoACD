#!/usr/bin/env python3
"""Benchmark the CoACD command line tool and check that its output is stable.

Runs the `main` executable on a set of meshes with a fixed seed and reports,
for each mesh, the wall time, the number of convex hulls and a hash of the
output OBJ. Given a second executable, it runs both and reports the speedup
and whether the outputs are identical, so a change can be checked for both
performance and unchanged results.

Examples:
    # Time one build on the bundled examples.
    python scripts/benchmark.py --bin build/main

    # Compare two builds (e.g. main vs. a branch), 3 runs each.
    python scripts/benchmark.py --baseline build-main/main --candidate build/main --runs 3

Only the Python standard library is needed.
"""

import argparse
import glob
import hashlib
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time


def run_once(binary, mesh, extra_args, timeout):
    """Runs `binary` on `mesh`; returns (seconds, hull count, output hash)."""
    with tempfile.TemporaryDirectory() as tmp:
        output = os.path.join(tmp, "output.obj")
        cmd = [binary, "-i", mesh, "-o", output, "-ro", os.path.join(tmp, "remesh.obj")]
        cmd += extra_args
        start = time.perf_counter()
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=timeout)
        seconds = time.perf_counter() - start
        if result.returncode != 0 or not os.path.exists(output):
            sys.exit(f"error: {' '.join(cmd)} failed:\n{result.stderr.decode(errors='replace')}")
        with open(output, "rb") as f:
            data = f.read()
    hulls = sum(1 for line in data.splitlines() if line.startswith(b"o "))
    return seconds, hulls, hashlib.sha256(data).hexdigest()


def benchmark(binary, mesh, extra_args, runs, timeout):
    times, hulls, digest = [], None, None
    for _ in range(runs):
        seconds, run_hulls, run_digest = run_once(binary, mesh, extra_args, timeout)
        if digest is not None and run_digest != digest:
            print(f"warning: {os.path.basename(mesh)}: output differs between runs of {binary}",
                  file=sys.stderr)
        times.append(seconds)
        hulls, digest = run_hulls, run_digest
    return {"seconds": statistics.median(times), "hulls": hulls, "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bin", "--baseline", dest="baseline", required=True,
                        help="CoACD `main` executable to benchmark (the baseline when comparing)")
    parser.add_argument("--candidate", help="second `main` executable to compare against the baseline")
    parser.add_argument("--meshes", nargs="+", help="input OBJ files (default: examples/*.obj)")
    parser.add_argument("--runs", type=int, default=1, help="runs per mesh; the median time is reported")
    parser.add_argument("--seed", type=int, default=0, help="seed passed to CoACD (default: 0)")
    parser.add_argument("--args", default="", help='extra arguments for `main`, e.g. "-t 0.1 -nm"')
    parser.add_argument("--timeout", type=float, default=3600, help="timeout per run, in seconds")
    parser.add_argument("--json", help="also write the results to this JSON file")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    meshes = args.meshes or sorted(glob.glob(os.path.join(root, "examples", "*.obj")))
    if not meshes:
        sys.exit("error: no meshes found")
    extra_args = ["-s", str(args.seed)] + shlex.split(args.args)
    binaries = {"baseline": args.baseline}
    if args.candidate:
        binaries["candidate"] = args.candidate

    results = {}
    if args.candidate:
        print(f"{'mesh':<20} {'baseline s':>11} {'candidate s':>12} {'speedup':>8} {'hulls':>6}  identical")
    else:
        print(f"{'mesh':<20} {'seconds':>9} {'hulls':>6}  sha256")
    for mesh in meshes:
        name = os.path.splitext(os.path.basename(mesh))[0]
        results[name] = {key: benchmark(binary, mesh, extra_args, args.runs, args.timeout)
                         for key, binary in binaries.items()}
        base = results[name]["baseline"]
        if args.candidate:
            cand = results[name]["candidate"]
            same = base["sha256"] == cand["sha256"]
            hulls = str(base["hulls"]) if same else f"{base['hulls']}/{cand['hulls']}"
            print(f"{name:<20} {base['seconds']:>11.2f} {cand['seconds']:>12.2f} "
                  f"{base['seconds'] / cand['seconds']:>7.2f}x {hulls:>6}  {'yes' if same else 'NO'}")
        else:
            print(f"{name:<20} {base['seconds']:>9.2f} {base['hulls']:>6}  {base['sha256'][:16]}")
        sys.stdout.flush()

    if args.candidate:
        total_base = sum(r["baseline"]["seconds"] for r in results.values())
        total_cand = sum(r["candidate"]["seconds"] for r in results.values())
        print(f"{'total':<20} {total_base:>11.2f} {total_cand:>12.2f} {total_base / total_cand:>7.2f}x")
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"binaries": binaries, "args": extra_args, "runs": args.runs,
                       "results": results}, f, indent=2)
    if args.candidate and any(r["baseline"]["sha256"] != r["candidate"]["sha256"]
                              for r in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
