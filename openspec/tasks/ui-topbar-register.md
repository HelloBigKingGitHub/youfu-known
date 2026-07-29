# UI Redesign: 顶栏用户信息 + 注册 + Turnstile 防机器人

> **任务编号**: ui-topbar-register-turnstile  
> **派发对象**: Kimi (前端 Coding Agent)  
> **状态**: ✅ 已完成 (commits `f3eeb36` + `e5517a1` + `0eff24f` + `71fb803`)  
> **基于**: 当前 commit `cc873d1` (前端认证集成, 缺顶栏 + 注册)

## 背景

当前 SPA 用户信息在**侧栏顶部**(`UserMenu` 在 `KnowledgeBaseSidebar` 里)。但行业惯例:
- **桌面端**: 用户信息在**顶栏右上角**(Vercel, Linear, Notion, GitHub, ChatGPT 都这样)
- **移动端**: 用户信息在**顶栏右侧**(可能是头像或汉堡, 不用开侧栏)

另外, 系统**只有一个 admin 账号**, **没有注册功能**。需要开放注册(用 admin 批准机制), 同时**防机器人滥用**。

本 spec 设计**顶栏 + 注册 + 防机器人**。

## 设计目标

### 1. 顶栏 (TopBar, 全新组件)

**桌面 (lg+)**:
```
┌─────────────────────────────────────────────────────────────┐
│  [≡] youfu-known                            [🔍 KB 名] [👤▾] │  ← 顶栏
│  ┌─────┐ ┌─────────────────────────────┐                  │
│  │侧栏 │ │ 主区域                      │                  │
│  │     │ │                              │                  │
│  └─────┘ └─────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```
- 顶栏固定在顶部 (sticky, 56px 高, 白底, 底部细边框)
- 左侧: 汉堡按钮 (toggle 侧栏抽屉) + 标题 `youfu-known`
- 中间 (可选): 当前 KB 名 (居中, 灰字)
- 右侧: 用户头像/菜单 (点击展开)
  - `👤 admin` ▼ → 下拉菜单:
    - 当前用户信息 (头像 + 用户名 + role)
    - 修改密码
    - 登出

**平板 (md)**: 同桌面布局, 顶栏窄一点

**手机 (base)**: 
```
┌─────────────────────────┐
│ [≡] youfu-known   [👤▾] │  ← 顶栏 56px
├─────────────────────────┤
│ 主区域                  │
│                         │
│                         │
└─────────────────────────┘
```
- 左侧: 汉堡 (打开侧栏 Drawer)
- 中间: 标题
- 右侧: 用户头像/菜单
- 主区域 padding 收紧

**关键**:
- 顶栏与侧栏**共存**: 桌面有侧栏 + 顶栏 (顶栏用于用户, 侧栏用于 KB 列表)
- 移动: 顶栏替换侧栏 (Drawer 式)

### 2. 注册功能 (`/register` 路由)

**新路由**:
```
GET /register
```
**视觉**: 跟 `/login` 同风格卡片, 但字段更多:
- 用户名 (3-32 字符, `^[a-zA-Z0-9_-]+$`)
- 邮箱 (选填, 用作验证)
- 密码 (8+ 字符)
- 确认密码
- Turnstile 验证 (Cloudflare 小部件, 0 摩擦)
- "注册" 蓝色按钮
- 底部链接: "已有账号? 登录"

**成功后**:
- 调 `POST /api/auth/register`
- 弹 toast: "注册成功, 等待管理员批准"
- 跳 `/login` (不自动登录, 因为 is_approved=False)

### 3. Cloudflare Turnstile 防机器人

**已有 Cloudflare 账号** (sxy.homes), 直接用 Turnstile widget:
- Site key: `1x00000000000000000000AA` (Cloudflare 测试 key, **生产换真 key**)
- 验证在前端完成 (用户无感知), 拿到 token
- 后端调 `https://challenges.cloudflare.com/turnstile/v0/siteverify` 验证

