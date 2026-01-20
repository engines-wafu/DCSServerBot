# Claude Code Instructions for DCSServerBot

This file contains instructions for Claude Code when working on this repository. This file is local-only (.gitignore) to preserve context across conversation compaction.

## Server Access

The DCSServerBot production server is accessible via SSH. **Always connect directly to perform server-side actions rather than asking the user to do it.**

### SSH Connection Details

```
Host: hoverstop
IP: 192.154.225.181
User: Administrator
Platform: Windows Server 2025
```

Connect using:
```bash
ssh hoverstop "command here"
```

### Server Directory Structure

```
C:\Users\Administrator\github\DCSServerBot\     # Main bot installation
C:\Users\Administrator\github\DCSServerBot\config\plugins\  # Plugin configs
C:\Users\Administrator\.dcssb\                  # Python venv
C:\Users\Administrator\Saved Games\             # DCS saved games
```

### Common Server Tasks

**Pull latest code:**
```bash
ssh hoverstop "cd C:\Users\Administrator\github\DCSServerBot && git pull origin feat/flight_plan"
```

**Check if bot is running:**
```bash
ssh hoverstop "tasklist | findstr python"
```

**Restart bot (requires user to restart from RDP or run start_bot.bat):**
Bot runs as process, not service. User must restart manually via RDP.
Start script: `C:\Users\Administrator\github\DCSServerBot\start_bot.bat`

**View plugin config:**
```bash
ssh hoverstop "type C:\Users\Administrator\github\DCSServerBot\config\plugins\flightplan.yaml"
```

**Create/edit config file:**
```bash
ssh hoverstop "echo key: value > C:\Users\Administrator\github\DCSServerBot\config\plugins\plugin.yaml"
```

**View logs:**
```bash
ssh hoverstop "type C:\Users\Administrator\github\DCSServerBot\logs\dcssb.log"
```

---

## Development Workflow

1. Make changes locally on the `feat/flight_plan` branch (or appropriate feature branch)
2. Commit and push to the `fork` remote (engines-wafu/DCSServerBot)
3. SSH to server and pull the changes
4. Restart the bot service if needed
5. Test in Discord/DCS

### Git Remotes

**Local machine:**
- `origin` - Special-K-s-Flightsim-Bots/DCSServerBot (upstream, read-only)
- `fork` - engines-wafu/DCSServerBot (our fork, push here)

**Server (hoverstop):**
- `origin` - engines-wafu/DCSServerBot (our fork)
- `upstream` - Special-K-s-Flightsim-Bots/DCSServerBot (upstream)

**Note:** Remote names differ! On local, push to `fork`. On server, pull from `origin`.

---

## Project Structure

- `plugins/` - Bot plugins (commands, listeners, Lua scripts)
- `core/` - Core bot functionality
- `services/` - Background services
- `extensions/` - Optional extensions (SRS, TacView, etc.)
- `config/` - Configuration files
- `reports/` - Report templates

### Plugin Development

Each plugin typically contains:
- `__init__.py` - Plugin initialization
- `commands.py` - Discord slash commands
- `listener.py` - Event handlers and chat commands
- `db/tables.sql` - Database schema
- `lua/commands.lua` - Python-to-DCS bridge
- `lua/mission.lua` - Mission environment scripts

---

## Discord Test Server

| Item | Value |
|------|-------|
| **Server Name** | Hover Stop Staging |
| **Guild ID** | 1461528993516748980 |
| **Default Channel ID** | 1461528994708062363 |

---

# Current Work: Flight Plan Plugin

**Branch:** `feat/flight_plan`
**Status:** In development

## Overview

New standalone `flightplan` plugin (not part of logbook) providing IFR-style flight planning with:
- File flight plans with waypoints, altitude, timing
- F10 map visualization (cyan markers, distinct from logistics yellow)
- F10 menu for in-game operations
- Discord publishing for visibility
- In-game chat commands
- OpenAIP API integration for navigation fixes
- Auto-cancel stale plans

## OpenAIP Configuration

API Key configured in `config/plugins/flightplan.yaml`:
```yaml
DEFAULT:
  openaip:
    api_key: 00dd1cf7f2956902a9c4f021c89fe335
```

**Note:** All plugin configs require `DEFAULT:` as the top-level key.

Sync fixes with `/flightplan fix sync <theater>`.

## Commands Implemented

### Discord Slash Commands
- `/flightplan file` - File a flight plan (departure/destination autocomplete airbases)
- `/flightplan view` - View a flight plan
- `/flightplan list` - List flight plans
- `/flightplan activate` - Activate a filed plan (creates F10 markers)
- `/flightplan complete` - Mark plan completed
- `/flightplan cancel` - Cancel a plan
- `/flightplan plot` - Temporary F10 plot (30s default)
- `/flightplan publish` - Post to Discord channel
- `/flightplan stale` - Admin: cancel stale plans
- `/flightplan waypoint add/list/delete` - User-defined waypoints
- `/flightplan fix list/add/delete/sync/count` - Navigation fixes

### In-Game Chat Commands
- `-flightplan` or `-fp` - Show your active flight plan
- `-plotfp [plan_id]` - Plot flight plan on F10 map (30s)
- `-fileplan <DEP> <DEST> [aircraft]` - Quick file from in-game
- `-activatefp` - Activate your filed plan
- `-completefp` - Complete your active plan
- `-cancelfp` - Cancel your plan

