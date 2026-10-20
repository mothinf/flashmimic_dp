# flashmimic_dp

G1 29-DOF 的 MimicLite WBT 部署仓库，包含 ONNX 策略、运动数据和部署补丁。

支持 Ubuntu 20.04/22.04，`x86_64` 和 `aarch64`。克隆后，除实机启动外的命令均在仓库根目录执行。

## 1. 准备依赖

```bash
sudo apt update
sudo apt install -y build-essential cmake git curl file python3 python3-yaml \
  libyaml-cpp-dev libboost-program-options-dev libeigen3-dev libspdlog-dev libfmt-dev

git clone https://github.com/LeeLeno/flashmimic_dp.git
cd flashmimic_dp
bash scripts/setup.sh
```

[`setup.sh`](scripts/setup.sh) 拉取固定版本上游、应用补丁，并准备 ONNX Runtime 1.22.0。首次运行需访问 GitHub；ARM 库目录名仍保留 `linux-x64`。

已有部署只需清理旧舞蹈入口时，在停机后执行 `python3 scripts/prune_legacy_dances.py`，再重启控制器，无需重新编译。脚本也会由 `setup.sh` 自动执行：只移除两个上游示例舞蹈及其切换入口，保留现有模型路径、运动和增益；首次修改前备份为 `config.yaml.before-single-dance`。

## 2. 编译

首次安装 SDK/DDS；系统已有匹配版本时，可跳过下面前三条命令。

```bash
cmake -S unitree_sdk2 -B unitree_sdk2/build -DBUILD_EXAMPLES=OFF
sudo cmake --build unitree_sdk2/build --target install
sudo ldconfig

cmake -S unitree_rl_lab/deploy/robots/g1_29dof \
  -B unitree_rl_lab/deploy/robots/g1_29dof/build -DCMAKE_BUILD_TYPE=Release
cmake --build unitree_rl_lab/deploy/robots/g1_29dof/build --parallel 2
```

编译只生成 `g1_ctrl`，不会启动机器人。

## 3. 离线检查

检查模型推理和速度状态的首次发布，不连接机器人。C++ 推理检查只需 Python/PyYAML 读取配置，不需要 Python ONNX Runtime。

```bash
bash scripts/parity/run_numeric_check.sh
bash scripts/parity/run_rlbase_gate_test.sh
```

应分别看到 `NUMERIC PASS` 和 `GATE PASS`。当前模型输入输出为 `obs[1,397] → [1,29]`。

模型检查默认读取 `unitree_rl_lab/deploy/robots/g1_29dof/config/config.yaml` 中 `Mimic_WBT_Dance1` 的 `policy`、`deploy_config`。检查其他配置或状态可用 `--controller-config`、`--state`，单独覆盖模型或参数可用 `--onnx`、`--config`。同名参数优先于环境变量，详见 `--help`。

模型检查和 parity 会打印实际路径，并将记录保存在 `.deps/checks/`；`--out` 可指定输出目录，`--resolve-only` 只核对输入，不编译或推理。控制器 YAML 内的相对路径按控制器项目目录解析；命令行相对路径按当前目录解析。配置文件另存到其他目录时，可用 `--project-root` 指定控制器项目目录。

## 4. 实机测试

默认只启用以下 4 个状态：

| 状态 | 用途 |
| --- | --- |
| `Passive` | 启动状态，关节阻尼，不支撑体重 |
| `FixStand` | 用约 3 秒过渡到固定站姿 |
| `Velocity` | 平衡/行走，也是舞蹈结束后的返回状态 |
| `Mimic_WBT_Dance1` | 唯一舞蹈入口，使用当前配置的 WBT 模型和运动 |

正常流程为 `Passive → FixStand → Velocity → Mimic_WBT_Dance1 → Velocity`。上游示例 `Mimic_Dance_102`、`Mimic_Gangnam_Style` 已从启用列表、参数和切换入口移除；L2 长按后按 ↓ / ← 不再切入示例舞蹈。

