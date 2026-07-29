# 前端增强: 共享开关 + 用户管理 UI

> **任务编号**: ui-shared-users  
> **派发对象**: Kimi (前端 Coding Agent)  
> **状态**: ✅ 已完成 (commit `e85c130`)

## 背景

后端数据隔离已上线 (`8906ab0`):
- KB 字段 `is_shared` (0/1) 控制可见性
- admin 有审计端点 `GET /api/admin/kbs/{id}/chats` 和 `GET /api/admin/users/{id}/chats`
- 老的 admin 端点 `GET /api/admin/users` / PATCH / DELETE 都在

但前端**没体现**这些:
- KB 详情页看不到当前 KB 是不是 shared
- 没地方切换 shared
- admin 没用户管理界面 (批准/拒绝 member / 改 role)
- 登录后侧栏 KB 列表没显示 "我的" vs "共享" 区分

本 spec 设计前端。

## 核心改动

### 1. KB 详情页: 共享开关

**位置**: `web/src/components/KBMainArea.tsx` (KB 标题区)

**显示**:
- 现有标题 + 描述 + 文档/chunks 计数
- **新增**: 共享/私有状态 pill + 切换按钮 (仅 owner/admin)

```
┌─────────────────────────────────────────┐
│  宝子的护理考试              [管理菜单▾]│
│  帮助小宝子进行护理考试学习           │
│                                         │
│  [2 文档] [7115 chunks] [🔒 私有] [✓共享]│
│       └─ 仅 owner/admin 看            │
└─────────────────────────────────────────┘
```

**交互**:
- pill 显示当前状态 (锁/共享图标 + 文字)
- 点 pill 或旁边的"切换"按钮 → 调 `PATCH /api/kbs/{id} {"is_shared": !current}`
- loading 时禁用, 完成后 toast
- 非 owner/admin: pill 只读, 不显示切换按钮

**移动端**: 同样的 pill, 文字短一些 ("私有" / "共享")

### 2. 侧栏 KB 列表: 分组显示

**位置**: `web/src/components/KnowledgeBaseSidebar.tsx`

**当前**: 一个 flat 列表 "知识库 (N)"

**新结构**:
```
知识库 (3)
├─ 我的 (2)
│  ├─ 📁 我的 KB 1        [×]
│  └─ 📁 我的 KB 2        [×]
└─ 共享给我 (1)
   └─ 👥 团队 KB         (不可删)
```

**逻辑**:
- 列表调用 `GET /api/kbs` 已经返回了 (KB 列表会自然按 is_shared 过滤)
- 前端再 group: `owner_id === currentUser.id` → "我的", `is_shared && owner_id !== currentUser.id` → "共享给我"
- "共享给我" 组的 KB **不显示删除按钮** (你不是 owner)

**新创建 KB 默认** `is_shared: false` (私有)。

### 3. Admin: 用户管理页 (`/admin/users`)

**新路由**: `/admin/users`

**新组件**: `web/src/components/AdminUsersPage.tsx`

**UI**:
```
┌───────────────────────────────────────────────┐
│  用户管理                          [+ 新建用户] │
│  ──────────────────────────────────────────    │
│  搜索框                                       │
│  ──────────────────────────────────────────    │
│  用户名    邮箱       角色    状态    操作  │
│  admin                admin    ✓活动   [编辑] │
│  alice     alice@...  member   待批准  [✓批准][×拒绝]│
│  bob       bob@...    member   ✓活动   [禁用][改admin]│
└───────────────────────────────────────────────┘
```

**功能**:
- 列表 `GET /api/admin/users`
- 搜索 (前端 filter, 因为后端没 search endpoint)
- 操作:
  - 批准新 member: `PATCH /api/admin/users/{id} {"is_approved": true}`
  - 拒绝: `DELETE /api/admin/users/{id}` (这是删除账号)
  - 改 role: `PATCH {"role": "admin"}` (提升)
  - 禁用: `PATCH {"is_active": false}`
  - 自删/自降保护 (后端会 400, 显示对应错误)

