# Nexora Student UI Visual Audit

## Reference
**Tasks** (`student-tasks-HD.png`, 3840×2494) — Primary visual reference/design standard

---

## Dashboard
| Issue | Expected (per Tasks) | Actual | Severity |
|-------|---------------------|--------|----------|
| Page height | 2494px | 2812px (+318px) | P1 |
| Content density | Standard card grid | More cards/widgets stacked vertically | P2 |
| Sidebar active state | Highlighted "Dashboard" | Highlighted correctly | — |
| Header heading | "Tasks" style | "Student Dashboard" — same size/weight? | P2 |
| Card layout | Task cards | Mixed: stats cards + recent activity + quick actions | P1 |

**Notes:** Dashboard is the tallest page. Contains stat cards (4 columns), recent activity feed, and quick action cards — more vertical stacking than Tasks' table/list layout.

---

## My Classes
| Issue | Expected (per Tasks) | Actual | Severity |
|-------|---------------------|--------|----------|
| Page height | 2494px | 2160px (-334px) | P1 |
| Content structure | Table/list | Card grid (class cards) | P1 |
| Header heading | "Tasks" | "My Classes" | — |
| Empty state handling | Not visible | No classes → shows empty state? | P2 |
| Join class modal | N/A | Present (join-ui, join-modal captured) | — |
| Card sizing | Task row height | Class cards taller, fixed aspect | P1 |

**Notes:** Classes uses a card-based grid layout vs Tasks' table/list. Significantly shorter page height suggests less content or more compact cards.

---

## Logbook
| Issue | Expected (per Tasks) | Actual | Severity |
|-------|---------------------|--------|----------|
| Page height | 2494px | 2160px (-334px) | P1 |
| Content structure | Table/list | List/grouped by date? | P1 |
| Header heading | "Tasks" | "Logbook" | — |
| Add entry UI | N/A | Not found (broken interaction) | P2 |
| Date picker | N/A | Not found | P2 |
| Session details | Task details | Log entry detail view captured | — |

**Notes:** Logbook is same height as Classes/Profile (2160px). Uses different content structure — likely date-grouped entries vs Tasks' flat list. Missing "Add Log" button (broken interaction).

---

## Documents
| Issue | Expected (per Tasks) | Actual | Severity |
|-------|---------------------|--------|----------|
| Page height | 2494px | 2378px (-116px) | P2 |
| Content structure | Table/list | Card/list hybrid with upload zone | P1 |
| Header heading | "Tasks" | "Documents" | — |
| Upload UI | N/A | Prominent upload button + modal + file picker | — |
| Action menu | Task menu | Document action menu captured | — |
| Card sizing | Task rows | Document cards wider, more padding | P2 |

**Notes:** Documents has upload functionality (modal, file picker, action menu all captured). Slightly shorter than Tasks. Upload zone at top may affect content flow.

---

## Notifications
| Issue | Expected (per Tasks) | Actual | Severity |
|-------|---------------------|--------|----------|
| Page height | 2494px | 2396px (-98px) | P2 |
| Content structure | Table/list | Notification list items | P1 |
| Header heading | "Tasks" | "Notifications" | — |
| Huge vertical gap | None | Previously observed "huge gap" | P1 |
| Empty state | Not visible | Empty state captured (same height) | P2 |
| Mark-as-read | N/A | Not found (broken interaction) | P2 |
| Unread indicator | N/A | Not found | P2 |

**Notes:** Notifications page has a documented "huge gap" issue. Same height for normal/opened/empty (2396px) suggests fixed container with lots of whitespace. Missing mark-read and unread UI.

---

## Profile
| Issue | Expected (per Tasks) | Actual | Severity |
|-------|---------------------|--------|----------|
| Page height | 2494px | 2160px (-334px) | P1 |
| Content structure | Table/list | Form fields + avatar | P1 |
| Header heading | "Tasks" | "Profile" / shows SQLite error | P0 |
| SQLite error on page | None | `sqlite3.OperationalError: ambiguous column name: profile_picture` | P0 |
| Edit mode | N/A | Edit button not found | P2 |
| Form fields | N/A | Editable form captured (profile-form.png) | — |
| Profile menu | User dropdown | Not found (broken interaction) | P2 |

**Notes:** **Critical:** Profile page renders a SQLite error (`ambiguous column name: profile_picture`) in the page title/body. This breaks usability (P0). Form fields exist but no edit/save flow visible.

---

