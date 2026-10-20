#!/usr/bin/env python3
"""Build and run DDS-free checks using the selected deployment inputs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from deployment_config import (WS, add_deployment_args, add_geometry_args,
                               load_geometry, resolve_deployment)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("check", choices=("numeric", "parity"), help=argparse.SUPPRESS)
    p.add_argument("output_dir", nargs="?", type=Path, help="legacy positional output directory")
    add_deployment_args(p, motion=True)
    add_geometry_args(p)
    p.add_argument("--out", type=Path, help="check output directory (also accepts OUT)")
    p.add_argument("--ort", type=Path, default=os.environ.get("ORT", WS / "unitree_rl_lab/deploy/thirdparty/onnxruntime-linux-x64-1.22.0"),
                   help="matching ONNX Runtime installation")
    p.add_argument("--resolve-only", action="store_true", help="print inputs without compiling or inference")
    args = p.parse_args()
    try:
        if args.out is not None and args.output_dir is not None:
            raise ValueError("Use --out or the positional output directory, not both")
        deployment = resolve_deployment(args, motion=args.check == "parity")
        out = Path(args.out or args.output_dir or os.environ.get("OUT") or
                   WS / ".deps/checks" / args.check).expanduser().resolve()
        record = deployment.describe()
        geometry = None
        if args.check == "parity":
            geometry, record["geometry"] = load_geometry(args)
        record["out"] = str(out)
        print(json.dumps(record, indent=2), flush=True)
        if args.resolve_only:
            return
        ort = args.ort.expanduser().resolve()
        lib = ort / "lib/libonnxruntime.so.1"
        if not lib.is_file():
            raise ValueError(f"ONNX Runtime not found: {lib}; run setup.sh or pass --ort")
        out.mkdir(parents=True, exist_ok=True)
        (out / "inputs.json").write_text(json.dumps(record, indent=2) + "\n")
        runtime_dir = out / "lib"
        runtime_dir.mkdir(exist_ok=True)
        soname = runtime_dir / "libonnxruntime.so.1"
        real_lib = lib.resolve()
        if not (soname.is_file() and soname.resolve() == real_lib):
            if soname.exists() and not soname.is_symlink():
                raise ValueError(f"Refusing to replace an existing library: {soname}")
            if soname.is_symlink():
                soname.unlink()
            soname.symlink_to(real_lib)
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, [str(runtime_dir), str(ort / "lib"), env.get("LD_LIBRARY_PATH")]))

        def run(command: list[str]) -> None:
            print("+ " + shlex.join([str(x) for x in command]), flush=True)
            subprocess.run([str(x) for x in command], check=True, env=env)

        deploy = WS / "unitree_rl_lab/deploy"
        common = ["g++", "-std=c++17", "-O2", "-I", str(deploy / "include"),
                  "-I", str(ort / "include")]
        if args.check == "numeric":
            binary = out / "mimiclite_numeric_check"
            run(common + [str(WS / "scripts/parity/mimiclite_numeric_check.cpp"),
                          str(lib), "-lpthread", "-o", str(binary)])
            run([str(binary), str(deployment.onnx)])
        else:
            # Freeze the geometry so Python consumes exactly the XML recorded above.
            xml = out / "reference_g1.xml"
            xml.write_text(geometry)
            run([sys.executable, str(WS / "scripts/parity/mimiclite_reference.py"),
                 "--controller-config", str(deployment.controller), "--state", deployment.state,
                 "--project-root", str(deployment.project_root),
                 "--config", str(deployment.config), "--onnx", str(deployment.onnx),
                 "--motion-bin", str(deployment.motion_bin), "--motion", str(deployment.motion),
                 "--mjcf", str(xml), "--out", str(out)])
            g1 = deploy / "robots/g1_29dof"
            binary = out / "wbt_parity"
            run(common + ["-I", "/usr/include/eigen3", "-I", str(g1 / "include"),
                          "-I", str(WS / "unitree_sdk2/include"),
                          str(WS / "scripts/parity/wbt_parity.cpp"), str(g1 / "src/WBT_Policy.cpp"),
                          str(lib), "-lyaml-cpp", "-lfmt", "-lpthread", "-o", str(binary)])
            run([str(binary), str(deployment.config), str(deployment.controller),
                 str(deployment.onnx), str(deployment.motion_bin), str(out), deployment.state])
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        p.exit(1, f"CHECK FAILED: {exc}\n")


if __name__ == "__main__":
    main()
