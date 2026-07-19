# 响应式适配任务规范 (Kimi 执行)

> 来源: youfu-known 项目主协调派发  
> 创建时间: 2026-07-19  
> 受众: Kimi (前端 Coding Agent)  
> 工作目录: `/home/youfu/projects/youfu-known/web/src/`

## 1. 目标

**当前问题**: SPA 在手机/平板上显示错乱, 主要因为:
- 侧栏固定 `w="280px"`, 占用手机屏幕一大半
- 文档表格列多, 手机上横排溢出
- 上传区/问答区无 max-width, 桌面拉伸过宽
- 弹窗 (新建 KB / 删除确认) 在小屏可能超出视口
- 字体/图标固定大小, 触摸目标可能 < 44px (Apple HIG / Material 建议)

**目标**: 适配 3 个断点, 全平台体验统一:
| 断点 | 宽度 | 设备 |
|---|---|---|
| `base` | 0-767px | 手机 (竖屏) |
| `md`   | 768-1023px | 平板 / 手机 (横屏) |
| `lg`+  | 1024px+ | 桌面 |

## 2. 现有代码状况

- 13 个源文件, 1373 行, Chakra UI v2.10
- **0 个响应式关键字** (`grep "base=|md=|lg=|sm=|xl=" web/src/` 无结果)
- 所有宽度硬编码 (如 `w="280px"`, `maxW="960px"`)
- 用 `react-router-dom` 路由

涉及修改的文件:
```
src/App.tsx                          # 根布局
src/components/KnowledgeBaseSidebar.tsx  # 侧栏 (核心)
src/components/KBMainArea.tsx        # 主区域
src/components/Uploader.tsx
src/components/DocumentList.tsx       # 表格
src/components/ChatPanel.tsx
src/components/CitationPanel.tsx
src/components/NewKnowledgeBaseButton.tsx
src/components/EmptyState.tsx
```

## 3. 关键设计决策 (主协调已定)

### 3.1 侧栏行为
- **桌面 (lg+)**: 固定显示在左侧, `w="280px"`, 不变
- **平板 (md)**: 固定显示, `w="240px"`, 内容压缩
- **手机 (base)**: **抽屉模式** — 默认隐藏, 顶部有汉堡菜单按钮, 点击抽屉式从左侧滑出 (Chakra Drawer 组件, full height, w="280px")
- 选中 KB 后, 手机端**自动关闭**抽屉并跳转 (避免占用屏幕)

### 3.2 文档表格
- **桌面**: 5 列 (文件名 / 大小 / 状态 / chunks / 操作) - 现状
- **平板**: 同样 5 列, 但**列宽自动调整** (用 `<Box minW="0">` + `truncate`)
- **手机**: 改为**卡片列表** (单列, 每文档一张 Card), 字段竖排:
  ```
  ┌────────────────────────┐
  │ 文件名.docx        [×] │
  │ 大小: 50.9 KB        │
  │ 状态: [就绪]   chunks: 502 │
  └────────────────────────┘
  ```
  操作按钮 (刷新/删除) 放 Card 右上角

### 3.3 问答区
- **桌面**: 历史区域 `maxH="420px"`, 输入框右边按钮
- **手机**: 历史区 `maxH="50vh"`, 输入框 + 按钮**堆叠** (按钮在输入框下方, 全宽)

### 3.4 上传区
- 不变 (已经是响应式友好的 — 拖拽区 + 按钮)

### 3.5 弹窗 (新建 KB / 删除确认)
- Chakra `Modal` 组件, 默认 `size="md"`, 小屏自动 fullscreen (`isFullScreen` 在 base 断点)
- 已有 `Modal` 自带响应式 (Chakra 默认行为), 主要确认**没有**自定义 width 写死

### 3.6 字体/触摸目标
- 桌面字体不变
- 移动端: 主按钮/图标按钮 `minH="44px"`, 文字最小 14px
- 表格行/列表项 触摸区 >= 44px

## 4. 实现要点 (Kimi 必读)

### 4.1 Chakra 响应式语法