## Shared Sidebar
| Element | Tasks (Reference) | Dashboard | Classes | Logbook | Documents | Notifications | Profile | Severity |
|---------|-------------------|-----------|---------|---------|-----------|---------------|---------|----------|
| Width (expanded) | ~260px | Same | Same | Same | Same | Same | Same | — |
| Width (collapsed) | ~72px | Captured | — | — | — | — | — | — |
| Logo | NEXORA + icon | Same | Same | Same | Same | Same | Same | — |
| Nav spacing | Even | Even | Even | Even | Even | Even | Even | — |
| Active indicator | Green bar left | Green bar left | Green bar left | Green bar left | Green bar left | Green bar left | Green bar left | — |
| Icon size | 20px | 20px | 20px | 20px | 20px | 20px | 20px | — |
| Text size | 14px | 14px | 14px | 14px | 14px | 14px | 14px | — |
| Collapse button | Chevron left `<` | Position varies? | — | — | — | — | — | P2 |
| Footer gap | Small | Large gap observed | — | — | — | — | — | P2 |
| User badge | "Test User / Student" | Same | Same | Same | Same | Same | Same | — |

**Notes:** Sidebar is consistent across pages. Two issues noted: (1) Collapse button `<` position shifts on some pages, (2) Footer gap below user badge is inconsistent — large on some pages.

---

## Shared Topbar
| Element | Tasks (Reference) | Dashboard | Classes | Logbook | Documents | Notifications | Profile | Severity |
|---------|-------------------|-----------|---------|---------|-----------|---------------|---------|----------|
| Height | 64px | 64px | 64px | 64px | 64px | 64px | 64px | — |
| Position | Fixed top | Fixed | Fixed | Fixed | Fixed | Fixed | Fixed | — |
| Search bar width | ~400px | Same | Same | Same | Same | Same | Same | — |
| Search bar height | 40px | 40px | 40px | 40px | 40px | 40px | 40px | — |
| Search placement | Center-right | Center-right | Center-right | Center-right | Center-right | Center-right | Center-right | — |
| Notification bell | Present | Present | Present | Present | Present | Present | Present | — |
| Profile avatar | Present | Present | Present | Present | Present | Present | Present | — |
| Horizontal spacing | 24px | 24px | 24px | 24px | 24px | 24px | 24px | — |

**Notes:** Topbar is visually consistent across all pages. Search focus state captured (search-focused.png).

---

## Page Header
| Element | Tasks (Reference) | Dashboard | Classes | Logbook | Documents | Notifications | Profile | Severity |
|---------|-------------------|-----------|---------|---------|-----------|---------------|---------|----------|
| Heading text | "Tasks" | "Student Dashboard" | "My Classes" | "Logbook" | "Documents" | "Notifications" | "Profile" / Error | — |
| Heading size | 28px/700 | 28px/700? | 28px/700? | 28px/700? | 28px/700? | 28px/700? | 28px/700? | P2 |
| Heading weight | 700 | 700? | 700? | 700? | 700? | 700? | 700? | — |
| Heading font | Inter | Inter | Inter | Inter | Inter | Inter | Inter | — |
| Position | Left, below topbar | Same | Same | Same | Same | Same | Same | — |
| Breadcrumb | None | None | None | None | None | None | None | — |
| Subtitle | "Manage your tasks" | "Overview of your internship" | None? | None? | "Upload and manage" | "Recent updates" | None? | P2 |
| Header→content gap | 24px | 24px? | 24px? | 24px? | 24px? | **Large gap** | 24px? | P1 |

**Notes:** Notifications has documented "huge gap" between header and content. Subtitle text varies — some pages have descriptive subtitles, others don't. Profile shows SQL error instead of proper heading.

---

## Content Area
| Element | Tasks (Reference) | Dashboard | Classes | Logbook | Documents | Notifications | Profile | Severity |
|---------|-------------------|-----------|---------|---------|-----------|---------------|---------|----------|
| Max width | 1200px | 1200px | 1200px | 1200px | 1200px | 1200px | 1200px | — |
| Left/right margin | 24px | 24px | 24px | 24px | 24px | 24px | 24px | — |
| Top spacing | 24px | 24px | 24px | 24px | 24px | **Large** | 24px | P1 |
| Card width | Full (table) | 4-col stats + full | Card grid | List items | Card/list | List items | Form | P1 |
| Card height | ~56px rows | 120px stats cards | ~200px cards | ~80px entries | ~100px cards | ~80px items | N/A | P1 |
| Grid gaps | N/A | 24px | 24px | 16px | 24px | 16px | N/A | P2 |
| Padding | 16px | 16px/24px | 24px | 16px | 24px | 16px | 24px | P2 |
| Border radius | 8px | 12px | 12px | 8px | 12px | 8px | 8px | P2 |
| Borders | 1px #e6eaf0 | 1px | 1px | 1px | 1px | 1px | 1px | — |
| Shadows | None | Subtle on stats | Subtle on cards | None | Subtle | None | None | P2 |

