"""Shared offline inputs; controller paths resolve exactly like State_WBT."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

import yaml

WS = Path(__file__).resolve().parents[2]
DEFAULT_CONTROLLER = WS / "unitree_rl_lab/deploy/robots/g1_29dof/config/config.yaml"


@dataclass(frozen=True)
class Deployment:
    controller: Path
    project_root: Path
    state: str
    config: Path
    onnx: Path
    motion_bin: Path | None = None
    motion: Path | None = None

    def describe(self) -> dict[str, str]:
        return {key: str(value) for key, value in vars(self).items() if value is not None}


def add_deployment_args(parser: argparse.ArgumentParser, *, motion: bool = False) -> None:
    parser.add_argument("--controller-config", type=Path,
                        default=os.environ.get("CONTROLLER_CONFIG"),
                        help="controller config.yaml (default: prepared g1_29dof/config/config.yaml)")
    parser.add_argument("--state", default=os.environ.get("FSM_STATE", "Mimic_WBT_Dance1"),
                        help="WBT state in the controller configuration")
    parser.add_argument("--project-root", type=Path, default=os.environ.get("CONTROLLER_ROOT"),
                        help="controller project root for YAML-relative paths (default: config directory's parent)")
    parser.add_argument("--config", type=Path, default=os.environ.get("DEPLOY_CONFIG"),
                        help="override the state's deployment YAML")
    parser.add_argument("--onnx", "--policy", type=Path, default=os.environ.get("POLICY"),
                        help="override the state's ONNX policy")
    if motion:
        parser.add_argument("--motion-bin", type=Path, default=os.environ.get("MOTION_BIN"),
                            help="override the state's binary motion")
        parser.add_argument("--motion", "--motion-npz", type=Path,
                            default=os.environ.get("MOTION_NPZ"),
                            help="reference NPZ (default: binary motion path with .npz suffix)")


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} not found: {path}")
    return path


def resolve_deployment(args: argparse.Namespace, *, motion: bool = False) -> Deployment:
    # Resolve relative YAML values against the logical config location, not a symlink target.
    controller = Path(os.path.abspath(Path(args.controller_config or DEFAULT_CONTROLLER).expanduser()))
    project_root = Path(args.project_root or controller.parent.parent).expanduser().resolve()
    state_cfg = {}
    # Explicit numeric inputs also work before setup.sh prepares the controller.
    needs_controller = motion or args.controller_config is not None or not (args.config and args.onnx)
    if needs_controller:
        if not controller.is_file():
            raise ValueError(f"Controller configuration not found: {controller}; "
                             "run scripts/setup.sh first or pass --controller-config")
        try:
            state_cfg = yaml.safe_load(controller.read_text())["FSM"][args.state]
            if not isinstance(state_cfg, dict):
                raise KeyError(args.state)
        except (KeyError, TypeError, yaml.YAMLError) as exc:
            raise ValueError(f"Invalid WBT state {args.state!r} in {controller}: {exc}") from exc

    def select(override: Path | None, key: str) -> Path:
        if override is not None:
            return require_file(Path(override), key)
        if key not in state_cfg or not isinstance(state_cfg[key], str):
            raise ValueError(f"Missing FSM.{args.state}.{key} in {controller}")
        path = Path(state_cfg[key])
        if not path.is_absolute():
            path = project_root / path
        return require_file(path, f"FSM.{args.state}.{key}")

    config = select(args.config, "deploy_config")
    onnx = select(args.onnx, "policy")
    binary = select(args.motion_bin, "motion") if motion else None
    npz = require_file(Path(args.motion) if args.motion else binary.with_suffix(".npz"),
                       "Motion NPZ; use --motion when it has a different name") if motion else None
    return Deployment(controller, project_root, args.state, config, onnx, binary, npz)


def add_geometry_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mjcf", type=Path, default=os.environ.get("MJCF"),
                        help="matching G1 XML file; no UniLab Git repository needed")
    parser.add_argument("--unilab", type=Path,
                        default=os.environ.get("UNILAB", WS.parent / "UniLab"),
                        help="UniLab Git repository used when --mjcf is absent")
    parser.add_argument("--unilab-ref", default=os.environ.get("UNILAB_REF", "HEAD"),
                        help="UniLab commit, tag or branch (default: HEAD)")


def load_geometry(args: argparse.Namespace) -> tuple[str, str]:
    if args.mjcf is not None:
        path = require_file(Path(args.mjcf), "MJCF")
        return path.read_text(), str(path)
    repo = Path(args.unilab).expanduser().resolve()
    ref = args.unilab_ref
    if not ref or ref.startswith("-"):
        raise ValueError(f"Invalid UniLab reference: {ref!r}")
    try:
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
                                check=True, capture_output=True, text=True).stdout.strip()
        xml = subprocess.run(["git", "-C", str(repo), "show",
                              f"{commit}:src/unilab/assets/robots/g1/g1.xml"],
                             check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"Cannot read G1 XML from UniLab {repo} at {ref!r}. "
                         f"Set --unilab/--unilab-ref or use --mjcf. {exc.stderr.strip()}") from exc
    return xml, f"{repo} @ {commit} (requested {ref})"
