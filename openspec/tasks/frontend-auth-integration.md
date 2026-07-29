# 前端认证集成 Spec

> **任务编号**: frontend-auth-integration  
> **派发对象**: Kimi (前端 Coding Agent)  
> **状态**: ✅ 已完成 (commit `cc873d1`)

## 背景

后端认证 + RBAC 已上线 (`06f0521`)。但 SPA 还**完全无认证概念**:
- 没登录页
- fetch 不带 cookie (`credentials` 默认 omit)
- API 401 收到也无所谓 (继续走)
- 侧栏没用户菜单
- 任何人都能进 KB 路由

本 spec 设计前端接入, 用户体验好的登录流程。

## 设计目标

### 用户体验流程

**未登录用户**访问 https://kb.sxy.homes:
1. SPA 启动, 调 `GET /api/auth/me`
2. 401 → 跳 `/login` (sidebar/chat 都隐藏)
3. 用户输入 username + password
4. POST `/api/auth/login` → 200 + Set-Cookie
5. SPA 自动跳 `/` 或上次访问的 KB
6. 侧栏顶部显示 `👤 admin [登出]`
7. 进 KB 路由正常工作

**已登录用户**:
- 侧栏顶部显示用户名 + 登出按钮
- 任何 fetch 自动带 cookie (browser 自动处理)
- 401 → 清 localStorage 的 user state, 跳 `/login`
- token 过期 (24h) → 显示 toast "会话过期, 请重新登录"

### 视觉效果

**登录页 `/login`**:
- 全屏居中卡片
- 背景浅灰 (gray.50)
- 白底圆角卡片 (max-width 400px)
- logo + "youfu-known" 标题
- 用户名输入框 (大, 44px height)
- 密码输入框 (大)
- "登录" 蓝色按钮 (全宽)
- 失败: 红色 toast "用户名或密码错误"
- loading: 按钮 spinner

**侧栏顶部 UserMenu** (替代之前的纯标题):
```
┌─────────────────┐
│ youfu-known     │  ← 标题
├─────────────────┤
│ ┌─────────┐      │
│ │ 👤 admin│      │  ← 用户菜单 (折叠按钮)
│ └─────────┘      │
│ + 新建知识库     │
└─────────────────┘
```
点 UserMenu → 弹出下拉: "登出" + "修改密码"

## 实现要点

### 1. `web/src/components/LoginPage.tsx` (新)

```tsx
import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Box, Button, Card, CardBody, Center, FormControl, FormLabel, Heading, Input, Spinner, Stack, Text, VStack, useToast } from '@chakra-ui/react';
import { api } from '../api';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  const from = (location.state as any)?.from || '/';

  const handleSubmit = async () => {
    if (!username.trim() || !password) return;
    setLoading(true);
    try {
      const resp = await api.login(username.trim(), password);
      // 存 user 到 localStorage (方便侧栏显示, 不是 token)
      localStorage.setItem('user', JSON.stringify(resp.user));
      navigate(from, { replace: true });
    } catch (e: any) {
      toast({
        title: '登录失败',
        description: e.message || '用户名或密码错误',
        status: 'error',
        duration: 4000,
        position: 'top',
      });
    } finally {
      setLoading(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit();
  };

  return (
    <Center minH="100vh" bg="gray.50" px={4}>
      <Card maxW="400px" w="full" boxShadow="lg" borderRadius="2xl">
        <CardBody p={{ base: 6, md: 8 }}>
          <VStack spacing={6}>
            <VStack spacing={2} align="center">
              <Box w="56px" h="56px" bg="brand.500" color="white" borderRadius="2xl" display="flex" alignItems="center" justifyContent="center" fontSize="2xl" fontWeight="bold">
                Y
              </Box>
              <Heading size="lg">youfu-known</Heading>
              <Text fontSize="sm" color="gray.500">登录以使用知识库问答</Text>
            </VStack>

            <Stack spacing={4} w="full">
              <FormControl>
                <FormLabel fontSize="sm">用户名</FormLabel>
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="admin"
                  size="lg"
                  autoFocus
                  isDisabled={loading}
                />
              </FormControl>
              <FormControl>
                <FormLabel fontSize="sm">密码</FormLabel>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="••••••••"
                  size="lg"
                  isDisabled={loading}
                />
              </FormControl>
            </Stack>

            <Button
              colorScheme="brand"
              size="lg"
              w="full"
              onClick={handleSubmit}
              isLoading={loading}
              loadingText="登录中"
            >
              登录
            </Button>

            <Text fontSize="xs" color="gray.400" textAlign="center">
              个人知识库 · 数据本地存储
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </Center>
  );
}
```

### 2. `web/src/components/RequireAuth.tsx` (新)