做好吊挂/防坠保护，按机器人手册进入开发模式（L2 + R2），退出原厂运控后再启动。`eth0` 换为机器人通信网卡，不用 SSH 的 Wi-Fi 网卡。

```bash
cd unitree_rl_lab/deploy/robots/g1_29dof/build
./g1_ctrl --network eth0 --check-network  # 只检查网卡，不初始化 DDS
```

网卡检查通过后，正式启动控制器（会持续发布指令）：

```bash
./g1_ctrl --network eth0
```

看到 `Connected to robot` 和 `FSM: Start Passive` 后操作；若提示其他进程占用 `lowcmd`，退出排查。

| 操作 | 遥控器 |
| --- | --- |
| 进入固定站姿 | 按住 L2，点按方向键 ↑，等待约 3 秒 |
| 双脚触地后进入平衡/行走 | R1 + X |
| 从平衡切入 WBT 舞蹈 | **先按住 L2 超过 2 秒，再点按方向键 →** |
| 中止舞蹈，返回平衡 | R1 + X |
| 退回阻尼 Passive | L2 + B |

片段结束自动返回平衡。停机时先确保防坠支撑，L2 + B 退回 Passive，再 `Ctrl+C`；Passive 不支撑体重。

WBT 推理故障或姿态异常会退回 Passive；所有状态保留低层状态接收超时退回 Passive 的保护。

训练限制执行器力矩，不裁剪虚拟目标角；当前发布侧没有同等的总 PD 力矩限幅，实机前需核实。离线 PASS 不代表闭环安全。

## 5. 更换模型或运动

每次导出单独存放，例如 `assets/policy_1020/`，保留配套的 `policy.onnx` 和 `policy.onnx.data` 原名，避免外置权重引用失效。`.pt` 需先导出 ONNX。

在 `unitree_rl_lab/deploy/robots/g1_29dof/config/config.yaml` 中修改 `FSM.Mimic_WBT_Dance1.policy`：

```yaml
policy: ../../../../assets/policy_1020/policy.onnx
```

同配置下只换 checkpoint，无需重编译，停机切换后重启。**修改控制器配置后，模型检查和完整 parity 都会跟随新路径，无需改脚本。**若观测布局、关节顺序、缩放、延迟或增益变化，需同步[部署参数](assets/mimiclite_dr_140k_deploy_config.yaml)、该状态的 `kp/kd`，并确认 C++ 支持。

换运动：`python3 scripts/export_motion_bin.py 输入.npz 输出.bin`（需要 NumPy），再更新 `motion` 和播放时间。

<details>
<summary>可选：完整 Python/C++ parity</summary>

需要 NumPy、PyYAML、Python ONNX Runtime，以及与运动数据匹配的 G1 XML。在 Python 3.10 环境中运行：

```bash
python -m pip install numpy pyyaml onnxruntime==1.22.0
PYTHON=python bash scripts/parity/run_parity.sh --unilab ../UniLab --unilab-ref HEAD
```

`--unilab` 默认是仓库旁的 `../UniLab`，`--unilab-ref` 默认 `HEAD`，也可指定本地已有的提交、标签或分支。脚本读取该版本的 `src/unilab/assets/robots/g1/g1.xml`，不再要求特定远程分支。也可直接提供 XML，完全不依赖 UniLab Git 仓库：

```bash
PYTHON=python bash scripts/parity/run_parity.sh --mjcf /path/to/g1.xml
```

运动 BIN 默认读取当前状态的 `motion`，参考 NPZ 默认取其同名 `.npz` 文件；不同名时使用 `--motion-bin`、`--motion` 显式指定。XML 与运动的关节顺序/几何不匹配会报错，成功输出 `PARITY PASS`。

原有 `PYTHON`、`UNILAB` 用法仍可用；也支持 `UNILAB_REF`、`MJCF`、`POLICY`、`DEPLOY_CONFIG`、`MOTION_BIN`、`MOTION_NPZ`、`CONTROLLER_CONFIG`、`FSM_STATE` 环境变量，同名参数优先。提供 XML 时优先使用 XML，不读取 UniLab。

</details>
