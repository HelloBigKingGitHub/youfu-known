# youfu-known

> 个人知识库 + RAG 问答系统 · 全栈自托管 · 移动端可用

轻量级、零云依赖的个人知识库。基于 FastAPI + Chroma + React, 上传文档即问即答, 基于你的内容做检索增强生成 (RAG)。所有数据存本地, 仅在调用 LLM/Embedding 时走外网。

## ✨ 核心特性

- 📚 **多知识库**: 建多个 KB, 分别管理不同主题 (工作 / 学习 / 笔记)
- 📄 **多格式上传**: PDF / Word (.docx / .doc) / Markdown / TXT / HTML
- 🤖 **RAG 问答**: 基于你上传的内容, 带可点击引用片段
- 🔒 **数据本地**: Chroma + SQLite 本地存储, **不上传任何文件到云**
- 🔑 **多 Key 轮询**: 支持配置多个 LLM API Key, 失败自动切换
- 📱 **响应式 UI**: 桌面 / 平板 / 手机三档适配 (Chakra UI)
- 🌐 **HTTPS 外网**: 一键部署 Cloudflare Tunnel, 公网访问

## 🛠 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI 0.139 + Pydantic 2.13 + Uvicorn |
| 向量库 | Chroma 1.0 (PersistentClient, 本地文件) |
| LLM | MiniMax (兼容 OpenAI 协议) |
| Embedding | 阿里云百炼 DashScope text-embedding-v3 (1024 维) |
| 前端 | Vite 5 + React 18 + Chakra UI 2.10 |
| 部署 | systemd + Cloudflare Tunnel |

## 🚀 快速开始

### 1. 安装依赖

```bash
# Python 后端
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 前端
cd web && npm install
```

### 2. 配置凭据

```bash
cp .env.example .env
# 编辑 .env 填入你的 MiniMax + DashScope API Key
```

### 3. 启动

```bash
# 后端 (默认 8000)
uvicorn main:app --host 0.0.0.0 --port 8000

# 前端 (另一个终端, 默认 5173)
cd web && npm run dev

# 浏览器打开
open http://127.0.0.1:5173
```

### 4. 部署脚本

```bash
# 一键安装到 systemd
bash scripts/install.sh

# 启动 / 停止 / 重启 / 状态
bash scripts/start.sh
bash scripts/stop.sh
bash scripts/restart.sh
bash scripts/status.sh

# 部署到树莓派
bash scripts/deploy_pi.sh
```

## 🌐 外网访问

完整流程见 [docs/expose-to-internet.md](docs/expose-to-internet.md) — 用 Cloudflare Tunnel 把 Pi 上的服务暴露到公网, 自动 HTTPS。

**最终效果**: `https://kb.sxy.homes`

## 📐 项目结构

```
youfu-known/
├── main.py                          # FastAPI 入口
├── config.yaml                      # 全局配置
├── requirements.txt
├── app/
│   ├── api/                         # REST 路由层
│   ├── kb/                          # 知识库 (CRUD + ingest)
│   ├── rag/                         # 文档加载 + 切块 + 嵌入 + 检索
│   ├── llm/                         # LLM + Embedding 客户端
│   ├── jobs/                        # 后台 ingest job
│   └── config.py
├── web/                             # React SPA
│   └── src/
│       ├── App.tsx                  # 根布局 + Drawer state
│       └── components/              # 9 个响应式组件
├── scripts/                         # 运维脚本 (12 个)
│   ├── start.sh / stop.sh / restart.sh
│   ├── deploy_pi.sh                 # 推 Pi
│   └── cloudflare/                  # Tunnel 装卸
├── tests/                           # pytest (71 个)
├── docs/                            # 运维文档
└── openspec/                        # 设计规格
```

## 📊 测试

```bash
source .venv/bin/activate
pytest tests/ -v
```

当前 **71 个测试全过**:
- 后端核心 64 个 (loader / chunker / vectorstore / retriever / model / service)
- API 集成 7 个 (上传 / ingest / 问答 / 异常路径)

## 📜 License

MIT License, 见 [LICENSE](LICENSE)。

## 🤝 贡献

仓库地址: https://github.com/HelloBigKingGitHub/youfu-known

PR / Issue 欢迎。