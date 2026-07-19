# youfu-known · 部署 / 运维 / 故障排查

个人知识库 + RAG 问答系统的完整操作手册。

## 目录

1. [快速启动](#快速启动)
2. [API Key 配置](#api-key-配置)
3. [Pi 部署流程](#pi-部署流程)
4. [管理命令](#管理命令)
5. [故障排查](#故障排查)

---

## 快速启动

### 本地开发

```bash
cd youfu-known
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env 填入 MINIMAX_API_KEY / DASHSCOPE_API_KEY

# 后端
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 前端 (另一终端)
cd web && npm install && npm run dev
# 访问 http://localhost:5173
```

### 一键脚本 (推荐)

```bash
bash scripts/install.sh    # 装依赖
bash scripts/start.sh      # 启动
bash scripts/status.sh     # 看状态
bash scripts/stop.sh       # 停止
bash scripts/restart.sh    # 重启
bash scripts/update.sh     # 升级
```

---

## API Key 配置

`.env` 文件格式:

```bash
# MiniMax (对话模型)
MINIMAX_API_KEY=sk-cp-...
MINIMAX_API_KEY_2=sk-cp-...    # 备用 1 (可选)
MINIMAX_API_KEY_3=sk-cp-...    # 备用 2 (可选)
# 最多支持 _2 ~ _10

# 阿里云百炼 (Embedding)
DASHSCOPE_API_KEY=sk-e21...
```

### 多 Key 轮询机制

代码读 `MINIMAX_API_KEY` (主) + `MINIMAX_API_KEY_2` ... `_10` (备用),按顺序轮询:

- **首次请求**: 用主 key
- **失败 (尤其 429 / 401 / 5xx)**: 标记当前 key 冷却 60s, 切到下一个 key 重试
- **全部失败**: 抛 RuntimeError, API 返回 500
- **冷却过期 (60s)**: key 重新可用

测试覆盖 (`/tmp/test_multi_key.py`):
- ✅ pick 选下一个可用 key
- ✅ mark_failed 后冷却
- ✅ cooldown 过期自动恢复
- ✅ achat 失败自动 failover 到下一个 key
- ✅ 全部失败抛 RuntimeError

### "多个 Key 没生效" 排查

**最常见**: 多个 Key 都是**同一个 MiniMax 账户**下签发的,共享同一份 Token Plan 配额。即使轮询,429 仍然会出现 — 因为所有 key 都指向同一账户。

**解决方法**:
1. 在 MiniMax 控制台 (platform.MiniMax.chat) 检查 Token Plan 剩余额度
2. 充值 / 升级套餐 / 购买额外积分
3. 用**多个不同账户**的 key (轮询才能真正起到分流作用)

---

## Pi 部署流程

完整流程: SSH 免密 → 装系统依赖 → 装 Python/Node 依赖 → 推代码 → systemd 注册 → 启动。

### 一次性设置 SSH 免密

```bash
PI_HOST=192.168.x.x bash scripts/setup_pi_ssh.sh
# 按提示输入 Pi 密码 (只输一次, 之后免密)
```

### 一键部署 (主入口)

```bash
PI_HOST=192.168.x.x bash scripts/install_pi_deps.sh   # 装系统包 + Node
PI_HOST=192.168.x.x bash scripts/deploy_pi.sh        # rsync 代码 + 装 + 启动
```

或者一行 (后台跑 + 看日志):
```bash
PI_HOST=192.168.x.x nohup bash scripts/deploy_pi.sh > /tmp/deploy.log 2>&1 &
tail -f /tmp/deploy.log
```

### 手动步骤 (troubleshooting)

```bash
# 1. 测试 SSH
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x

# 2. 装系统依赖 (Pi ARM64 + Debian 13)
#    - python3-venv build-essential libopenblas-dev libxml2-dev ...
#    - NodeSource Node 20.x
bash scripts/install_pi_deps.sh

# 3. rsync 代码
rsync -az --exclude='.venv' --exclude='node_modules' --exclude='storage' \
    -e "ssh -i ~/.ssh/id_rsa_pi" \
    /path/to/youfu-known/ youfu@192.168.x.x:/home/youfu/youfu-known/

# 4. 推 .env (含真实 key)
scp -i ~/.ssh/id_rsa_pi .env youfu@192.168.x.x:/home/youfu/youfu-known/.env

# 5. Pi 上 git init (因为 install.sh 检测 git 仓库)
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x \
    "cd /home/youfu/youfu-known && git init -q && git add -A && \
     git -c user.email=pi@local -c user.name=pi commit -q -m initial"

# 6. Pi 上跑 install.sh
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x \
    "cd /home/youfu/youfu-known && INSTALL_DIR=/home/youfu/youfu-known \
     YOUFU_PORT=8000 YOUFU_USER=youfu bash scripts/install.sh"

# 7. 修 systemd unit (sed 替换占位符不工作时的备用方案)
scp -i ~/.ssh/id_rsa_pi /tmp/youfu-known.service.fixed \
    youfu@192.168.x.x:/tmp/youfu-known.service

# 8. 装 systemd unit + 启服务 + 开机自启
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x \
    "sudo -S install -m 644 /tmp/youfu-known.service /etc/systemd/system/youfu-known.service && \
     sudo -S systemctl daemon-reload && \
     sudo -S systemctl enable youfu-known && \
     sudo -S systemctl start youfu-known"
```

### 验证

```bash
# API
curl http://192.168.x.x:8000/api/health
# → {"code":0,"data":{"status":"ok","version":"0.1.0"}}

# SPA (主页面 HTML)
curl http://192.168.x.x:8000/
# → <!doctype html><html lang="zh-CN">...

# 完整端到端
curl -X POST http://192.168.x.x:8000/api/kbs \
    -H "Content-Type: application/json" \
    -d '{"name":"测试"}'
```

---

## 管理命令

### 本机 (本机开发)

```bash
bash scripts/start.sh      # 启动 (systemd 优先, fallback nohup)
bash scripts/stop.sh       # 停止
bash scripts/restart.sh    # 重启
bash scripts/status.sh     # 状态 (智能端口解析)
bash scripts/update.sh     # 升级 (git pull + 重装 + 重启)
bash scripts/uninstall.sh  # 卸载
```

### Pi (远端, 走免密 SSH)

```bash
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x

# 服务管理
sudo systemctl status youfu-known
sudo systemctl restart youfu-known
sudo systemctl stop youfu-known
sudo systemctl start youfu-known
sudo systemctl enable youfu-known   # 开机自启
sudo systemctl disable youfu-known  # 禁用

# 日志
sudo tail -f /var/log/youfu-known/error.log
sudo tail -f /var/log/youfu-known/access.log
sudo journalctl -u youfu-known -n 50 -f

# 数据
ls -la /home/youfu/youfu-known/storage/
du -sh /home/youfu/youfu-known/storage/*

# 重启时清空所有数据
sudo systemctl stop youfu-known
sudo rm -rf /home/youfu/youfu-known/storage/
sudo systemctl start youfu-known
```

---

## 故障排查

### 1. `pip install` 报 "Network is unreachable"

**原因**: Pi 走 IPv4 only, 但 PyPI 解析到 IPv6 地址 (`2a04:4e42:600::223`)。

**解决** (任选一):
```bash
# 方案 A: 配清华源 (推荐, IPv4 通)
mkdir -p ~/.pip
cat > ~/.pip/pip.conf <<'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
[install]
prefer-binary = true
EOF

# 方案 B: 用阿里源
# index-url = https://mirrors.aliyun.com/pypi/simple/

# 方案 C: 让 Pi 启用 IPv6
# /etc/network/interfaces 加 inet6 ...
```

### 2. `sudo: a terminal is required to read the password`

**原因**: SSH 非交互 session 下 sudo 默认要求 tty。

**解决**:
```bash
# 方案 A: 用 expect 喂密码
spawn ssh user@host "sudo -S bash -c '...'"
expect {
    "assword" { send "$PASS\r"; exp_continue }
    eof
}

# 方案 B: 配 NOPASSWD sudo (在 Pi 上)
sudo visudo
# 添加: youfu ALL=(ALL) NOPASSWD: ALL
```

### 3. systemd unit 配置错误 `bad unit file setting`

**原因**: install.sh 的 sed 替换占位符失败, `@INSTALL_DIR@` 字面留在 unit 里。

**解决**: 用预先生成的 unit:
```bash
# 推送已修好的 unit
scp -i ~/.ssh/id_rsa_pi scripts/youfu-known.service youfu@PI:/tmp/
ssh youfu@PI "sudo -S install -m 644 /tmp/youfu-known.service \
    /etc/systemd/system/youfu-known.service && \
    sudo -S systemctl daemon-reload && \
    sudo -S systemctl restart youfu-known"
```

### 4. `unable to open database file` (sqlite)

**原因**: systemd 用了 `ProtectSystem=full` + `ProtectHome=read-only`, `storage/` 被 root 创建, youfu 用户写不了。

**解决**:
```bash
sudo chown -R youfu:youfu /home/youfu/youfu-known/storage
```

### 5. `MiniMax chat request failed: 429 rate_limit_error`

**原因**: MiniMax 账户 Token Plan 用尽。

**解决**:
1. 控制台充值 / 升级套餐
2. 用多账户的 key (`MINIMAX_API_KEY`, `_2`, `_3` ...)

### 6. `curl GET /` 返回 JSON 而非 SPA HTML

**原因**: FastAPI 没挂载 `web/dist/` 静态服务。

**解决**: 已在 `main.py` 加 `_register_static()`, 但**确保 `web/dist/index.html` 存在**:
```bash
cd web && npm run build   # 生成 dist/
sudo systemctl restart youfu-known
```

### 7. Pi 上 Node 没装

**原因**: Pi 官方系统默认无 Node。

**解决**: NodeSource 一键装 (Node 20.x):
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -S bash
sudo -S apt-get install -y nodejs
```

### 8. SSH 认证失败 / `Permission denied (publickey,password)`

**排查步骤**:
```bash
# 1. 看 SSH 用的是哪个 key
ssh -vvv user@host "echo OK" 2>&1 | grep "Offering"

# 2. Pi 上看 authorized_keys
ssh user@host "cat ~/.ssh/authorized_keys"

# 3. 看权限
ssh user@host "ls -la ~/.ssh/"
# authorized_keys 必须是 600, .ssh 必须是 700
```

---

## 环境变量速查

| 变量 | 默认 | 说明 |
|---|---|---|
| `INSTALL_DIR` | `/opt/youfu-known` | 安装路径 |
| `YOUFU_PORT` | `8000` | 服务端口 |
| `YOUFU_USER` | `youfu` | 运行用户 |
| `YOUFU_REPO` | `https://github.com/youfu/youfu-known.git` | Git 源 |
| `YOUFU_BRANCH` | `main` | Git 分支 |
| `YOUFU_DATA_DIR` | `${INSTALL_DIR}/storage` | 数据目录 |
| `YOUFU_LOG_DIR` | `${INSTALL_DIR}/logs` | 日志目录 |
| `PI_HOST` | (无) | 树莓派 IP |
| `PI_PORT` | `22` | SSH 端口 |
| `PI_USER` | `youfu` | SSH 用户 |
| `PI_SSH_KEY` | `~/.ssh/id_rsa_pi` | SSH key 路径 |
| `PI_SUDO_PASS` | (无) | Pi sudo 密码 (留空则需 NOPASSWD) |
| `MINIMAX_API_KEY` | (无) | MiniMax 主 key |
| `MINIMAX_API_KEY_2..10` | (无) | MiniMax 备用 key (轮询) |
| `DASHSCOPE_API_KEY` | (无) | 阿里云 DashScope key |

---

## 文件结构

```
youfu-known/
├── main.py                     # FastAPI 入口 + SPA fallback
├── config.yaml                 # 服务配置
├── requirements.txt            # Python 依赖
├── .env / .env.example         # 凭据
├── app/                        # 后端核心
│   ├── config.py               # Settings (含多 key 加载)
│   ├── llm/
│   │   ├── minimax_client.py   # MiniMax 聊天 (含多 key 轮询 + cooldown)
│   │   └── embedding_client.py # DashScope embedding
│   ├── rag/                    # 检索 + 切块 + 解析
│   ├── kb/                     # 知识库 CRUD
│   └── api/                    # FastAPI 路由
├── web/                        # 前端 (Vite + React + Chakra)
│   └── dist/                   # 构建产物 (Pi 上 mount)
├── storage/                    # 数据 (上传/chroma/sqlite)
├── scripts/                    # 运维脚本
│   ├── install.sh              # 本机一键装
│   ├── start.sh / stop.sh / restart.sh / status.sh
│   ├── update.sh / uninstall.sh
│   ├── deploy_pi.sh            # 树莓派一键部署
│   ├── install_pi_deps.sh      # Pi 系统依赖
│   ├── setup_pi_ssh.sh         # Pi SSH 免密设置
│   ├── youfu-known.service     # systemd unit 模板
│   ├── README.md               # 详细脚本文档
│   └── lib/common.sh           # 公共函数
├── tests/                      # pytest 测试 (71+ 个)
├── openspec/spec.md            # 系统规格
└── docs/deploy.md              # 本文档
```

---

## 已知限制

- **Pi 网络**: 需 IPv4 出站, PyPI 走清华源
- **流式 chat**: 后端暂返 501, 前端禁用 + 提示"开发中"
- **多用户**: 单租户, 无认证
- **HTTPS**: 未配, 仅 HTTP 内网访问
- **Pi systemd unit 替换占位符**: 用预先生成的 fixed 文件 (install.sh 的 sed 在某些 Pi 系统上失败)
- **storage 目录权限**: install.sh 默认 root 创建, youfu 用户需手动 chown

---

## 紧急故障

**服务挂了**:
```bash
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x "sudo journalctl -u youfu-known -n 50 --no-pager"
```

**完全重启 (清状态)**:
```bash
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x \
    "sudo systemctl stop youfu-known && \
     sudo rm -rf /home/youfu/youfu-known/storage && \
     sudo systemctl start youfu-known"
```

**完全卸载**:
```bash
ssh -i ~/.ssh/id_rsa_pi youfu@192.168.x.x "bash scripts/uninstall.sh"
# 按提示确认是否保留数据
```