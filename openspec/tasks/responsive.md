# Task Spec: Responsive Redesign

> **Status**: Dispatching to Kimi (frontend agent)  
> **Created**: 2026-07-19  
> **Dispatcher**: Hermes-M3 (project coordinator)

## Goal
Make `youfu-known` SPA fully responsive across mobile / tablet / desktop.

## Tech Stack
- Vite + React 18 + TypeScript + Chakra UI 2.10
- react-router-dom 6.x
- **No new dependencies** — use Chakra built-ins only

## Three Breakpoints
| Breakpoint | Width | Device |
|---|---|---|
| `base` | 0–767px | Mobile (portrait) |
| `md` | 768–1023px | Tablet / Mobile (landscape) |
| `lg`+ | 1024px+ | Desktop |

## Current State
- 13 source files, 1373 lines, **zero responsive keywords** (`grep "base=|md=|lg=" web/src/` returns nothing)
- All widths hardcoded (e.g. `w="280px"`, `maxW="960px"`)
- Chakra is already installed — just not used responsively

## Per-Component Spec

### 1. `KnowledgeBaseSidebar.tsx` — the critical one
- **Desktop (lg+)**: fixed at left, `w="280px"`, unchanged
- **Tablet (md)**: fixed at left, `w="240px"`, slightly compressed
- **Mobile (base)**: **drawer mode** — hidden by default, hamburger button in top bar opens it (Chakra `Drawer`, placement="left", size="xs")
- After KB click on mobile → **auto-close drawer** + navigate (don't waste screen real estate)
- Hamburger button only on mobile (use `useBreakpointValue`)

### 2. `App.tsx` — root layout
- Wrap in Flex with `direction={{ base: "column", lg: "row" }}`
- On mobile: top bar with hamburger; below: main area
- On desktop: sidebar at left + main area (current)
- Add `minH="100vh"` to ensure full height

### 3. `KBMainArea.tsx`
- Container `maxW="960px"` stays, but `px={{ base: 3, md: 5 }}` for side padding
- Heading `size={{ base: "md", md: "lg" }}`

### 4. `DocumentList.tsx` — table OR cards
- **Desktop / Tablet**: 5-column table (filename / size / status / chunks / actions), wrap in `Box overflowX="auto"` for narrow viewports
- **Mobile**: **switch to card list** using `useBreakpointValue`:
  ```
  ┌──────────────────────────┐
  │ filename.docx        [×] │
  │ 大小: 50.9 KB             │
  │ 状态: [就绪]   chunks: 502 │
  └──────────────────────────┘
  ```
  Action buttons (refresh/delete) on Card's top-right corner
- Each Card `mb={2}`, full width, `p={3}`, border + borderRadius
- **Touch target >= 44px** for all buttons

### 5. `ChatPanel.tsx`
- History area `maxH={{ base: "50vh", md: "420px" }}` — give mobile more room
- Input + button row: `direction={{ base: "column", md: "row" }}` (stacked on mobile)
- On mobile, send button full width below input
- Float-to-bottom button: smaller on mobile

### 6. `Uploader.tsx`
- Already mostly responsive. Verify icon + text + button stack vertically on mobile (`<VStack>` is fine)
- Drop zone padding `p={{ base: 4, md: 5 }}`

### 7. `CitationPanel.tsx`
- Citation item header flex wraps gracefully
- `flexWrap="wrap"` on the row with score, file name

### 8. `NewKnowledgeBaseButton.tsx` & `EmptyState.tsx`
- Modal: ensure `isFullScreen` on base, `size="md"` on md+
- EmptyState: reduce icon size on mobile

## Implementation Rules (READ CAREFULLY)

### Use Chakra's responsive prop syntax:
```tsx
<Box p={{ base: 2, md: 4, lg: 6 }} />
<Heading size={{ base: "md", md: "lg" }} />
<Button display={{ base: "block", md: "none" }} />
```

### For conditional rendering based on breakpoint:
```tsx
const isMobile = useBreakpointValue({ base: true, md: false });
{isMobile ? <MobileCard /> : <DesktopTable />}
```

### Drawer pattern for mobile sidebar:
```tsx
<Drawer isOpen={isOpen} onClose={onClose} placement="left" size="xs">
  <DrawerOverlay />
  <DrawerContent>
    <DrawerCloseButton />
    <DrawerBody>{sidebarContent}</DrawerBody>
  </DrawerContent>
</Drawer>
```

## DO NOT MODIFY
- `api.ts` (backend contract)
- `types.ts` (TypeScript types)
- `main.tsx` (entry point)
- `theme.ts` (brand colors / fonts)
- `package.json` (no new dependencies)
- React Router structure

## CRITICAL Constraints

1. **Desktop (lg+) MUST look 100% identical** — don't break existing users
2. **Touch targets >= 44px** on mobile (Apple HIG / Material guideline)
3. **No horizontal scroll on body** (only inside scrollable containers)
4. **All interactive features must work on mobile** (KB switch, upload, delete, chat)
5. **KB click on mobile = close drawer + navigate** (don't leave drawer open)

## Files to Modify (9 total)
```
src/App.tsx
src/components/KnowledgeBaseSidebar.tsx
src/components/KBMainArea.tsx
src/components/Uploader.tsx
src/components/DocumentList.tsx
src/components/ChatPanel.tsx
src/components/CitationPanel.tsx
src/components/NewKnowledgeBaseButton.tsx
src/components/EmptyState.tsx
```

You may add new helper components in `src/components/` (e.g. `MobileDocCard.tsx`) but prefer to extend existing files when possible.

## Acceptance Criteria (coordinator will verify)

```bash
cd web && npm run build
# Must pass with zero errors
```

Then I will:
1. Spin up Chromium headless
2. Screenshot 3 viewports: 390x844 (iPhone 14), 768x1024 (iPad), 1280x800
3. Visually inspect:
   - Mobile: sidebar is drawer; documents are cards; chat input stacks on button
   - Tablet: sidebar visible but narrower; table still works
   - Desktop: pixel-identical to current
4. Test interactions on mobile:
   - Hamburger → drawer slides in
   - Click KB → drawer closes, main shows
   - Upload file → progress visible
   - Delete KB → confirmation modal fullscreen

If your changes break any of the above, I'll re-dispatch the fix to you.

## Worktree
Work in a feature branch:
```bash
cd /home/youfu/projects/youfu-known
git worktree add .worktrees/responsive -b feature/responsive
cd .worktrees/responsive
# ... your changes
git add -A && git commit -m "feat: responsive redesign"
```

I'll merge when verified.

## Timeline
- Estimate: 1-2 iteration cycles
- If first attempt is good → merge + deploy
- If visual regressions → I dispatch fix tasks back to you with specific screenshots