```tsx
import { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Center, Spinner } from '@chakra-ui/react';
import { api } from '../api';

export function RequireAuth() {
  const [authState, setAuthState] = useState<'loading' | 'authed' | 'unauthed'>('loading');
  const location = useLocation();

  useEffect(() => {
    api.me()
      .then(() => setAuthState('authed'))
      .catch(() => setAuthState('unauthed'));
  }, []);

  if (authState === 'loading') {
    return (
      <Center h="100vh">
        <Spinner size="lg" color="brand.500" />
      </Center>
    );
  }

  if (authState === 'unauthed') {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  return <Outlet />;
}
```

### 3. `web/src/components/UserMenu.tsx` (新)

```tsx
import { Button, Menu, MenuButton, MenuDivider, MenuItem, MenuList, Text } from '@chakra-ui/react';
import { ChevronDownIcon, DeleteIcon, LockIcon } from '@chakra-ui/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

interface Props { user: { username: string; role: string } | null; onLogout: () => void; }

export function UserMenu({ user, onLogout }: Props) {
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <Menu>
      <MenuButton as={Button} rightIcon={<ChevronDownIcon />} variant="ghost" size="sm" w="full" justifyContent="space-between">
        <Text fontSize="sm">👤 {user.username}</Text>
      </MenuButton>
      <MenuList>
        <MenuItem icon={<LockIcon />} onClick={() => navigate('/change-password')}>
          修改密码
        </MenuItem>
        <MenuDivider />
        <MenuItem icon={<DeleteIcon />} color="red.500" onClick={async () => {
          await api.logout();
          onLogout();
          navigate('/login', { replace: true });
        }}>
          登出
        </MenuItem>
      </MenuList>
    </Menu>
  );
}
```

### 4. `web/src/api.ts` 修改

```tsx
// 加这些方法
export const api = {
  // 现有方法...

  login: async (username: string, password: string) => {
    const r = await request<LoginResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    return r;
  },

  logout: async () => {
    await request('/api/auth/logout', { method: 'POST' });
  },

  me: async (): Promise<User> => {
    const r = await request<User>('/api/auth/me');
    return r;
  },

  changePassword: async (oldPassword: string, newPassword: string) => {
    await request('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
  },
};

// 改 fetch 默认带 cookie
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    credentials: 'include',  // ← 关键
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
    ...init,
  });
  // 401 处理 (自动跳登录)
  if (resp.status === 401 && !path.includes('/auth/login')) {
    // 跳登录 (但避免在 login 页面再跳)
    window.location.href = '/login';
    throw new Error('not authenticated');
  }
  const body = await resp.json();
  if (body.code !== 0) throw new ApiError(body.code, body.message, body.detail);
  return body.data as T;
}
```

### 5. `web/src/App.tsx` 改路由

```tsx
<Routes>
  <Route path="/login" element={<LoginPage />} />
  <Route element={<RequireAuth />}>
    <Route path="/" element={<RootRedirect />} />
    <Route path="/kbs/:kbId" element={<KBRoute />} />
    <Route path="/kbs/:kbId/manage" element={<KBRoute />} />
    <Route path="/kbs/:kbId/chat" element={<KBRoute />} />
    <Route path="/change-password" element={<ChangePasswordPage />} />
    <Route path="*" element={<EmptyState />} />
  </Route>
</Routes>
```

### 6. 改 PasswordPage (新建小页)

`web/src/components/ChangePasswordPage.tsx`:
- 跟 LoginPage 风格统一
- 输入旧密码 + 新密码 + 确认
- 提交 `POST /api/auth/change-password`
- 成功 toast, 跳回

## 验收标准

```bash
# 1. build
cd web && npm run build  # 0 错误

# 2. 桌面截图 (1280x800)
#    - 未登录: 跳 /login 卡片
#    - 登录后: 看到 UserMenu
#    - 登出: 跳 /login

# 3. 移动截图 (390x844)
#    - 登录页大输入框
#    - 登出按钮可点 (>= 44px)

# 4. e2e:
#    - 登录成功 → 进 KB
#    - 输入错密码 → 红 toast, 还在 /login
#    - 登录后点登出 → 跳 /login
#    - 在登录态访问 / → 走 RequireAuth 进 KB
```

## 不准做

- 不引新依赖
- 不改后端代码
- 不改 theme.ts (除非 LoginPage 微调色)
- 不改 ChatPanel / DocumentList / Uploader 内部 (只集成 cookie)

## 完成后

```bash
cd web && npm run build  # 0 错误
git add -A
git commit -m "feat(ui): auth integration (login page, RequireAuth, user menu)"
```

## 主协调验收

主协调 (Hermes) 会:
1. build 验证 (0 错误)
2. 三档截图 (登录前/登录后/登出)
3. 端到端 (未登录访问 / → 跳 /login → 登录 → KB 正常)
4. 推 Pi + 验证

START NOW.