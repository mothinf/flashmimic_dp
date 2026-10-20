"""Exercise deployment selection and CLI boundaries without inference or DDS."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

PARITY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PARITY))
import deployment_config as dc


class DeploymentConfigTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory(prefix="deployment inputs ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.project = self.root / "controller project"
        self.controller = self.project / "config/config.yaml"
        self.controller.parent.mkdir(parents=True)
        artifacts = self.project / "artifacts with spaces"
        artifacts.mkdir()
        for name in ("current.onnx", "alternate.onnx", "deploy.yaml", "dance.bin", "dance.npz",
                     "different.bin", "different.npz", "reference.xml"):
            (artifacts / name).write_text("fixture")
        self.artifacts = artifacts
        self.cfg = {"FSM": {"Mimic_WBT_Dance1": {
            "policy": "artifacts with spaces/current.onnx",
            "deploy_config": "artifacts with spaces/deploy.yaml",
            "motion": "artifacts with spaces/dance.bin"}}}
        self.write_config()

    def write_config(self):
        self.controller.write_text(yaml.safe_dump(self.cfg))

    def args(self, *options):
        parser = argparse.ArgumentParser()
        dc.add_deployment_args(parser, motion=True)
        dc.add_geometry_args(parser)
        return parser.parse_args(options)

    def test_default_tracks_the_current_configuration(self):
        with patch.object(dc, "DEFAULT_CONTROLLER", self.controller):
            first = dc.resolve_deployment(self.args(), motion=True)
            self.assertEqual(first.onnx, self.artifacts / "current.onnx")
            self.assertEqual(first.motion, self.artifacts / "dance.npz")
            self.cfg["FSM"]["Mimic_WBT_Dance1"]["policy"] = "artifacts with spaces/alternate.onnx"
            self.write_config()
            self.assertEqual(dc.resolve_deployment(self.args()).onnx, self.artifacts / "alternate.onnx")

    def test_cli_wins_over_environment_and_derives_new_motion_npz(self):
        with patch.dict(os.environ, {"POLICY": str(self.artifacts / "alternate.onnx")}):
            result = dc.resolve_deployment(self.args("--controller-config", str(self.controller),
                "--onnx", str(self.artifacts / "current.onnx"),
                "--motion-bin", str(self.artifacts / "different.bin")), motion=True)
        self.assertEqual(result.onnx, self.artifacts / "current.onnx")
        self.assertEqual(result.motion, self.artifacts / "different.npz")

    def test_relative_controller_paths_do_not_use_callers_working_directory(self):
        command = ["bash", str(PARITY / "run_numeric_check.sh"), "--resolve-only",
                   "--controller-config", str(self.controller)]
        proc = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["onnx"], str(self.artifacts / "current.onnx"))

    def test_symlinked_yaml_keeps_the_controllers_project_root(self):
        snapshot = self.root / "snapshot.yaml"
        self.controller.replace(snapshot)
        self.controller.symlink_to(snapshot)
        result = dc.resolve_deployment(self.args("--controller-config", str(self.controller)))
        self.assertEqual(result.onnx, self.artifacts / "current.onnx")

    def test_legacy_output_argument_takes_precedence_over_out_environment(self):
        output = self.root / "selected output"
        with patch.dict(os.environ, {"OUT": str(self.root / "environment output")}):
            result = subprocess.run(["bash", str(PARITY / "run_numeric_check.sh"), str(output),
                "--controller-config", str(self.controller), "--resolve-only"],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["out"], str(output))

    def test_relocated_config_can_set_project_root_and_state(self):
        other = self.root / "elsewhere.yaml"
        other.write_text(yaml.safe_dump({"FSM": {"SelectedWBT": self.cfg["FSM"]["Mimic_WBT_Dance1"]}}))
        result = dc.resolve_deployment(self.args("--controller-config", str(other),
            "--project-root", str(self.project), "--state", "SelectedWBT"))
        self.assertEqual(result.onnx, self.artifacts / "current.onnx")

    def test_missing_selected_model_fails_without_falling_back(self):
        (self.artifacts / "current.onnx").unlink()
        with self.assertRaisesRegex(ValueError, "FSM.Mimic_WBT_Dance1.policy not found"):
            dc.resolve_deployment(self.args("--controller-config", str(self.controller)))

    def test_missing_npz_has_actionable_error(self):
        (self.artifacts / "dance.npz").unlink()
        with self.assertRaisesRegex(ValueError, "use --motion"):
            dc.resolve_deployment(self.args("--controller-config", str(self.controller)), motion=True)

    def test_explicit_npz_can_have_a_different_name(self):
        renamed = self.artifacts / "reference-only.npz"
        renamed.write_text("fixture")
        (self.artifacts / "dance.npz").unlink()
        result = dc.resolve_deployment(self.args("--controller-config", str(self.controller),
                                                "--motion", str(renamed)), motion=True)
        self.assertEqual(result.motion, renamed)

    def test_unknown_state_does_not_fall_back_to_the_default_state(self):
        with self.assertRaisesRegex(ValueError, "Invalid WBT state 'Typo'"):
            dc.resolve_deployment(self.args("--controller-config", str(self.controller), "--state", "Typo"))

    def test_numeric_can_use_explicit_files_before_setup(self):
        with patch.object(dc, "DEFAULT_CONTROLLER", self.root / "absent/config.yaml"):
            result = dc.resolve_deployment(self.args("--onnx", str(self.artifacts / "current.onnx"),
                                                    "--config", str(self.artifacts / "deploy.yaml")))
            self.assertEqual(result.onnx, self.artifacts / "current.onnx")
            with self.assertRaisesRegex(ValueError, "run scripts/setup.sh first"):
                dc.resolve_deployment(self.args())

    def test_direct_xml_does_not_require_unilab(self):
        xml, source = dc.load_geometry(self.args("--mjcf", str(self.artifacts / "reference.xml"),
                                                "--unilab", str(self.root / "absent")))
        self.assertEqual(xml, "fixture")
        self.assertEqual(source, str(self.artifacts / "reference.xml"))

    def test_unilab_defaults_to_head_and_accepts_tags(self):
        repo = self.root / "training repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        xml = repo / "src/unilab/assets/robots/g1/g1.xml"
        xml.parent.mkdir(parents=True)
        xml.write_text("<mujoco/>")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "core.hooksPath=/dev/null", "commit", "-qm", "geometry fixture")
        git("tag", "selected-geometry")
        for ref in ("HEAD", "selected-geometry"):
            content, source = dc.load_geometry(self.args("--unilab", str(repo), "--unilab-ref", ref))
            self.assertEqual(content, "<mujoco/>")
            self.assertIn(git("rev-parse", "HEAD"), source)
        self.assertEqual(self.args().unilab_ref, "HEAD")
        with self.assertRaisesRegex(ValueError, "Set --unilab/--unilab-ref or use --mjcf"):
            dc.load_geometry(self.args("--unilab", str(repo), "--unilab-ref", "missing-branch"))


if __name__ == "__main__":
    unittest.main()