### F10 Menu Options
- View Active Plans
- My Flight Plan
- Plot All Plans (30s)
- Plot Plan (by ID submenu)
- Activate Plan (for filed plans)
- Complete Flight (for active plans)
- Cancel Flight (for active plans)

## Database Tables

- `flightplan_plans` - Main flight plans
- `flightplan_waypoints` - User-defined waypoints
- `flightplan_navigation_fixes` - VORs, NDBs, TACANs, waypoints
- `flightplan_markers` - F10 marker tracking

## Key Features

### Waypoint Autocomplete
- Corridor-based: shows fixes within 50nm of direct route between departure and destination
- Falls back to all theater fixes when departure/destination not selected

### Altitude Parsing
- Accepts FL300 or 30000 format

### ETD Parsing
- Accepts 14:30 or 1430 format

### Theater Bounding Boxes
Defined for all 11 DCS theaters for OpenAIP sync:
- Afghanistan, Caucasus, Kola, Mariana Islands, Nevada, Normandy
- Persian Gulf, Sinai, South Atlantic, Syria, The Channel

## Seed Data

`plugins/flightplan/db/seed_navigation_fixes.sql` includes:
- Caucasus: VORs, NDBs, RNAV waypoints from Furia's template
- Syria: Major airports and Cyprus
- Persian Gulf: UAE, Iran, Oman
- Afghanistan: Major VORs, G202 airway (NABID, DOLAN), Camp Bastion region

## Verification Checklist

1. [ ] `/flightplan file` with waypoints, altitude, ETD - plan created in DB
2. [ ] `/flightplan activate` - F10 markers appear (cyan), Discord embed posted
3. [ ] `-plotfp` in-game - temporary markers for 30s
4. [ ] `/flightplan complete` - markers removed, Discord updated
5. [ ] F10 menu: View Plans, My Plan, Plot All, Plot by ID
6. [ ] F10 menu: Activate, Complete, Cancel
7. [ ] Stale plan auto-cancelled on mission start
8. [ ] Waypoint autocomplete shows fixes in corridor
9. [ ] `/flightplan fix sync Afghanistan` pulls from OpenAIP

---

# Logistics Plugin Status

**Status:** In Beta Testing
**PRs:** #97, #99, #100, #102 merged to upstream development

## Bugs Fixed During Beta Testing

1. **Detached HEAD crash** - Added try/except TypeError in nodeimpl.py
2. **Coalition type mismatch** - Changed `player.coalition` to `player.side.value`
3. **Side enum comparison error** - Changed `player.side > 0` to proper enum check
4. **Nil channel Lua error** - Added default channel handling
5. **Markers not disappearing** - Moved timeout from Lua to Python asyncio
6. **Markers on server start** - Only recreate for assigned/in_progress tasks
7. **F10 menu callback handler** - Use `@event(name="logistics")` not "callback"
8. **F10 menu not appearing** - Use `onPlayerChangeSlot` not `onPlayerStart`

## Verification Checklist

1. [x] Create task via Discord → appears in database
2. [x] Approve task → status changes to approved
3. [x] In-game `-tasks` → shows available tasks for coalition
4. [x] Accept via `-accept` → assignment confirmed, markers appear
5. [x] `-plot all` → plots all tasks with 30s timeout
6. [x] `-plot <id>` → plots specific task with 30s timeout
7. [x] F10 map markers show pickup/delivery with route lines
8. [x] F10 map text box shows task details
9. [ ] Land at destination → auto-completion triggers
10. [ ] `/logbook stats` → shows logistics completion
11. [ ] `/warehouse status` → shows correct inventory
12. [ ] F10 menu flow works end-to-end

---

# Logbook Plugin Status

**Status:** MERGED (PR #97)
**Merged:** 2026-01-12 into upstream `development` branch

## Completed Features

- Core Infrastructure - Plugin scaffold, database schema, `/logbook stats`
- Squadron Management - Full CRUD with CO/XO hierarchy
- Qualifications System - With expiration and auto-grant
- Awards System - With ribbon rack image generation
- Flight Plans - Filing and status tracking (now separate plugin)
- Stores Request System - Submit, list, view, approve, deny

### `/logbook pilot` Command
- Service (RN, RAF, AAC)
- Rank (Cdr, Lt, Wg Cdr, etc.)
- Squadron(s) - supports multiple assignments
- Total Hours (including historical)
- Last Joined date
- Qualifications with issue/expiry dates
- Awards with issue dates
- Ribbon rack image

### Database Migrations
- `update_v1.1.sql` - Add `ribbon_image BYTEA` column to awards
- `update_v1.2.sql` - Create `logbook_pilots` table, add `service` to squadrons

---

# Test Environment

### Windows Server
| Item | Value |
|------|-------|
| **Hostname** | server.hoverstop.us |
| **IP Address** | 192.154.225.181 |
| **OS** | Windows Server 2025 Standard |
| **Status** | Active - DCSServerBot running |

### Prerequisites Completed
- [x] SSH server enabled (OpenSSH for Windows)
- [x] SSH key authentication working
- [x] Python 3.11+ installed
- [x] Git installed
- [x] PostgreSQL installed
- [x] DCS World Dedicated Server installed
- [x] DCSServerBot cloned and configured
- [x] DCSServerBot running as service

### Discord Test Server
- [x] Hover Stop Staging server created
- [x] Bot connected and working
- [x] Roles created (DCS Admin, DCS, Logistics Officer)
- [x] Channels created (#bot-commands, #admin-channel, #logs)
