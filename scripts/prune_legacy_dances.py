#!/usr/bin/env python3
"""Remove upstream demo dances without rewriting deployment paths or gains."""
import argparse
import copy
from pathlib import Path
import shutil
import tempfile

import yaml

LEGACY = {"Mimic_Dance_102", "Mimic_Gangnam_Style"}
DEFAULT_CONFIG = (Path(__file__).resolve().parents[1]
                  / "unitree_rl_lab/deploy/robots/g1_29dof/config/config.yaml")


def entries(node):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("expected a YAML mapping in FSM configuration")
    return {key.value: (key, value) for key, value in node.value}


def prune(text):
    """Use YAML locations to remove entries while preserving all other text."""
    original = yaml.safe_load(text)
    fsm = original["FSM"]
    if not isinstance(fsm.get("_"), dict):
        raise ValueError("missing FSM._ enabled states")
    required = {"Passive", "FixStand", "Velocity", "Mimic_WBT_Dance1"}
    if not required.issubset(fsm["_"]) or not required.issubset(fsm):
        raise ValueError("expected the WBT deployment with its three base states")

    expected = copy.deepcopy(original)
    nodes = entries(entries(yaml.compose(text))["FSM"][1])
    lines = text.splitlines(keepends=True)
    removed = set()

    def remove(mapping, name):
        if name not in mapping:
            return
        key, value = mapping[name]
        start = key.start_mark.line
        block = isinstance(value, (yaml.MappingNode, yaml.SequenceNode)) and not value.flow_style
        end = value.end_mark.line + (not block and bool(value.end_mark.column))
        # A mapping's end can include the next section's leading comments.
        while end > start + 1 and (not lines[end - 1].strip()
                                  or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        removed.update(range(start, end))

    enabled = entries(nodes["_"][1])
    for name in LEGACY:
        remove(enabled, name)
        remove(nodes, name)
        expected["FSM"]["_"].pop(name, None)
        expected["FSM"].pop(name, None)
    for name, state in fsm.items():
        if name == "_" or name in LEGACY or not isinstance(state, dict):
            continue
        if "transitions" in state:
            transitions = entries(entries(nodes[name][1])["transitions"][1])
            for target in LEGACY:
                remove(transitions, target)
                expected["FSM"][name]["transitions"].pop(target, None)

    result = "".join(line for i, line in enumerate(lines) if i not in removed)
    # Refuse unfamiliar layouts (e.g. inline mappings) instead of changing
    # unrelated settings. No file is written until this comparison passes.
    if yaml.safe_load(result) != expected:
        raise ValueError("unsupported YAML layout; configuration left unchanged")
    return result


def update(path):
    path = path.resolve(strict=True)
    original = path.read_text()
    result = prune(original)
    if result == original:
        print("[FSM] single-dance configuration already in place")
        return False
    backup = path.with_name(path.name + ".before-single-dance")
    if not backup.exists():
        shutil.copy2(path, backup)
    # Replace atomically so an interrupted write cannot truncate the YAML.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(result)
        shutil.copymode(path, temporary)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"[FSM] removed the two upstream demo dances; backup: {backup}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        update(args.config)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