**后端需要**:
- 环境变量: `YOUFU_TURNSTILE_SECRET=*** (生产) / 1x0000000000000000000000000000000AA (dev)`
- `POST /api/auth/register` 接收 `turnstile_token` 字段, 验证
- dev 模式 (没设 secret): 跳过验证 + 警告日志
- 生产: 严格验证, 失败 403

**UI**:
- 注册页底部, 在 "注册" 按钮上方
- 一个小卡片 widget (Cloudflare 提供的 React 组件, `<div class="cf-turnstile" data-sitekey="...">`)
- 不可见时 (用户没操作) 提交按钮 disabled

### 4. 实施细节

#### 4.1 TopBar 组件

新文件 `web/src/components/TopBar.tsx`:

```tsx
import { Box, Flex, HStack, IconButton, Text, useBreakpointValue, Menu, MenuButton, MenuList, MenuItem, MenuDivider, Button, Avatar } from '@chakra-ui/react'
import { ChevronDownIcon, HamburgerIcon, LockIcon, LogoutIcon } from '@chakra-ui/icons'
import { useNavigate } from 'react-router-dom'

interface Props {
  user: { username: string; role: string } | null
  currentKBName?: string
  onToggleSidebar: () => void  // 移动端打开 Drawer
  onLogout: () => void
  isMobile: boolean
}

export function TopBar({ user, currentKBName, onToggleSidebar, onLogout, isMobile }: Props) {
  const navigate = useNavigate()
  return (
    <Flex
      h="56px"
      align="center"
      px={{ base: 3, md: 4 }}
      bg="surface.raised"
      borderBottom="1px"
      borderColor="surface.border"
      position="sticky"
      top={0}
      zIndex={20}
      gap={3}
    >
      {isMobile && (
        <IconButton
          aria-label="打开侧栏"
          icon={<HamburgerIcon />}
          variant="ghost"
          onClick={onToggleSidebar}
          minW="44px"
          minH="44px"
        />
      )}
      <Text fontSize="md" fontWeight="bold" color="brand.700" noOfLines={1}>
        youfu-known
      </Text>
      {currentKBName && !isMobile && (
        <Text fontSize="sm" color="gray.500" noOfLines={1} flex={1} textAlign="center">
          {currentKBName}
        </Text>
      )}
      <Box flex={1} />  {/* 推动右侧 */}
      {user ? (
        <Menu>
          <MenuButton
            as={Button}
            rightIcon={<ChevronDownIcon />}
            variant="ghost"
            size="sm"
            minH="44px"
          >
            <HStack spacing={2}>
              <Avatar size="xs" name={user.username} />
              <Text fontSize="sm">{user.username}</Text>
            </HStack>
          </MenuButton>
          <MenuList>
            <MenuItem isDisabled>
              <Text fontSize="xs" color="gray.500">
                {user.role === 'admin' ? '👑 管理员' : '👤 成员'}
              </Text>
            </MenuItem>
            <MenuDivider />
            <MenuItem icon={<LockIcon />} onClick={() => navigate('/change-password')}>
              修改密码
            </MenuItem>
            <MenuItem icon={<LogoutIcon />} color="red.500" onClick={onLogout}>
              登出
            </MenuItem>
          </MenuList>
        </Menu>
      ) : (
        <Button size="sm" colorScheme="brand" onClick={() => navigate('/login')}>
          登录
        </Button>
      )}
    </Flex>
  )
}
```

#### 4.2 App.tsx 改造

