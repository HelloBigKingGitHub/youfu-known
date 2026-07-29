# UI Fix: 输入框滚动条 + 引用默认折叠 + iPhone Pro Max 按钮错位

> **任务编号**: ui-input-fix  
> **派发对象**: Claude Code (frontend backup)  
> **状态**: 未开始  
> **基于**: `ddead1a` commit (Claude 上轮 UI 改造)

## 三个 Bug

### Bug #1: 输入框滚动条丑

**位置**: `web/src/components/ChatPanel.tsx`

**问题**: Textarea 在长文本时显示 Chrome 默认滚动条, 影响美观
**修复**: Textarea 自适应高度 + 隐藏滚动条 (但保留滚动能力, 内容过长时仍可滚)

**实现**:
```tsx
<Textarea
  ...
  minH="44px"
  maxH="160px"
  resize="none"
  overflowY="auto"
  sx={{
    '&::-webkit-scrollbar': { display: 'none' },
    'scrollbarWidth': 'none',  // Firefox
    '-ms-overflow-style': 'none',  // IE/Edge
  }}
/>
```

或者使用 Chakra:
```tsx
css={{
  scrollbarWidth: 'none',
  '&::-webkit-scrollbar': { display: 'none' },
}}
```

**也可以**用更激进方案 — Textarea 不需要滚动条, 因为:
- 单条消息应该简短
- 如果超长, 用户应该发完一条再发下一条
- 长文本用 Enter 换行 → 高度自适应到 maxH 后保持

### Bug #2: 引用默认展开, 遮答案

**位置**: `web/src/components/CitationPanel.tsx`

**问题**: 引用列表默认展开(Collapse in={open}), 但 open 初始值默认是 false, 看起来应该折叠。但用户说"展开遮答案"——检查当前实现是否确实默认折叠

**当前代码** (推测):
```tsx
function CitationItem({ citation: c }: { citation: Citation }) {
  const [open, setOpen] = useState(false)  // 应该 false
  return <Collapse in={open}>...</Collapse>
}
```

如果 `useState(false)` 但用户看到展开, 可能是:
- (a) 当前实现是 `useState(true)` (默认展开) → 改成 false
- (b) Collapse 动画问题 → 初始渲染就直接渲染了内容, 而不是隐藏

**修复**: 确认初始折叠。如果引用列表**整体**默认折叠, 可以加个 `<Box>` 包裹, 用 useState 控制 "显示引用 N 个" 的展开/折叠。

**实现方案**:
```tsx
function CitationPanel({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <Box mt={3} bg="surface.sunken" borderRadius="lg" p={3} border="1px" borderColor="surface.border">
      <Button
        variant="ghost"
        size="sm"
        w="full"
        justifyContent="flex-start"
        onClick={() => setExpanded(!expanded)}
      >
        <Text fontSize="xs" fontWeight="semibold" color="gray.600">
          引用 ({citations.length})
          {expanded ? ' ▾' : ' ▸'}
        </Text>
      </Button>
      {expanded && (
        <VStack align="stretch" spacing={1} mt={2}>
          {citations.map(c => <CitationItem key={c.n} citation={c} />)}
        </VStack>
      )}
    </Box>
  )
}
```

这样:
- 默认只显示 "引用 (3) ▸", 一个按钮
- 用户点一下才展开全部
- 答案本身永远是主视觉, 引用是辅助信息

### Bug #3: iPhone Pro Max 输入框 + 按钮错位

**位置**: `web/src/components/ChatPanel.tsx` 输入区

**问题**: 在 iPhone 14 Pro Max (430x932) 上, 发送按钮位置不对齐输入框垂直中心. 看起来按钮浮在输入框顶部.

**当前代码** (推测):
```tsx
<Flex align="flex-end" gap={2} ...>
  <Textarea minH="40px" maxH="120px" rows={1} resize="none" />
  <Button minH="40px" ...>发送</Button>
</Flex>
```