**响应式属性数组** (推荐):
```tsx
<Box p={{ base: 2, md: 4, lg: 6 }} />
<Heading size={{ base: "md", md: "lg" }} />
```

**useBreakpointValue** (条件渲染):
```tsx
const isMobile = useBreakpointValue({ base: true, md: false });
```

**显示/隐藏**:
```tsx
<Box display={{ base: "block", md: "none" }}>  {/* 只手机 */}
<Box display={{ base: "none", md: "block" }}>  {/* 平板+ */}
```

**Drawer 模式** (手机侧栏):
```tsx
<Drawer isOpen={isOpen} onClose={onClose} placement="left" size="xs">
  <DrawerOverlay />
  <DrawerContent>
    <DrawerCloseButton />
    <DrawerHeader>知识库</DrawerHeader>
    <DrawerBody>{/* 复用 Sidebar 内容 */}</DrawerBody>
  </DrawerContent>
</Drawer>
```

### 4.2 表格响应式 (DocumentList 关键)

Chakra `Table` 在小屏需要 `overflowX="auto"` 包一层 + 表格 `minW="600px"` 强制不缩小; 然后**手机断点用 Card 列表替代表格**:

```tsx
{isMobile ? (
  <VStack>{docs.map(d => <DocCard doc={d} />)}</VStack>
) : (
  <Table>...</Table>
)}
```

### 4.3 不准改的东西

- **不**改 `api.ts` / `types.ts` (后端契约)
- **不**改 `main.tsx` (入口)
- **不**改 `theme.ts` (品牌色/字体保留)
- **不**引入新依赖 (用 Chakra 内置就够了)
- **不**改 SPA 路由结构 (`/kbs/:kbId` 保留)
- **不**重写组件逻辑, 只加响应式 + 结构调整

## 5. 验收标准 (主协调亲自跑)

我 (主协调) 改完会跑:
```bash
cd web && npm run build    # 1) build 不报错
# 2) chromium headless 截图 3 个断点:
#    - base (iPhone 14: 390x844)
#    - md   (iPad:   768x1024)
#    - lg   (1280x800)
# 然后目视检查:
#   - 侧栏在手机上变成抽屉
#   - 文档在手机上变卡片
#   - 问答区在手机上输入框 + 按钮堆叠
#   - 没有横向滚动 / 内容溢出
#   - 字体大小合理
# 3) 用 Playwright 测交互:
#   - 手机断点: 点击汉堡 -> 抽屉滑出 -> 点 KB -> 抽屉关闭
#   - 平板: 侧栏固定, 表格正常
```

**Kimi 不能自验收** — 我会亲自验证。如果 Kimi 报告"完成",我会:
1. 跑 build
2. 跑截图
3. 跑交互测试
4. 不通过就回派 Kimi 修

## 6. 交付物

- 修改的 9 个组件文件
- 任何新建的 helper 组件 (如 `<MobileNavButton>`, `<MobileDocCard>`) 放 `src/components/`
- **不**改 `package.json` (不加新依赖)

## 7. 工作时间预期

- Kimi 用 `worktree` 隔离修改
- 完成后回 main 分支, 我亲自验收
- 预计 1-2 轮迭代 (Kimi 改完可能需根据截图再调整)

## 8. 关键约束

1. **桌面 (lg+) 视觉必须 100% 不变** — 现有用户没反馈桌面有问题, 别动桌面
2. **手机断点必须实测** — 不能写完不截图就说完成
3. **触碰目标 >= 44px** (手机可点)
4. **没横向滚动** (用 overflowX="auto" 控制局部, 不是整个 body)
5. **KB 切换/上传/删除** 三个交互在手机上必须能用

## 9. 主协调保留事项

- 后端 API 契约 (Kimi 改了前端要同步我)
- 部署 (build 完推到 Pi, 走 Cloudflare)
- 性能 (首屏 < 2s, 即使手机 4G)
- 真实数据验证 (用宝子的护理考试 KB 截图)

---

**Kimi 开始任务** — 先建 worktree, 改 App.tsx + KnowledgeBaseSidebar.tsx (核心), 再扩到其他组件。