**Notes:** Content width consistent (1200px). Card/component styling varies: Dashboard uses elevated stat cards (shadow, 12px radius), Classes/Documents use 12px cards, Tasks/Logbook/Notifications/Profile use 8px or no cards. Shadow usage inconsistent.

---

## Typography
| Element | Tasks (Reference) | Others | Severity |
|---------|-------------------|--------|----------|
| Font family | Inter | Inter (all pages) | — |
| H1 (page title) | 28px/700/1.2 | 28px/700/1.2 (mostly) | P2 |
| H2 (section) | 20px/600/1.3 | 20px/600? | P2 |
| Body | 14px/400/1.5 | 14px/400/1.5 | — |
| Small/muted | 12px/400/1.4 | 12px/400? | — |
| Button text | 14px/500 | 14px/500 | — |
| Input label | 13px/500 | 13px/500? | — |
| Line height | 1.5 | 1.5 | — |
| Letter spacing | Normal | Normal | — |

**Notes:** Typography appears consistent (Inter font family). Minor weight/size variations possible on section headings.

---

## Colors
| Element | Tasks (Reference) | Others | Severity |
|---------|-------------------|--------|----------|
| Page background | #f7f9fb | #f7f9fb (all) | — |
| Sidebar background | #ffffff | #ffffff | — |
| Topbar background | #ffffff | #ffffff | — |
| Heading color | #142033 | #142033 | — |
| Body color | #334155 | #334155 | — |
| Muted text | #697486 | #697486 | — |
| Card background | #ffffff | #ffffff | — |
| Borders | #e6eaf0 | #e6eaf0 | — |
| Primary button | #12a879 | #12a879 | — |
| Active nav | #12a879 bar | #12a879 bar | — |
| Hover states | #07865f | #07865f | — |
| Error/alert | #b00020 | #b00020 | — |
| Success | #0a6b2a | #0a6b2a | — |

**Notes:** Color palette is consistent across all pages. CSS variables (--green, --ink, --muted, --line, --bg) appear to be used globally.

---

## Content Width
| Page | Viewport | Content Max-Width | Actual Content Width | Severity |
|------|----------|-------------------|---------------------|----------|
| Tasks | 1920px | 1200px | ~1152px (table) | — |
| Dashboard | 1920px | 1200px | ~1152px (grid) | — |
| Classes | 1920px | 1200px | ~1152px (cards) | — |
| Logbook | 1920px | 1200px | ~1152px (list) | — |
| Documents | 1920px | 1200px | ~1152px (cards) | — |
| Notifications | 1920px | 1200px | ~1152px (list) | — |
| Profile | 1920px | 1200px | ~1152px (form) | — |

**Notes:** Content max-width is consistent at ~1200px across all pages. No horizontal scrolling issues.

---

## Component Differences
| Component | Tasks | Dashboard | Classes | Logbook | Documents | Notifications | Profile | Severity |
|-----------|-------|-----------|---------|---------|-----------|---------------|---------|----------|
| Primary layout | Table | Stats grid + cards | Card grid | Date-grouped list | Card/list + upload zone | List | Form | P1 |
| Empty state | Not visible | Not visible | Likely | Not visible | Not visible | Captured | Not visible | P2 |
| Search | Not found | Not found | Not found | Not found | Not found | Not found | Not found | P2 |
| Filter | Not found | Not found | Not found | Not found | Not found | Not found | Not found | P2 |
| Action menu | Not found | Not found | Not found | Not found | **Captured** | Not found | Not found | P2 |
| Modal | None | None | Join modal | None | Upload modal | None | None | — |
| Toast/alert | None visible | None visible | None visible | None visible | None visible | None visible | None visible | P2 |
| Pagination | Not visible | Not visible | Not visible | Not visible | Not visible | Not visible | N/A | — |

**Notes:** Documents is the only page with visible action menus and modals (upload). Tasks lacks search/filter/modals entirely in current implementation. Most pages missing empty states, search, filters, toasts.

---