```tsx
// 拿当前 KB 名
const location = useLocation()
const { kbId } = useParams<{ kbId: string }>()
const [kbs, setKBs] = useState<KB[]>([])
const drawer = useDisclosure()
const isMobile = useBreakpointValue({ base: true, md: false })

// 从 KBs 找当前 KB
const currentKB = kbs.find(kb => kb.id === kbId)

return (
  <Flex direction="column" h="100vh" w="100vw" overflow="hidden" bg="surface.base">
    <TopBar
      user={user}
      currentKBName={currentKB?.name}
      onToggleSidebar={drawer.onOpen}
      onLogout={handleLogout}
      isMobile={!!isMobile}
    />
    <Flex flex={1} overflow="hidden">
      {!isMobile && (
        <KnowledgeBaseSidebar ... />  // 桌面端固定侧栏
      )}
      {isMobile && (
        <Drawer isOpen={drawer.isOpen} onClose={drawer.onClose} placement="left" size="xs">
          ... <KnowledgeBaseSidebar ... />
        </Drawer>
      )}
      <Box flex={1} overflow="auto">
        <Routes>
          <Route path="/login" element={<LoginPage ... />} />
          <Route path="/register" element={<RegisterPage ... />} />
          <Route element={<RequireAuth />}>
            <Route path="/" ... />
            <Route path="/kbs/:kbId" ... />
            ...
          </Route>
        </Routes>
      </Box>
    </Flex>
  </Flex>
)
```

**关键改动**:
- 把 KB Drawer 从 KnowledgeBaseSidebar 提到 App.tsx
- 顶栏 + 主区域用 Flex 布局
- 桌面: 顶栏 + 侧栏 + 主区域 (三者并排)
- 移动: 顶栏 + 主区域, 侧栏进 Drawer

#### 4.3 RegisterPage 组件

新文件 `web/src/components/RegisterPage.tsx`:

```tsx
import { useState, useEffect, useRef } from 'react'
import { useNavigate, Link as RouterLink } from 'react-router-dom'
import { Box, Button, Card, CardBody, Center, FormControl, FormLabel, Heading, Input, Link, Stack, Text, VStack, useToast, FormHelperText, FormErrorMessage } from '@chakra-ui/react'

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: any) => string
      reset: (widgetId?: string) => void
      getResponse: (widgetId?: string) => string
    }
  }
}

export function RegisterPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null)
  const turnstileRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | null>(null)
  const navigate = useNavigate()
  const toast = useToast()

  useEffect(() => {
    // 动态加载 Turnstile script
    const script = document.createElement('script')
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
    script.async = true
    script.defer = true
    document.head.appendChild(script)
    script.onload = () => {
      if (window.turnstile && turnstileRef.current) {
        widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
          sitekey: import.meta.env.VITE_TURNSTILE_SITE_KEY || '1x00000000000000000000AA',
          callback: (token: string) => setTurnstileToken(token),
          'expired-callback': () => setTurnstileToken(null),
        })
      }
    }
    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current)
      }
      document.head.removeChild(script)
    }
  }, [])

  const handleSubmit = async () => {
    if (!username.trim() || !password) return
    if (password !== confirm) {
      toast({ title: '两次密码不一致', status: 'error', duration: 3000 })
      return
    }
    if (!turnstileToken) {
      toast({ title: '请先完成人机验证', status: 'error', duration: 3000 })
      return
    }
    setLoading(true)
    try {
      await api.register(username.trim(), email, password, turnstileToken)
      toast({ title: '注册成功, 等待管理员批准', status: 'success', duration: 4000 })
      navigate('/login')
    } catch (e: any) {
      toast({ title: '注册失败', description: e.message, status: 'error', duration: 4000 })
    } finally {
      setLoading(false)
      // 重置 Turnstile
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.reset(widgetIdRef.current)
        setTurnstileToken(null)
      }
    }
  }

  return (
    <Center minH="100vh" bg="gray.50" px={4} py={8}>
      <Card maxW="440px" w="full" boxShadow="lg" borderRadius="2xl">
        <CardBody p={{ base: 6, md: 8 }}>
          <VStack spacing={6}>
            <VStack spacing={2} align="center">
              <Box w="56px" h="56px" bg="brand.500" color="white" borderRadius="2xl" display="flex" alignItems="center" justifyContent="center" fontSize="2xl" fontWeight="bold">
                Y
              </Box>
              <Heading size="lg">注册账号</Heading>
              <Text fontSize="sm" color="gray.500">注册后需管理员批准才能登录</Text>
            </VStack>

            <Stack spacing={4} w="full">
              <FormControl isRequired>
                <FormLabel fontSize="sm">用户名</FormLabel>
                <Input value={username} onChange={e => setUsername(e.target.value)} placeholder="3-32 字符, 字母数字下划线" size="lg" autoFocus isDisabled={loading} />
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">邮箱 (选填)</FormLabel>
                <Input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="用于接收通知" size="lg" isDisabled={loading} />
              </FormControl>
              <FormControl isRequired>
                <FormLabel fontSize="sm">密码</FormLabel>
                <Input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="8 字符以上" size="lg" isDisabled={loading} />
              </FormControl>
              <FormControl isRequired isInvalid={confirm && password !== confirm}>
                <FormLabel fontSize="sm">确认密码</FormLabel>
                <Input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="再次输入" size="lg" isDisabled={loading} />
                {confirm && password !== confirm && <FormErrorMessage>两次密码不一致</FormErrorMessage>}
              </FormControl>
            </Stack>

            {/* Turnstile widget */}
            <Box ref={turnstileRef} w="full" />

            <Button colorScheme="brand" size="lg" w="full" onClick={handleSubmit} isLoading={loading} loadingText="注册中" isDisabled={!turnstileToken}>
              注册
            </Button>

            <Text fontSize="sm" color="gray.600" textAlign="center">
              已有账号?{' '}
              <Link as={RouterLink} to="/login" color="brand.600" fontWeight="semibold">
                登录
              </Link>
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </Center>
  )
}
```

