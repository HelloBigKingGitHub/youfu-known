# GitHub 仓库配置说明

## 仓库设置 (在 GitHub 网页操作)

1. 打开 https://github.com/HelloBigKingGitHub/youfu-known/settings

### General
- **Description**: `个人知识库 + RAG 问答系统 · 全栈自托管 · 响应式 SPA`
- **Website**: `https://kb.sxy.homes`
- **Topics**: 添加标签:
  - `rag` `fastapi` `chromadb` `react` `vite` `chakra-ui`
  - `knowledge-base` `personal-rag` `self-hosted` `cloudflare-tunnel`

### Features (默认即可)
- ✅ Issues
- ❌ Wiki (用 docs/ 替代)
- ❌ Projects (不用 GitHub Projects)
- ❌ Discussions (用 Issues)

### Pull Requests
- ✅ Allow squash merging (默认)

### Branch Protection (重要)
在 `Branches → Branch protection rules → Add rule`:
- Branch name pattern: `main`
- ✅ Require a pull request before merging
- ✅ Require status checks to pass (如果配了 GitHub Actions)

## GitHub Actions (可选)

可以加 `.github/workflows/ci.yml`:

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m venv .venv && .venv/bin/pip install -r requirements.txt
      - run: .venv/bin/pytest tests/ -v
```