# Notion drafts

Markdown drafts for the LiraLab robot documentation in Notion. I do not have
Notion access from here, so these are written to be pasted in: Notion's
Markdown import (`⌘/Ctrl+V` of raw markdown, or Import → Markdown) preserves
headings, tables, toggles-as-lists and code blocks.

| file | becomes |
|---|---|
| `00-landing-page.md` | the shared landing page — one row per robot |
| `widowx.md` | the WidowX setup page, linked from the landing page |

## Proposed Notion structure

The infrastructure doc asks for "a shared landing page where we can select any
robot setup, and access its own documentation page". Concretely:

```
🤖 LiraLab Robot Infrastructure        <- landing page, database view
├── 🦾 WidowX                          <- one page per setup, same template
├── 🦾 Trossen AI
├── 🦾 XArm
├── 🦾 DROID
├── 📐 Shared conventions              <- data format, folder layout, metadata
└── 🛠️ Physical setup                  <- curtains, lights, camera mounts
```

Make the robot pages a **Notion database**, not plain subpages, with properties
`Robot`, `Owners`, `Desktop`, `Status`, `Repo`. That gives the "select any robot
setup" selector the doc asks for, for free, and it stays usable at eight robots.

Every robot page should use the **same section headings** so that someone who
knows one rig can navigate another. Proposed template, which `widowx.md`
follows:

1. At a glance (hardware, desktop, repo, owners)
2. Physical setup / cabling
3. Preflight
4. Data collection
5. Powering off
6. Inference
7. Data processing
8. Troubleshooting
9. Reference

## Before pasting — two things

**Credentials.** The current WidowX Google doc contains the Alienware login
password in plain text. Do not carry that into Notion, and do not put it in
this repo. The drafts here have a placeholder pointing at the lab password
manager / a pinned Slack message instead. **[decide]** where lab credentials
should actually live.

**Screenshots.** The manual's expected-`roslaunch`-output screenshot and the
example camera observation are worth re-capturing and attaching — they are the
fastest way for a new teleoperator to tell "working" from "not working".
Marked `> 📷` in the drafts.