#### 4.4 api.ts 加 register

```tsx
register: async (username: string, email: string, password: string, turnstileToken: string) => {
  return request('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, email, password, turnstile_token: turnstileToken }),
  })
},
```

#### 4.5 vite.config.ts 加环境变量

```ts
// .env.local 加:
// VITE_TURNSTILE_SITE_KEY=1x00000000000000000000AA
```

## 验收标准

```bash
# V1: build
cd web && npm run build  # 0 错误

# V2: 桌面截图 (1280x800)
#    - 顶栏右上角看到 [👤 admin ▼]
#    - 点开下拉: 修改密码 / 登出
#    - 侧栏仍然在左边 (共存)
#    - 主区域内容不变

# V3: 移动截图 (390x844)
#    - 顶栏 [≡] [youfu-known] [👤▼]
#    - 点 [≡] 打开侧栏 Drawer
#    - 点 [👤▼] 弹出修改密码/登出

# V4: 注册页 (iPhone 14)
#    - 路由 /register
#    - 看到 Turnstile widget
#    - 输入完 + 完成验证 → 注册按钮可点
#    - 成功后跳 /login, toast "等待管理员批准"
#    - 试错密码 → 表单错误提示
#    - 试重复用户名 → toast "用户名已存在"

# V5: 后端流程 (curl, 用 admin123 临时 admin)
#    POST /api/auth/register {username, password, turnstile_token} → 201
#    数据库出现新 user (is_approved=False)
#    admin login → /api/admin/users → 看到新 user
#    PATCH /api/admin/users/{id} {is_approved:true} → 200
#    新 user 重新 login → 200
```

## 不准做

- 不引新依赖 (Turnstile 走原生 script, 不需要 react-turnstile 包)
- 不改后端
- 不改 theme.ts
- 不 push
- 不重启服务 / 部署 (主协调验收后做)

## 完成后

```bash
cd web && npm run build  # 0 错误
git add -A
git commit -m "feat(ui): top bar with user menu + register page + Turnstile"
```

报告:
- 改的文件清单
- build 输出
- 任何 spec 偏离

START NOW.