`align="flex-end"` 让按钮底部对齐 textarea 底部. 但 textarea 自动高度变化时, 单行时高度 ~24px, 多行时变高. 按钮高度 40px 始终, 所以多行时按钮在底部对齐, 看起来 OK; 但**单行 + align flex-end** 时按钮底部对齐 textarea 底部 (很短), 按钮看起来浮在中间偏上.

**修复方案**:

**方案 A**: 用 `align="center"` 而不是 `flex-end`. 但这样按钮中心对齐 textarea 中心, 多行时按钮在 textarea 中间偏上 (因为 textarea 顶部有 padding).

**方案 B**: 让按钮绝对定位 / sticky 到 textarea 底部 (类似 Apple Messages)

**方案 C** (推荐): 按钮**始终贴底部**, 通过让 textarea `minH={56}` (足够容纳按钮高度), 按钮 `alignSelf="flex-end"` 始终在底部.

**方案 D**: 让 textarea 永远只有 1 行 + 一个独立的发送按钮行 (在下面). 类似旧版的 "输入 + 按钮" 结构但输入框更高更优雅.

**推荐方案 D**:
```tsx
<VStack spacing={3} bg="surface.sunken" borderRadius="xl" border="1px" borderColor="surface.border" p={3}>
  <Textarea
    placeholder="..."
    value={question}
    onChange={...}
    border="none"
    _focus={{ boxShadow: 'none' }}
    resize="none"
    minH="48px"
    maxH="200px"
    overflowY="auto"
    css={{ scrollbarWidth: 'none', '&::-webkit-scrollbar': { display: 'none' } }}
  />
  <Flex justify="space-between" align="center" w="full">
    <Text fontSize="xs" color="gray.400">Enter 发送 · Shift+Enter 换行</Text>
    <Button colorScheme="brand" size="md" leftIcon={<ArrowUpIcon />} onClick={handleSend} isDisabled={!question.trim()}>
      发送
    </Button>
  </Flex>
</VStack>
```

这样:
- Textarea 在上, 自然高度 (min 48, max 200, 隐藏滚动条)
- 按钮行在下, 左侧提示 + 右侧按钮, 始终对齐 baseline
- iPhone Pro Max / iPhone SE / iPad / Desktop 全部自然适配

## 验证标准 (主协调会跑)

### 视觉验证 (手机端, 多档)

```bash
# 主协调会跑这些视口:
- iPhone SE (375x667)
- iPhone 14 Pro (393x852)
- iPhone 14 Pro Max (430x932)  ← 用户特别关注
- iPad (768x1024)
- Desktop (1280x800)
```

**期望**:
- ✅ 输入框 2 行内: 按钮始终贴底部, 垂直居中
- ✅ 输入框 5+ 行: 按钮始终在底部, 不变形
- ✅ Textarea 无滚动条 (无论内容多长)
- ✅ 引用默认折叠 (只显示 "引用 (3) ▸" 按钮)

### 功能验证

- ✅ 发送按钮可点 (无错位)
- ✅ 引用折叠后, 答案完全可见 (不被引用列表遮挡)
- ✅ 点引用按钮展开后, 引用列表可滚动查看每个引用

## 不准做

- ❌ 不改 Tab 结构
- ❌ 不改 theme.ts (除非修阴影微调)
- ❌ 不改路由
- ❌ 不改后端

## 完成后

```bash
cd web && npm run build  # 必须 0 错误
git add -A
git commit -m "fix(ui): 隐藏 Textarea 滚动条 + 引用默认折叠 + Pro Max 按钮对齐"
```

报告:
- 改的文件
- build 输出
- 在 Pro Max 视口截图过吗?

## 主协调验收

主协调 (Hermes) 会:
1. 跑 build (0 错误)
2. 跑多视口截图 (iPhone SE / 14 / 14 Pro / Pro Max + iPad + Desktop)
3. 发一个真问答 (用真 KB), 看引用是否折叠
4. 不通过 → 重派 / 通过 → 推 Pi + 验收

START NOW.