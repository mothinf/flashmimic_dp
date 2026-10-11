# flashmimic_dp

这是 MimicLite WBT（G1 29-DOF）部署端的最小可复现仓库。仓库只保存策略、运动数据、部署补丁和准备/验证脚本；三个 Unitree 上游仓库在执行 `scripts/setup.sh` 时按固定提交下载，因此不会把它们的源码和 `.git` 历史重复放进本仓库。

> **硬件安全声明**：本文和仓库脚本只准备、编译或离线验证代码，不启动 `g1_ctrl`，不初始化 DDS，不读取网卡状态，也不向机器人发送 `LowCmd`。请不要在本次复现中执行任何 `g1_ctrl` 命令。

## 仓库内容

```text
assets/
  policy.onnx + policy.onnx.data       # 397 维观测 -> 29 维动作
  dance1_subject2_part.bin             # 部署端运动片段
  dance1_subject2_part.npz             # 重导出和离线 parity 的原始数据
  mimiclite_dr_140k_deploy_config.yaml # 观测布局、延迟、动作缩放等
patches/                                # 应用于固定版本上游的部署改动
scripts/setup.sh                        # 拉取上游、校验 ORT、应用补丁
scripts/setup_host_deps.sh              # 无 root 时准备本地 libfmt（可选）
scripts/export_motion_bin.py            # NPZ -> 部署端 motion.bin
scripts/parity/                         # 不含 DDS/实机的离线检查
```

`unitree_mujoco/`、`unitree_rl_lab/`、`unitree_sdk2/`、构建目录、`.deps/` 和架构相关的 ONNX Runtime 压缩包均由脚本生成或下载，并已在 `.gitignore` 中排除。

## 支持环境和系统依赖

在 Ubuntu 20.04/22.04 的 `x86_64` 或 `aarch64` 主机上操作。首次准备需要网络访问 GitHub；`aarch64` 主机还会从 ONNX Runtime release 下载 1.22.0，并用 SHA256 校验。

```bash
sudo apt update
sudo apt install -y \
  build-essential cmake git curl file \
  libyaml-cpp-dev libboost-program-options-dev libeigen3-dev \
  libspdlog-dev libfmt-dev
```

## 从零准备并编译（只生成文件）

把 `<仓库地址>` 替换成实际 Git 远端地址：

```bash
git clone <仓库地址> flashmimic_dp
cd flashmimic_dp

# 固定版本：unitree_mujoco、unitree_rl_lab、unitree_sdk2；然后应用本仓库补丁
./scripts/setup.sh

# 安装 SDK2 提供的 DDS 头文件和共享库（g1_ctrl 的 CMake 需要）
cmake -S unitree_sdk2 -B unitree_sdk2/build -DBUILD_EXAMPLES=OFF
sudo cmake --build unitree_sdk2/build --target install
sudo ldconfig

# 编译部署控制器；此命令只产生 g1_ctrl，不会执行它
cmake -S unitree_rl_lab/deploy/robots/g1_29dof \
      -B unitree_rl_lab/deploy/robots/g1_29dof/build \
      -DCMAKE_BUILD_TYPE=Release
cmake --build unitree_rl_lab/deploy/robots/g1_29dof/build --parallel "$(nproc)"
```

编译结果位于 `unitree_rl_lab/deploy/robots/g1_29dof/build/g1_ctrl`。`unitree_sdk2` 的安装步骤不能省略：部署补丁会把匹配固定头文件的 SDK 静态库链接到控制器，同时还需要 SDK2 提供的 CycloneDDS 头文件和共享库。

没有 root 权限时，可以在编译前运行：

```bash
bash scripts/setup_host_deps.sh
```

它只把 `libfmt-dev` 解包到仓库内的 `.deps/`，不启动任何进程；DDS 依赖仍需由系统或管理员安装。

## 离线验证（可选）

以下命令都不创建 DDS participant、不打开网卡、不运行 `g1_ctrl`。

### C++ ONNX 数值检查

这是最适合部署主机的检查，不依赖 Python 的 ONNX Runtime：

```bash
ORT="$PWD/unitree_rl_lab/deploy/thirdparty/onnxruntime-linux-x64-1.22.0"
g++ -std=c++17 -O2 \
  -I unitree_rl_lab/deploy/include -I "$ORT/include" \
  scripts/parity/mimiclite_numeric_check.cpp \
  "$ORT/lib/libonnxruntime.so.1.22.0" -lpthread \
  -o /tmp/mimiclite_numeric_check
LD_LIBRARY_PATH="$ORT/lib" \
  /tmp/mimiclite_numeric_check assets/policy.onnx
```

成功时会打印 `NUMERIC PASS`，并确认 ONNX 输入输出为 `[1,397] -> [1,29]`、输出有限且重复推理稳定。

### Python 数值检查

需要 `numpy`、`pyyaml` 和 `onnxruntime>=1.18`。在有对应 wheel 的主机上执行：

```bash
python3 -m pip install --user numpy pyyaml 'onnxruntime>=1.18'
python3 scripts/parity/mimiclite_numeric_check.py
```

成功时会打印 `NUMERIC PASS`，并检查 YAML 观测布局和一步动作延迟。

### 其他离线检查

完成 `setup.sh` 后可以运行速度状态机的发布门检查：

```bash
bash scripts/parity/run_rlbase_gate_test.sh
```

它用 `scripts/parity/fake_sdk/Types.h` 替代真实 LowState/LowCmd，只验证第一次推理前不会发布错误目标。

完整的 Python/C++ WBT parity 还需要旁边有训练仓库 UniLab（默认路径为 `../UniLab`）：

```bash
PYTHON=python3 UNILAB=/path/to/UniLab bash scripts/parity/run_parity.sh
```

该检查只读运动数据并在 CPU 上比较观测、动作和目标角度，成功时打印 `PARITY PASS`。

## 更新策略或运动片段

把新的 `policy.onnx` 与同目录的 `policy.onnx.data` 一起替换；控制器配置引用 `assets/` 下的文件。训练 NPZ 转为部署端二进制：

```bash
python3 scripts/export_motion_bin.py \
  assets/new_motion.npz assets/new_motion.bin
```

运行离线检查确认通过后，再由有硬件操作资质的人另行制定实机流程；本仓库 README 不包含实机启动步骤。

## 固定版本

| 组件 | 提交/版本 |
| --- | --- |
| `unitree_mujoco` | `1a37b051a10be723405b7ed6dc839361af036d88` |
| `unitree_rl_lab` | `4960b84732b0c2ec593dccbfe963fda1bcd7b1e3` |
| `unitree_sdk2` | `6d03531e109135b18500c7c3e6f8408ba857134e` |
| ONNX Runtime | `1.22.0`（x86_64 使用上游副本，aarch64 由 `setup.sh` 下载并覆盖） |

