# 任务: 聊天历史持久化 + 发布前面 Kimi 改的 UI

> **任务编号**: chat-history-persistence  
> **派发对象**: Kimi (前端 Coding Agent)  
> **状态**: ✅ 已完成 (commit `7e016ad`)

## 背景

后端 `POST /api/kbs/{id}/chat` 已经在保存问答 (`chat_turns` 表)。**但前端 ChatPanel 完全没用这些数据**:
- mount 时不拉历史
- 刷新页面 → 历史全丢
- 切 KB → history 重新从空开始

而且**前面的 UI 任务 (Kimi 已 commit `e85c130` 还没推到 Pi**):
- 共享 KB 切换 pill
- 侧栏 分组
- admin 用户管理页
- RegisterPage 路由已加但未发布

本 spec 包含 2 个改动 + 发布。

## 核心改动

### 1. ChatPanel 持久化 (核心)

**当前 `web/src/components/ChatPanel.tsx`**:
- `useState<ChatTurn[]>([])` 内存保存
- 发送时直接 setHistory
- **不拉后端数据**

**新逻辑**:
```tsx
export function ChatPanel({ kbId }: Props) {
  const [history, setHistory] = useState<ChatTurn[]>([])
  const [loading, setLoading] = useState(true)  // 拉历史时显示 spinner
  const [sending, setSending] = useState(false)

  // mount 时拉历史
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.listChats(kbId)
      .then(chats => {
        if (!cancelled) {
          // 倒序: 后端 DESC, 前端正序展示
          setHistory(chats.slice().reverse())
        }
      })
      .catch(e => {
        toast({ title: '加载历史失败', description: e.message, status: 'error' })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [kbId])  // 切 KB 时重新拉

  // 发送
  const handleSend = async () => {
    const q = question.trim()
    if (!q || sending) return
    setSending(true)
    const tempId = `temp-${Date.now()}`  // 乐观更新
    setHistory(h => [...h, {
      id: tempId,
      kb_id: kbId,
      user_id: 'me',  // 占位
      question: q,
      answer: '',
      citations: [],
      status: 'ready',
      created_at: new Date().toISOString(),
      latency_ms: 0,
    }])
    setQuestion('')
    try {
      const resp = await api.chat(kbId, q)
      // 用后端返回的真实 turn 替换临时
      // 或者重新拉历史 (保险)
      const chats = await api.listChats(kbId)
      setHistory(chats.slice().reverse())
    } catch (e) {
      // 标错
      setHistory(h => h.map(t => t.id === tempId ? { ...t, error: String(e), status: 'failed' } : t))
    } finally {
      setSending(false)
    }
  }

  // 清空 → DELETE /api/kbs/{id}/chats (清当前 user 的, 不是清 KB 内所有)
  const handleClear = async () => {
    if (!window.confirm('清空当前 KB 的所有问答?')) return
    await api.clearChats(kbId)
    setHistory([])
  }

  // 删除单条
  const handleDelete = async (turnId: string) => {
    if (!window.confirm('删除这条问答?')) return
    await api.deleteChat(kbId, turnId)
    setHistory(h => h.filter(t => t.id !== turnId))
  }
}
```

**api.ts 加 3 个方法**:
```tsx
listChats: async (kbId: string) => {
  const r = await request<ChatTurn[]>(`/api/kbs/${kbId}/chats?limit=50`);
  return r;
},

deleteChat: async (kbId: string, turnId: string) => {
  return request<void>(`/api/kbs/${kbId}/chats/${turnId}`, { method: 'DELETE' });
},

clearChats: async (kbId: string) => {
  return request<void>(`/api/kbs/${kbId}/chats`, { method: 'DELETE' });
},
```

**types.ts 加 ChatTurn**:
```tsx
export interface ChatTurn {
  id: string;
  kb_id: string;
  user_id: string;
  question: string;
  answer: string;
  error: string;
  citations: Citation[];
  status: 'ready' | 'failed';
  created_at: string;  // ISO
  latency_ms: number;
}
```

### 2. UI 细节

- 加载时: spinner + "加载历史..."
- 空 + 加载完: 显示空状态
- 历史每条加 hover 出现 "删除" 按钮 (左上角小 ×)
- 清空按钮: 改文字 "清空我的问答" (更明确)
- 移动端: 加载状态放 header

### 3. ChatTab 切 KB 时自动 re-fetch

`KBChatTab` 已经 mount 不同的 ChatPanel, ChatPanel 的 useEffect `[kbId]` 会重新拉。

### 4. 发布任务

**Spec 完成, 也需要把 Kimi 之前 `e85c130` 改的 7 个文件推到 Pi**:
- 共享 KB pill
- 侧栏分组
- admin 用户管理页
- /register 路由 (已加但 Pi dist 没更新)

**所有改动一次 commit + push + 推 Pi**。

## 执行流程

1. 读本 spec
2. 看现状:
   - web/src/components/ChatPanel.tsx (改)
   - web/src/api.ts (加 listChats/deleteChat/clearChats)
   - web/src/types.ts (加 ChatTurn)
3. 改 ChatPanel.tsx (持久化逻辑)
4. 改 api.ts (3 个方法)
5. 改 types.ts (ChatTurn interface)
6. cd web && npm run build (0 错误)
7. **3 档截图验证** (用 chromium headless):
   - 桌面 (1280x800) - KB 详情: 看到 pill + 切共享 + admin 菜单
   - 桌面 - admin /admin/users: 看到用户列表
   - 移动 (390x844) - 侧栏分组 + KB 共享 pill
   - **重要**: 聊天刷新后保留 (手动截)
8. 截图保存到 /tmp/verify_*.png
9. git add -A
   git commit -m "feat(ui): persist chat history across reloads + integrate user-isolation data"
10. **推送**:
    ```bash
    git push origin main
    # 主协调 (Hermes) 会做 Pi 发布
    ```

## 关键技术约束

- 拉历史用 `useEffect [kbId]` 依赖, 切 KB 自动 re-fetch
- 发送时乐观更新 (临时 id), 后端返回后用真实 id 替换
- 拉历史失败显示 toast, 不阻塞 UI
- 历史每条 cite 仍可点开 (引用 panel)
- 加载 spinner 跟现有 spinner 风格统一
- 现有 useState 逻辑保留, 加 effect
- **不引新依赖**

## 不要做

- ❌ 不改后端
- ❌ 不改 theme.ts
- ❌ 不写 admin / 共享相关 (Kimi 之前 commit `e85c130` 已经做了, 我会一起发布)
- ❌ 不重启服务 / 部署 (主协调做)

## 输出格式

报告 markdown:
1. 改的文件清单 + 行数
2. 关键技术决策
3. build 输出
4. 截图清单 (路径 + 一句话描述)
5. spec 偏离

## 主协调验收

主协调 (Hermes) 会:
1. 跑 build (0 错误)
2. 看你的截图
3. 推 Pi (rsync + dist + 重启)
4. 截外网验证 (kb.sxy.homes)
5. 通知用户

START NOW.