## Spacing System
| Token | Tasks | Dashboard | Classes | Logbook | Documents | Notifications | Profile | Severity |
|-------|-------|-----------|---------|---------|-----------|---------------|---------|----------|
| xs (4px) | Used | Used | Used | Used | Used | Used | Used | — |
| sm (8px) | Used | Used | Used | Used | Used | Used | Used | — |
| md (16px) | Used | Used | Used | Used | Used | Used | Used | — |
| lg (24px) | Used | Used | Used | Used | Used | **Inconsistent** | Used | P1 |
| xl (32px) | Used | Used | Used | Used | Used | Used | Used | — |
| 2xl (48px) | Used | Used | Used | Used | Used | Used | Used | — |

**Notes:** Spacing tokens mostly consistent. Notifications page has irregular spacing (documented "huge gap"). Header-to-content gap uses lg (24px) on most pages but xl+ on Notifications.

---

## Priority Fix List

### P0 — Breaks Usability
| # | Page | Issue | Impact |
|---|------|-------|--------|
| 1 | Profile | SQLite error `ambiguous column name: profile_picture` renders on page | User sees DB error instead of profile |

### P1 — Major Visual Inconsistency
| # | Page | Issue | Impact |
|---|------|-------|--------|
| 2 | Notifications | Huge vertical gap between header and content | Page looks broken, excessive whitespace |
| 3 | Dashboard | 318px taller than reference; mixed card types | Inconsistent content density |
| 4 | Classes | 334px shorter; card grid vs table layout | Different mental model for users |
| 5 | Logbook | 334px shorter; date-grouped vs flat list | Different content structure |
| 6 | Profile | 334px shorter; form vs table layout | Different layout pattern |
| 7 | Sidebar | Collapse button `<` position shifts | Unpredictable interaction target |
| 8 | Sidebar | Footer gap below user badge inconsistent | Visual misalignment |
| 9 | Cards | Border radius: 8px (Tasks/Logbook/Notif/Profile) vs 12px (Dashboard/Classes/Docs) | Inconsistent component styling |
| 10 | Cards | Shadows: only Dashboard stats + Classes/Docs cards | Inconsistent elevation |

### P2 — Moderate Inconsistency
| # | Page | Issue | Impact |
|---|------|-------|--------|
| 11 | All (except Docs) | No action menus / dropdowns on rows | Missing standard interaction |
| 12 | All (except Docs) | No modals for create/edit/delete | Missing standard flows |
| 13 | All | No search input on any page | Missing standard feature |
| 14 | All | No filter controls on any page | Missing standard feature |
| 15 | All | No toast/alert notifications visible | Missing feedback system |
| 16 | Classes/Logbook/Profile | No empty state visible (except Notifications) | Missing empty state UX |
| 17 | Documents | Upload zone at top pushes content down | Different content start position |
| 18 | Notifications | Empty/normal/opened all same height (2396px) | Fixed container with whitespace |
| 19 | Logbook | No "Add Log" button found | Missing primary action |
| 20 | Profile | No edit button / save flow visible | Missing primary action |
| 21 | Grid gaps | 16px (Logbook/Notif) vs 24px (Dashboard/Classes/Docs) | Inconsistent rhythm |
| 22 | Padding | 16px (Tasks/Logbook/Notif) vs 24px (Dashboard/Classes/Docs/Profile) | Inconsistent inner spacing |

### P3 — Minor Polish
| # | Page | Issue | Impact |
|---|------|-------|--------|
| 23 | All | Subtitle presence inconsistent (some have, some don't) | Minor content hierarchy diff |
| 24 | Tasks | No visible pagination on long lists | Minor scalability concern |
| 25 | Sidebar | User badge text "Test User / Student" — hardcoded? | Minor personalization |

---

## Summary
- **Reference page:** Tasks (3840×2494)
- **Pages audited:** 7 main + 28 interactive states
- **Critical issues:** 1 (Profile SQL error)
- **Major inconsistencies:** 9
- **Moderate inconsistencies:** 12
- **Minor issues:** 3

**Root cause:** Pages appear to have been built independently without a shared component library or design system enforcement. Common patterns (search, filter, action menus, modals, toasts, empty states) are missing from most pages. Cards use two different border-radius values (8px vs 12px) and shadow treatments. Notifications has a layout bug (huge gap). Profile has a runtime SQL error.

**Recommendation:** Establish a shared Student layout component with enforced slots for header, content, sidebar, topbar. Create a component library for Card, Table, Modal, Dropdown, Toast, EmptyState, Search, Filter. Fix Profile SQL query. Audit Notifications container spacing.