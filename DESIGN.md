# Design System: 青年福利券

## Visual Theme
civic-trust, dense-product, restrained

## Craft stack (open-design)
- `craft/color.md` — neutrals 70–90%、accent ≤10%、对比度门槛
- `craft/typography.md` — 固定 rem 阶、字重三档、ALL CAPS 跟踪
- `craft/anti-ai-slop.md` — 禁 indigo 默认、双色信任渐变、左侧色条卡片
- `craft/state-coverage.md` — loading / empty / error / populated / edge
- `design-templates/dashboard` — 侧栏 + 顶栏 + KPI 分层密度

## Color Palette

| Role | Token | Value | Usage |
|------|-------|-------|-------|
| Background | `--bg` | `#F3F6F8` | App canvas（冷中性，非 cream） |
| Surface | `--surface` | `#FFFFFF` | Cards, panels |
| Surface-2 | `--surface-2` | `#E8EEF2` | Table header, chips, nav hover |
| Surface-3 | `--surface-3` | `#DCE4EA` | Stronger fill |
| Ink | `--ink` | `#15202B` | Primary text |
| Muted | `--muted` | `#5B6B7A` | Secondary text（≥4.5:1 on bg） |
| Brand / Accent | `--brand` / `--accent` | `#0F6E6A` | Primary actions, active nav |
| Brand-hover | `--brand-hover` | `#0C5A57` | Pressed / hover fill |
| Brand-soft | `--brand-soft` | `#D8F0EE` | Soft selected / KPI accent |
| Border | `--border` | `#D0DAE2` | Dividers, cards |
| Success | `--success` | `#1B7F4E` | Approved / redeem OK |
| Warning | `--warning` | `#B45309` | Pending |
| Danger | `--danger` | `#B42318` | Reject / void |
| Focus | `--focus` | teal ring | Focus-visible only |

Accent discipline: 每屏可见 accent ≤ 2 处（如主 CTA + 选中态）。

## Typography
- Family: `"Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif`
- Scale tokens: `--text-xs` 12 / `--text-sm` 13 / `--text-md` 14 / `--text-base` 16 / `--text-lg` 18 / `--text-xl` 22
- Titles 18px weight 600；body 14；table 13；labels letter-spacing +0.01–0.02em
- 禁止 display 流体 clamp 标题

## Spacing & shape
- Base 4px；card padding 16–20px；section gap 16px
- Radius: 8px controls / 12px cards（禁止 24+ 卡片圆角）
- Cards: **边框为主，不用宽软阴影**（craft 禁 border+大阴影叠用）

## Components
- Primary button: brand fill, white text, weight ~550
- Tables: surface-2 header, brand-soft row hover, clear empty
- Tags: Element light + semantic type
- Empty: dashed surface + title + 一句说明 + optional CTA
- Shell: flat dark-teal sidebar (admin/merchant)，用户端浅顶栏

## Layout
- Admin: fixed sidebar 228px（可折叠 72）+ sticky top bar + main scroll
- User: max-width 920 centered
- Merchant: max-width 820 centered
- Mobile: sidebar 强制折叠；内容全宽

## Motion
- 150–180ms state transitions only
- `prefers-reduced-motion: reduce` 全局降级

## Anti-patterns (do not ship)
- Tailwind indigo / 紫→蓝信任渐变
- Apple 蓝 `#007AFF` 体系（见 `trae` 分支，不在 master）
- 左色条 KPI 卡片、emoji 当图标、英雄大数字墙无任务上下文
