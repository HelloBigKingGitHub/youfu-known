# youfu-known · 部署与运维脚本

一套适用于服务器 / NAS / 个人主机的安装 / 启动 / 停止脚本,
同时兼容 `systemd`(生产)和 `nohup`(开发)两种部署形态。

## 文件清单

```
scripts/
├── install.sh              # 一键安装
├── start.sh                # 启动服务
├── stop.sh                 # 停止服务
├── restart.sh              # 重启 (= stop + start)
├── status.sh               # 查看状态
├── update.sh               # 升级 (git pull + 重装依赖 + 重启)
├── uninstall.sh            # 卸载
├── youfu-known.service     # systemd unit 模板 (由 install.sh 注册)
└── lib/
    └── common.sh           # 颜色/日志/锁/路径/进程管理 公共函数
```

## 快速上手

### 开发场景 (本地, 无 root)

```bash
# 项目根目录运行
bash scripts/start.sh        # 自动识别 ./main.py, 用 nohup 后台跑
bash scripts/status.sh       # 看状态 (含智能端口解析)
bash scripts/stop.sh
bash scripts/restart.sh
```

### 生产场景 (Linux 服务器)

```bash
# 一键安装到 /opt/youfu-known
sudo bash scripts/install.sh

# 编辑 API key
sudo vim /opt/youfu-known/.env

# 服务管理 (systemd)
sudo systemctl start youfu-known
sudo systemctl status youfu-known
sudo systemctl stop youfu-known

# 或继续用统一脚本 (推荐, 脚本内部自动检测 init)
sudo bash /opt/youfu-known/scripts/start.sh
sudo bash /opt/youfu-known/scripts/stop.sh
sudo bash /opt/youfu-known/scripts/restart.sh
sudo bash /opt/youfu-known/scripts/status.sh
```

### 自定义路径 / 端口

```bash
# 安装到 $HOME/youfu-known (无需 root)
INSTALL_DIR=$HOME/youfu-known bash scripts/install.sh

# 改端口
YOUFU_PORT=9000 bash scripts/install.sh

# 改运行用户
YOUFU_USER=myuser bash scripts/install.sh

# 改 git 源 / 分支
YOUFU_REPO=https://git.mycorp.com/youfu/youfu-known.git \
YOUFU_BRANCH=develop \
bash scripts/install.sh
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `INSTALL_DIR` | `/opt/youfu-known` | 安装路径 |
| `YOUFU_PORT` | `8000` | 服务端口 |
| `YOUFU_HOST` | `0.0.0.0` | 绑定地址 |
| `YOUFU_USER` | `youfu` | 运行用户 (root 时自动创建) |
| `YOUFU_REPO` | `https://github.com/youfu/youfu-known.git` | Git 源 |
| `YOUFU_BRANCH` | `main` | Git 分支 |
| `YOUFU_DATA_DIR` | `${INSTALL_DIR}/storage` | 数据目录 (上传/chroma/sqlite) |
| `YOUFU_LOG_DIR` | `${INSTALL_DIR}/logs` | 日志目录 |

## 端口 / 进程管理

- **systemd 模式**: `install.sh` 自动注册 `/etc/systemd/system/youfu-known.service`,
  启动时 `systemctl start youfu-known`, 开机自启用 `systemctl enable`
- **nohup 模式**: 无 systemd 时 (macOS / 容器 / 开发) fallback, 写 PID 文件到 `${YOUFU_LOG_DIR}/youfu-known.pid`,
  日志写到 `${YOUFU_LOG_DIR}/access.log` 和 `error.log`
- **混用检测**: 脚本启动时先检查 systemd unit 是否注册过; 已注册则用 systemd, 否则 nohup

## 智能特性

- **路径自动感知**: 若 `INSTALL_DIR` 是默认 `/opt/youfu-known` 但当前目录是项目目录
  (有 `main.py` + `app/` + `web/`), 自动切换到当前目录。开发场景无需手动指定
- **端口智能解析**: `status.sh` 从 PID 文件解析出真实监听端口, 健康检查无须手动指定 `YOUFU_PORT`
- **PID 验证**: 启动后验证 PID 文件中的进程真的存活, 必要时回退到 `pgrep` 找真实 uvicorn PID
- **端口冲突检测**: 启动前检查目标端口, 占用时打印占用进程, 不盲目覆盖

## 已知限制

- **macOS / WSL**: 无 systemd → 自动 fallback nohup, 功能完整
- **容器 (Docker)**: 建议直接用 uvicorn 入口命令; 脚本主要是给 host 部署用
- **生产级 multi-worker**: systemd unit 默认 `--workers 1`, 高并发场景需要手动改 unit

## 故障排查

| 现象 | 排查 |
|------|------|
| 启动报 "未检测到安装目录" | 当前目录不是 youfu-known 项目, 或 `INSTALL_DIR` 指向了不存在的路径 |
| 端口被占用 | `ss -tlnp \| grep $PORT` 看谁占着; 或用 `YOUFU_PORT=$OTHER` 改端口 |
| systemd 启动失败 | `journalctl -u youfu-known -n 50` |
| nohup 启动失败 | `tail -f ${YOUFU_LOG_DIR}/error.log` |
| 健康检查 HTTP 不可达 | `curl http://127.0.0.1:$PORT/api/health` 手动验证; 检查防火墙 |

## 卸载

```bash
sudo bash /opt/youfu-known/scripts/uninstall.sh
# 交互式询问: 是否保留数据 / .env / 删除代码目录 / 卸载 systemd unit
```