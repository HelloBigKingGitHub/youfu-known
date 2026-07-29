# UI Redesign: Tab 拆分 + 现代优雅

> **任务编号**: ui-elegance-redesign  
> **派发日期**: 2026-07-19  
> **派发对象**: Claude Code (frontend backup) 或 Kimi  
> **当前状态**: 未开始

## 背景

`youfu-known` SPA 当前 KB 主区域 (KBMainArea) 把"上传 + 文档列表 + 问答" 三块内容堆在一页滚, 用户反馈:

1. **页面拥挤** — 滚动太长, 找不到目标
2. **手机端输入框丑** — Chakra 默认 input 太朴素
3. **整体风格过时** — 跟现代 SaaS (Linear / Notion / Vercel) 比, 显得平
4. **缺乏层次** — 没阴影没圆角, 全是平面

## 目标

### 核心改动 #1: 单 KB 下分两个 Tab (新路由)

**当前**: `/kbs/:kbId` → 一页堆三块
**目标**:
- `/kbs/:kbId` → 重定向到 `/kbs/:kbId/manage`
- `/kbs/:kbId/manage` → 知识库管理 (上传 + 文档列表)
- `/kbs/:kbId/chat` → 智能问答 (独立宽敞)

**实现**: 用 react-router 子路由, 配 Chakra `Tabs` 顶部切换器

**Tab 切换器设计** (软胶囊风格, 类似 macOS segmented control):
```
┌─────────────────────────────────────────────┐
│  KB 标题区 (固定, 两个 tab 都显示)            │
│  ──────────────────────────────────          │
│  ┌─────────┐  ┌─────────┐                    │
│  │ 📎 管理 │  │ 💬 问答 │  ← Tab 切换器      │
│  └─────────┘  └─────────┘                    │
│                                             │
│  (Tab 内容, 各自全宽独立滚动)                │
└─────────────────────────────────────────────┘
```

### Tab 1: 知识库管理 (KBManageTab)

组件: `web/src/components/KBManageTab.tsx` (新)

内容:
- Uploader (拖拽 + 点击上传)
- DocumentList (移动端卡片, 桌面行卡)

### Tab 2: 智能问答 (KBChatTab)

组件: `web/src/components/KBChatTab.tsx` (新)

内容:
- ChatPanel (现有的, 但 UI 升级)
- 顶部小提示: "基于本知识库内容回答"

### 核心改动 #2: UI 现代化 (theme + 主要组件)