**admin 导航**: 在 UserMenu 里加 "用户管理" (admin only)

### 4. KB 切换共享的简单 UX

如果不想做复杂 UI, 最小可接受的方案:
- KB 标题区加一个 "🔒 私有" / "👥 共享" pill
- 点 pill → 调 PATCH, toggle
- 成功 → 更新 pill 状态, toast

**先做这个** (必做), 之后 admin 页面可选。

## 实施要点

### 1. `KBMainArea.tsx` 加共享 toggle

```tsx
const [kb, setKB] = useState<KB | null>(null)
const [togglingShare, setTogglingShare] = useState(false)
const { user } = useUser()  // 或 props
const toast = useToast()

const isOwnerOrAdmin = user && (user.role === 'admin' || user.id === kb?.owner_id)

const handleToggleShare = async () => {
  if (!kb) return
  setTogglingShare(true)
  try {
    const updated = await api.updateKB(kb.id, { is_shared: !kb.is_shared })
    setKB({ ...kb, is_shared: updated.is_shared, is_public: updated.is_public })
    toast({
      title: updated.is_shared ? '已设为共享' : '已设为私有',
      status: 'success', duration: 2000, position: 'top'
    })
  } catch (e: any) {
    toast({ title: '切换失败', description: e.message, status: 'error', duration: 3000 })
  } finally {
    setTogglingShare(false)
  }
}

// 在 KB 标题区:
<Button
  size="xs"
  variant="ghost"
  leftIcon={kb.is_shared ? <LockOpenIcon /> : <LockIcon />}
  isDisabled={!isOwnerOrAdmin}
  isLoading={togglingShare}
  onClick={handleToggleShare}
>
  {kb.is_shared ? '👥 共享' : '🔒 私有'}
</Button>
```

### 2. `api.ts` 加 updateKB

```tsx
updateKB: async (kbId: string, body: { name?: string; description?: string; is_shared?: boolean; is_public?: boolean }) => {
  return request<KB>(`/api/kbs/${kbId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
},
```

### 3. `api.ts` 加 admin 方法

```tsx
adminListUsers: () => request<User[]>('/api/admin/users'),
adminUpdateUser: (userId: string, body: { is_approved?: boolean; role?: string; is_active?: boolean }) =>
  request<User>(`/api/admin/users/${userId}`, { method: 'PATCH', body: JSON.stringify(body) }),
adminDeleteUser: (userId: string) =>
  request<void>(`/api/admin/users/${userId}`, { method: 'DELETE' }),
```

### 4. `KnowledgeBaseSidebar.tsx` 分组

```tsx
const myKBs = kbs.filter(kb => kb.owner_id === user?.id)
const sharedKBs = kbs.filter(kb => kb.is_shared && kb.owner_id !== user?.id)

// 渲染:
<VStack>
  <Text>我的 ({myKBs.length})</Text>
  {myKBs.map(renderKBItem)}
  
  {sharedKBs.length > 0 && (
    <>
      <Text mt={3}>共享给我 ({sharedKBs.length})</Text>
      {sharedKBs.map(renderKBItemWithoutDelete)}
    </>
  )}
