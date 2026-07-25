# Design System: 青年福利券

## Visual Theme
civic-trust, dense-product, restrained

## Color Palette (OKLCH-inspired hex)

| Role | Value | Usage |
|------|-------|-------|
| Background | `#F3F6F8` | App canvas (cool neutral, not cream) |
| Surface | `#FFFFFF` | Cards, panels |
| Surface-2 | `#E8EEF2` | Sidebar, chips, table header |
| Ink | `#15202B` | Primary text |
| Muted | `#5B6B7A` | Secondary text (≥4.5:1 on bg) |
| Brand | `#0F6E6A` | Primary actions, active nav |
| Brand-soft | `#D8F0EE` | Soft highlights |
| Border | `#D0DAE2` | Dividers |
| Success | `#1B7F4E` | Approved / used OK |
| Warning | `#B45309` | Pending |
| Danger | `#B42318` | Reject / void |
| Focus | `#0F6E6A` | Focus rings |

## Typography
- Family: system-ui, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif
- Scale: 12 / 13 / 14 / 16 / 18 / 22 / 28 (rem-fixed)
- Titles 18–22px semibold; body 14px; table 13px

## Spacing
- Base 4px; card padding 16–20px; section gap 16px; radius 10–12px (not 24+)

## Components
- Primary button: brand fill, white text
- Tables: light header, stripe optional, clear empty state
- Tags: semantic colors for status
- Shell: dark-teal sidebar (admin), light top bar (user/merchant)

## Layout
- Admin: fixed sidebar 220px + content
- User/Merchant: max-width 960–880px centered
- Mobile: sidebar collapses conceptually via stack; content full width