**目标风格**: 现代 SaaS 风格 (Linear / Notion / Vercel 感觉)
- 圆角加大 (md=10px, lg=14px, xl=18px, 2xl=24px)
- 阴影分层 (xs/sm/md/lg/xl 五级)
- 颜色: 蓝色品牌 (#3b82f6) + 中性灰
- 字体: Inter + 中文回退 (PingFang SC / Microsoft YaHei)
- 间距: 统一 4 / 6 / 8 像素倍数
- 边框: 浅灰 (#e8eaed)

**涉及组件**:
- `theme.ts` (新增品牌色 + shadow + radii)
- `ChatPanel.tsx` (重点: 输入框改为 Textarea + 内嵌发送按钮)
- `Uploader.tsx` (整块可点击 + dashed 边框 + 居中布局)
- `DocumentList.tsx` (卡片化, 圆形状态徽章)
- `KBMainArea.tsx` (Tabs + 顶部固定 KB 信息)

### 核心改动 #3: 响应式保持

- 桌面 (lg+): Tab 切换器 + 内容并排 (Tab 1: 文档表格行卡; Tab 2: 问答历史 + 输入框)
- 平板 (md): 同桌面布局, 略窄
- 手机 (base): Tab 切换器水平排, Tab 1 文档用卡片列表, Tab 2 输入框在底部

## 设计硬约束

### 不准改的东西

- `api.ts` (后端 API 契约)
- `types.ts` (TypeScript 类型)
- `main.tsx` (入口)
- `package.json` (不加新依赖)
- `react-router-dom` 路由配置 (除非加子路由)

### 桌面 (lg+) 视觉变化

桌面布局**可以**改进,但要保持:
- 侧栏 280px (不变)
- 主区域 max-width 960px 居中 (不变)
- KB 标题区字号风格 (基本不变)
- 删除按钮 + 编辑按钮位置

### 触摸目标 ≥ 44px (移动端所有可点元素)

### 引用可点击展开, 不能丢

### 数据完全保留 (上传 / 问答 / 文档) - 不重置状态

## 实现要点

### 路由改造

`web/src/App.tsx`:

```tsx
<Route path="/kbs/:kbId" element={<KBRoute />} />
<Route path="/kbs/:kbId/manage" element={<KBRoute />} />
<Route path="/kbs/:kbId/chat" element={<KBRoute />} />
```

或者用嵌套路由:
```tsx
<Route path="/kbs/:kbId" element={<KBShell />}>
  <Route index element={<Navigate to="manage" replace />} />
  <Route path="manage" element={<KBManageTab />} />
  <Route path="chat" element={<KBChatTab />} />
</Route>
```

(Claude 选合适方式)

### Chakra Tabs 样式

使用 `variant="soft-rounded"`, 自定义 `_selected`:
```tsx
<Tab
  fontSize="sm"
  fontWeight="semibold"
  borderRadius="lg"
  _selected={{ bg: 'white', color: 'brand.600', boxShadow: 'sm' }}
  color="gray.500"
>
```

外层 `TabList` 用 `bg="surface.sunken"` 灰色背景 + `borderRadius="xl"`, 形成胶囊感。

### 输入框升级 (ChatPanel)

```tsx
<Flex
  align="flex-end"
  gap={2}
  bg="surface.sunken"
  borderRadius="xl"
  border="1px"
  borderColor="surface.border"
  p={2}
  _focusWithin={{
    borderColor: 'brand.300',
    boxShadow: '0 0 0 3px rgba(59,130,246,0.12)',
  }}
>
  <Textarea
    placeholder="输入你的问题..."
    border="none"
    _focus={{ boxShadow: 'none' }}
    flex={1}
    resize="none"
    rows={1}
    minH="40px"
    maxH="120px"
  />
  <Button
    colorScheme="brand"
    leftIcon={<ArrowUpIcon />}
    size="md"
  >
    发送
  </Button>
</Flex>
```

Enter 发送, Shift+Enter 换行。

### 文档卡片

每文档一张卡:
- 左侧文件图标 (灰色, 圆角方块)
- 中间文件名 + 大小 + chunks + 状态徽章
- 右侧操作 (刷新 + 删除)

状态徽章:
- 就绪: 绿色 pill, 小绿点
- 处理中: 蓝色 pill, spinner
- 失败: 红色 pill, 错误提示 tooltip
- 等待: 灰色 pill

### KB 标题区 (顶部固定)

```
KB 名称 (大号粗体)
描述 (灰色, 小号, 1 行)
[2 文档] [7115 chunks]  ← 灰色 pill
```

桌面端右侧 / 移动端下方显示。

## 验收清单 (主协调亲自跑)

```bash
cd web && npm run build
# 必须 0 错误

# 1. 桌面截图 (1280x800): KB 详情页
#    - 看得到 Tab 切换器 + KB 标题区
#    - Tab 1 默认显示 (上传 + 文档)
#    - 点 Tab 2 看问答区 (空状态应该友好)

# 2. 平板截图 (768x1024): 同桌面布局

# 3. 手机截图 (390x844):
#    - Tab 切换器在标题下
#    - 文档用卡片列表
#    - 问答输入框在底部 (粘性)

# 4. 交互测试:
#    - 上传 docx → Tab 1 文档列表更新
#    - 切 Tab 2 → 问问题 → 引用可展开
#    - 手机切 KB 侧栏 → Tab 1 默认显示
```

## 技术细节

### 现有 ChatPanel 的关键行为 (不要丢)

- 自动滚到底部 (除非用户手动向上滚)
- "思考中" 三点动画
- 引用可展开
- 清空问答确认
- Enter 发送 (Shift+Enter 换行)

### KBManageTab 复用现有组件

不要重写 Uploader / DocumentList,只组合:
```tsx
<VStack align="stretch" spacing={5}>
  <Uploader kbId={kbId} onUploaded={onRefresh} />
  {documents.length > 0 && (
    <DocumentList kbId={kbId} documents={documents} onChange={onRefresh} />
  )}
</VStack>
```

### KBChatTab 复用 ChatPanel

```tsx
<Box>
  <Text fontSize="sm" color="gray.500" mb={4} textAlign="center">
    基于本知识库内容回答, 引用可点击展开
  </Text>
  <ChatPanel kbId={kbId} />
</Box>
```

## 不准做

- ❌ 改 KB 创建/删除逻辑
- ❌ 改后端 API 调用
- ❌ 改侧栏 (Drawer 模式)
- ❌ 重命名路由
- ❌ 加新依赖

## 完成后

```bash
cd web && npm run build  # 必须 0 错误
# git add + commit (commit msg: "feat(ui): tab-based KB view + modern theme")
# 不要 push
```

报告:
- 改了哪些文件
- build 输出
- 任何 spec 偏离

## 主协调 (我) 验收

主协调 (Hermes) 会:
1. 跑 build
2. 跑三档截图
3. 验证 Tab 切换 + 路由跳转
4. 不通过 → 重派 / 通过 → 推到 Pi + 外网验证