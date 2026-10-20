"""Verify migration of existing deployment settings without running the FSM."""
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prune_legacy_dances import prune, update


CONFIG = textwrap.dedent('''\
FSM:
  _:
    Passive: {id: 1}
    FixStand: {id: 2}
    Velocity: {id: 3, type: RLBase}
    Mimic_Dance_102:
      id: 101
      type: Mimic
    Mimic_Gangnam_Style:
      id: 102
      type: Mimic
    # Keep the selected WBT model.
    Mimic_WBT_Dance1: {id: 110, type: WBT}
  Passive:
    transitions:
      FixStand: LT + up.on_pressed
    kd: [3, 3, 3]
  FixStand:
    transitions:
      Passive: LT + B.on_pressed
      Velocity: RB + X.on_pressed
      Mimic_Dance_102: custom legacy shortcut
    ts: [0, 3]
  Velocity:
    transitions:
      Passive: LT + B.on_pressed
      Mimic_Dance_102: LT(2s) + down.on_pressed
      Mimic_Gangnam_Style: LT(2s) + left.on_pressed
      Mimic_WBT_Dance1: LT(2s) + right.on_pressed
    policy_dir: config/policy/velocity
  Mimic_Dance_102:
    policy_dir: legacy/dance102
  Mimic_Gangnam_Style:
    policy_dir: legacy/gangnam

  # Selected model and gains must survive unchanged.
  Mimic_WBT_Dance1:
    transitions:
      Passive: LT + B.on_pressed
      Velocity: RB + X.on_pressed
    policy: "models/policy 1020.onnx"  # operator-selected
    motion: "motions/current dance.bin"
    deploy_config: params/current.yaml
    kp: [40.179, 99.098]
    kd: [2.558, 6.309]
    time_start: 1.2
''')


class PruneLegacyDancesTests(unittest.TestCase):
    def test_only_four_enabled_states_and_no_dangling_transitions(self):
        fsm = yaml.safe_load(prune(CONFIG))["FSM"]
        self.assertEqual(list(fsm["_"]), ["Passive", "FixStand", "Velocity", "Mimic_WBT_Dance1"])
        self.assertEqual({s: v["id"] for s, v in fsm["_"].items()},
                         {"Passive": 1, "FixStand": 2, "Velocity": 3, "Mimic_WBT_Dance1": 110})
        self.assertEqual(set(fsm), {"_", *fsm["_"]})
        for name in fsm["_"]:
            self.assertLessEqual(set(fsm[name]["transitions"]), set(fsm["_"]))

    def test_retained_states_parameters_and_comments_are_preserved(self):
        result = prune(CONFIG)
        before = yaml.safe_load(CONFIG)["FSM"]
        after = yaml.safe_load(result)["FSM"]
        for name in ("Passive", "Mimic_WBT_Dance1"):
            self.assertEqual(before[name], after[name])
        self.assertEqual(before["Velocity"]["policy_dir"], after["Velocity"]["policy_dir"])
        for line in ('    policy: "models/policy 1020.onnx"  # operator-selected\n',
                     '  # Selected model and gains must survive unchanged.\n',
                     '    # Keep the selected WBT model.\n'):
            self.assertIn(line, result)

    def test_repeat_is_byte_identical(self):
        once = prune(CONFIG)
        self.assertEqual(prune(once), once)

    def test_backup_is_original_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(CONFIG)
            self.assertTrue(update(path))
            self.assertEqual(path.with_name("config.yaml.before-single-dance").read_text(), CONFIG)
            path.write_text(path.read_text().replace("1020.onnx", "1021.onnx"))
            self.assertFalse(update(path))
            self.assertIn("1021.onnx", path.read_text())
            self.assertEqual(path.with_name("config.yaml.before-single-dance").read_text(), CONFIG)

    def test_rejects_non_wbt_config_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            invalid = CONFIG.replace("    Mimic_WBT_Dance1: {id: 110, type: WBT}\n", "")
            path.write_text(invalid)
            with self.assertRaisesRegex(ValueError, "expected the WBT deployment"):
                update(path)
            self.assertEqual(path.read_text(), invalid)
            self.assertFalse(path.with_name("config.yaml.before-single-dance").exists())

    def test_rejects_shared_line_layout_without_removing_unrelated_states(self):
        # A single YAML line contains legacy and retained states; line deletion
        # cannot safely preserve it, so fail instead of rewriting that line.
        data = yaml.safe_load(CONFIG)
        inline = yaml.safe_dump(data, default_flow_style=True, width=100000)
        with self.assertRaises((ValueError, yaml.YAMLError, TypeError)):
            prune(inline)


if __name__ == "__main__":
    unittest.main()
