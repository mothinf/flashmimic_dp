# flashmimic_dp

G1 29-DOF 的 MimicLite WBT 部署仓库，包含 ONNX 策略、运动数据和部署补丁。

支持 Ubuntu 20.04/22.04，`x86_64` 和 `aarch64`。克隆后，除实机启动外的命令均在仓库根目录执行。

## 1. 准备依赖

```bash
sudo apt update
sudo apt install -y build-essential cmake git curl file \
  libyaml-cpp-dev libboost-program-options-dev libeigen3-dev libspdlog-dev libfmt-dev

git clone https://github.com/LeeLeno/flashmimic_dp.git
cd flashmimic_dp
bash scripts/setup.sh
```

[`setup.sh`](scripts/setup.sh) 拉取固定版本上游、应用补丁，并准备 ONNX Runtime 1.22.0。首次运行需访问 GitHub；ARM 库目录名仍保留 `linux-x64`。

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

检查模型推理和速度状态的首次发布，无需 Python 环境，不连接机器人。

```bash
ORT="$PWD/unitree_rl_lab/deploy/thirdparty/onnxruntime-linux-x64-1.22.0"
g++ -std=c++17 -O2 \
  -I unitree_rl_lab/deploy/include -I "$ORT/include" \
  scripts/parity/mimiclite_numeric_check.cpp \
  "$ORT/lib/libonnxruntime.so.1.22.0" -lpthread -o /tmp/mimiclite_numeric_check
LD_LIBRARY_PATH="$ORT/lib" /tmp/mimiclite_numeric_check assets/policy.onnx
bash scripts/parity/run_rlbase_gate_test.sh
```

应分别看到 `NUMERIC PASS` 和 `GATE PASS`。当前模型输入输出为 `obs[1,397] → [1,29]`。

## 4. 实机测试

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

训练限制执行器力矩，不裁剪虚拟目标角；当前发布侧没有同等的总 PD 力矩限幅，实机前需核实。离线 PASS 不代表闭环安全。

## 5. 更换模型或运动

每次导出单独存放，例如 `assets/policy_1020/`，保留配套的 `policy.onnx` 和 `policy.onnx.data` 原名，避免外置权重引用失效。`.pt` 需先导出 ONNX。

在 `unitree_rl_lab/deploy/robots/g1_29dof/config/config.yaml` 中修改 `FSM.Mimic_WBT_Dance1.policy`：

```yaml
policy: ../../../../assets/policy_1020/policy.onnx
```

同配置下只换 checkpoint，无需重编译，停机切换后重启。若观测布局、关节顺序、缩放、延迟或增益变化，需同步[部署参数](assets/mimiclite_dr_140k_deploy_config.yaml)、该状态的 `kp/kd`，并确认 C++ 支持。数值检查也要使用新模型路径。

换运动：`python3 scripts/export_motion_bin.py 输入.npz 输出.bin`（需要 NumPy），再更新 `motion` 和播放时间。

<details>
<summary>可选：完整 Python/C++ parity</summary>

需额外提供包含 `origin/feat/mimiclite-obs` 的 UniLab；只有主分支时可跳过此项。在 Python 3.10 环境中运行：

```bash
python -m pip install numpy pyyaml onnxruntime==1.22.0
PYTHON=python UNILAB=/path/to/UniLab bash scripts/parity/run_parity.sh
```

成功输出 `PARITY PASS`。脚本固定读取原模型和运动，**不会跟随控制器配置切换**；换版本时需同步脚本中的路径。

</details>