</VStack>
```

### 5. `AdminUsersPage.tsx` 完整组件

```tsx
// 简化版: 列表 + 搜索 + 批量操作
export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const toast = useToast()
  const { user: currentUser } = useUser()
  
  useEffect(() => {
    api.adminListUsers().then(setUsers).finally(() => setLoading(false))
  }, [])
  
  const filtered = users.filter(u => 
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    (u.email || '').toLowerCase().includes(search.toLowerCase())
  )
  
  const handleApprove = async (u: User) => {
    try {
      await api.adminUpdateUser(u.id, { is_approved: true })
      setUsers(users.map(x => x.id === u.id ? { ...x, is_approved: true } : x))
      toast({ title: `${u.username} 已批准`, status: 'success' })
    } catch (e: any) {
      toast({ title: '操作失败', description: e.message, status: 'error' })
    }
  }
  
  const handleDelete = async (u: User) => {
    if (!window.confirm(`确定删除用户 ${u.username}? 不可恢复。`)) return
    try {
      await api.adminDeleteUser(u.id)
      setUsers(users.filter(x => x.id !== u.id))
      toast({ title: `${u.username} 已删除`, status: 'success' })
    } catch (e: any) {
      toast({ title: '删除失败', description: e.message, status: 'error' })
    }
  }
  
  const handleToggleActive = async (u: User) => {
    try {
      const updated = await api.adminUpdateUser(u.id, { is_active: !u.is_active })
      setUsers(users.map(x => x.id === u.id ? updated : x))
    } catch (e: any) {
      toast({ title: '操作失败', description: e.message, status: 'error' })
    }
  }
  
  return (
    <Box maxW="960px" mx="auto" p={{ base: 3, md: 6 }}>
      <Heading size="lg" mb={6}>用户管理</Heading>
      <Input placeholder="搜索用户名或邮箱" value={search} onChange={e => setSearch(e.target.value)} mb={4} />
      <Table variant="simple">
        <Thead>
          <Tr>
            <Th>用户名</Th>
            <Th>邮箱</Th>
            <Th>角色</Th>
            <Th>状态</Th>
            <Th>操作</Th>
          </Tr>
        </Thead>
        <Tbody>
          {filtered.map(u => (
            <Tr key={u.id}>
              <Td>{u.username}</Td>
              <Td>{u.email || '-'}</Td>
              <Td><Badge colorScheme={u.role === 'admin' ? 'purple' : 'gray'}>{u.role}</Badge></Td>
              <Td>
                {u.is_approved ? <Badge colorScheme="green">已批准</Badge> : <Badge colorScheme="yellow">待批准</Badge>}
                {u.is_active ? null : <Badge colorScheme="red" ml={1}>已禁用</Badge>}
              </Td>
              <Td>
                {!u.is_approved && (
                  <Button size="xs" colorScheme="green" mr={2} onClick={() => handleApprove(u)}>
                    批准
                  </Button>
                )}
                {u.id !== currentUser?.id && (
                  <>
                    <Button size="xs" mr={2} onClick={() => handleToggleActive(u)}>
                      {u.is_active ? '禁用' : '启用'}
                    </Button>
                    <Button size="xs" colorScheme="red" variant="ghost" onClick={() => handleDelete(u)}>
                      删除
                    </Button>
                  </>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Box>
  )
}
```

### 6. 路由 + 导航

```tsx
// App.tsx
<Route path="/admin/users" element={<AdminUsersPage />} />

// TopBar.tsx UserMenu (admin only)
{user.role === 'admin' && (
  <MenuItem icon={<SettingsIcon />} onClick={() => navigate('/admin/users')}>
    用户管理
  </MenuItem>
)}
```

## 验收标准

```bash
# V1: build
cd web && npm run build  # 0 错误

# V2: 桌面截图
#    - KB 详情页: 看到共享 pill, 点切换
#    - 侧栏: "我的" + "共享给我" 分组
#    - admin 登录 → UserMenu 看到 "用户管理" → 进 admin 页
#    - 看到 alice / bob 等, 批准 / 拒绝 / 禁用 按钮工作

# V3: 移动截图
#    - KB 详情页: 共享 pill (小, 单字)
#    - 侧栏: 折叠菜单 (默认看 "我的", 展开 "共享给我")
#    - admin 用户管理: 表格可滚动

# V4: e2e
#    - 创建 member → 管理员收到通知 (top bar 红点) → 进 /admin/users → 批准
#    - 切换共享 → 看其他 user 是否能看见
```

## 不准做

- 不改后端
- 不引新依赖
- 不改 theme.ts (除非微调)
- 不 push
- 不重启服务

## 完成后

```bash
cd web && npm run build
git add -A
git commit -m "feat(ui): shared KB toggle + user grouping in sidebar + admin users page"
```

## 主协调验收

主协调会:
1. build 0 错误
2. 桌面 + 移动三档截图
3. 真链路 (注册新用户 → admin 批准 → 切换 KB 共享)
4. 推 Pi

START NOW.