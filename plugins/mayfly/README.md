# Mayfly Plugin

Aircraft management and MF700 documentation plugin for DCSServerBot. Provides military-style aircraft serviceability
tracking inspired by Royal Navy Fleet Air Arm procedures, including sortie sign-out/sign-in, defect logging (F707),
limitations (F703), deferrals (F704), and optional F-4E persistence file synchronisation.

## Features

- **Fleet Status Board**: Squadron-level aircraft status display with serviceability at a glance
- **Persistent Fleet Channel**: Auto-updating Discord embeds for each squadron, refreshed on every status change
- **Aircraft Cards**: Detailed individual aircraft status including flight history, defects, and limitations
- **Sortie Tracking**: Sign out/sign in workflow with departure/arrival, flight hours, and sortie results
- **Defect Management**: F707-style Serial Number of Work (SNOW) entries with rectification and deferral
- **Limitations Log**: F703-style aircraft limitations tracking
- **Grounding**: Admin grounding and release of aircraft
- **Crash/Eject Detection**: Automatic aircraft status update on DCS crash or ejection events
- **F-4E Persistence Sync**: Client-side DCS hook for automatic `.cache` file synchronisation via REST API

## Requirements

- **userstats plugin** must be enabled (provides the shared `squadrons` table)
- **WebService** must be configured (`config/services/webservice.yaml`) for persistence sync REST endpoints (optional -- Discord commands work without it)

## Installation

1. Add `mayfly` to `opt_plugins` in your `config/main.yaml`:
   ```yaml
   opt_plugins:
     - mayfly
   ```

2. Restart DCSServerBot - the database tables will be created automatically

3. Seed your squadrons using `/logbook squadron create` (Mayfly references the shared `squadrons` table)

4. Register aircraft with `/mayfly add`

## Discord Commands

### Fleet Status (`/mayfly`)

| Command                                | Parameter(s)                                              | Role      | Description                              |
|----------------------------------------|-----------------------------------------------------------|-----------|------------------------------------------|
| `/mayfly board <squadron>`             | `squadron`                                                | DCS       | Display squadron fleet status board      |
| `/mayfly check <squadron> <aircraft>`  | `squadron`, `aircraft`                                    | DCS       | Show detailed aircraft status card       |

### Sortie Management

| Command                                                       | Parameter(s)                                                  | Role      | Description                              |
|---------------------------------------------------------------|---------------------------------------------------------------|-----------|------------------------------------------|
| `/mayfly signout <squadron> <aircraft> [departure]`           | `squadron`, `aircraft`, `departure`                           | DCS       | Sign out an aircraft for a sortie        |
| `/mayfly signin <aircraft> <flight_hours> [arrival] [result]` | `aircraft`, `flight_hours`, `arrival`, `result`               | DCS       | Sign in an aircraft after a sortie       |

### Defect & Limitation Management

| Command                                                | Parameter(s)                                         | Role      | Description                              |
|--------------------------------------------------------|------------------------------------------------------|-----------|------------------------------------------|
| `/mayfly report <squadron> <aircraft> <description>`   | `squadron`, `aircraft`, `description`                | DCS       | Report a defect (F707 SNOW entry)        |
| `/mayfly defects <squadron> <aircraft>`                | `squadron`, `aircraft`                               | DCS       | List open defects for an aircraft        |
| `/mayfly rectify <squadron> <aircraft> <defect>`       | `squadron`, `aircraft`, `defect`                     | DCS       | Rectify (close) a defect                 |
| `/mayfly defer <squadron> <aircraft> <defect> <category>` | `squadron`, `aircraft`, `defect`, `category`      | DCS       | Defer a defect (F704)                    |
| `/mayfly limit <squadron> <aircraft> <description>`    | `squadron`, `aircraft`, `description`                | DCS       | Add a limitation to an aircraft (F703)   |
| `/mayfly unlimit <squadron> <aircraft>`                | `squadron`, `aircraft`                               | DCS       | Remove a limitation from an aircraft     |

### Admin Commands

| Command                                                                                       | Parameter(s)                                                                     | Role      | Description                              |
|-----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|-----------|------------------------------------------|
| `/mayfly ground <squadron> <aircraft> [reason]`                                               | `squadron`, `aircraft`, `reason`                                                 | DCS Admin | Ground an aircraft                       |
| `/mayfly release <squadron> <aircraft>`                                                       | `squadron`, `aircraft`                                                           | DCS Admin | Release aircraft back to serviceable     |
| `/mayfly add <squadron> <tail_number> <aircraft_type> [persistence_key] [livery_id] [notes]`  | `squadron`, `tail_number`, `aircraft_type`, `persistence_key`, `livery_id`, `notes` | DCS Admin | Register a new aircraft               |
| `/mayfly remove <squadron> <aircraft> [reason]`                                               | `squadron`, `aircraft`, `reason`                                                 | DCS Admin | Write off / remove an aircraft           |
| `/mayfly edit <squadron> <aircraft> [tail_number] [aircraft_type] [persistence_key] [livery_id] [notes]` | `squadron`, `aircraft`, and optional fields                           | DCS Admin | Edit aircraft details                    |

## In-Game Events

The Mayfly event listener automatically handles DCS events:

- **Player Spawn**: When a player spawns, they receive a chat message if they have an aircraft signed out
- **Crash / Ejection / Pilot Death**: The signed-out aircraft is marked unserviceable, the flight record is closed with the appropriate result, and the pilot is released

## F-4E Persistence Sync

For aircraft types that support DCS persistence (currently the F-4E Phantom), Mayfly can automatically synchronise
`.cache` files between pilots and the server database via a client-side DCS hook script.

### How It Works

1. **Pre-seed on connect**: When a pilot joins the server, the hook downloads all squadron `.cache` files to their local
   `Saved Games/DCS_F4E/cache/persistent_ac/` folder. This ensures persistence data is available before slotting.
2. **Upload on deslot**: When a pilot leaves their slot (or disconnects), only the specific aircraft they flew is
   uploaded back to the server. This prevents overwriting other pilots' data.
3. **Version history**: Each upload creates a snapshot of the previous data in a history table, providing rollback
   capability equivalent to S3 bucket versioning.

### Client Hook Installation

1. Copy `MayflyCacheSync.lua` to `Saved Games\DCS\Scripts\Hooks\`
2. Launch DCS once - it creates `Saved Games\DCS\Config\MayflyCacheSync.lua`
3. Edit the config file and set `api_base` to your DCSServerBot server address:
   ```lua
   api_base = "http://YOUR_SERVER_IP:9876/mayfly"
   ```
4. Restart DCS - sync is automatic from this point

### REST API Endpoints

The persistence sync uses three endpoints registered directly by the Mayfly plugin:

| Method | Endpoint                      | Description                                      |
|--------|-------------------------------|--------------------------------------------------|
| GET    | `/mayfly/cache`               | List all aircraft with persistence keys and status |
| GET    | `/mayfly/cache/{key}`         | Download a `.cache` file by persistence key      |
| PUT    | `/mayfly/cache/{key}`         | Upload a `.cache` file (max 10MB)                |

### Persistence Key Setup

Each aircraft that supports persistence needs a `persistence_key` matching the `PersistentAircraftKey` property
in the mission `.miz` file. Set this when registering an aircraft:

```
/mayfly add squadron:"892 NAS" tail_number:"XT-859" aircraft_type:"F-4E-45MC" persistence_key:"XT859_001_1"
```

> [!NOTE]
> The persistence key format depends on the mission editor. For the JSW Stanton mission, keys follow the pattern
> `{serial}_{modex}_{counter}` (e.g. `XT859_001_1`). Check your `.miz` file to find the exact keys.

## Persistent Fleet Status Channel

Mayfly can maintain auto-updating fleet status embeds in a dedicated Discord channel. Each squadron gets its own
persistent message that updates automatically when aircraft status changes (signout, signin, crash, defect, etc.).

### Configuration

Add `fleet_channel` to your `config/plugins/mayfly.yaml`:

```yaml
DEFAULT:
  fleet_channel: 123456789    # Discord channel ID for fleet status boards
```

When `fleet_channel` is not set, this feature is disabled. Set the channel to read-only for members so only the
bot can post.

Updates are coalesced -- multiple rapid changes result in a single Discord edit every 30 seconds to avoid rate limiting.

## Database Schema

The plugin creates the following tables:

- `mayfly_aircraft` - Aircraft registry with status, persistence data, and squadron assignment
- `mayfly_flights` - Per-sortie flight log (sign-out/sign-in records)
- `mayfly_defects` - F707 defect entries with SNOW numbering
- `mayfly_limitations` - F703 limitations log
- `mayfly_persistence_history` - Version history for `.cache` file rollback

## Data Model

```
Squadron (from shared userstats schema)
  └── mayfly_aircraft (1:many) - tail number, type, status, persistence data
        ├── mayfly_flights (1:many) - sortie records per aircraft
        ├── mayfly_defects (1:many) - defect entries with SNOW numbering
        ├── mayfly_limitations (1:many) - active/historical limitations
        └── mayfly_persistence_history (1:many) - .cache file version snapshots

Player (from DCSServerBot core)
  └── mayfly_aircraft.current_pilot_ucid - currently signed-out aircraft
  └── mayfly_flights.pilot_ucid - flight records
  └── mayfly_defects.reported_by_ucid / rectified_by_ucid
```

## MF700 Form Reference

| Form  | Purpose                          | Mayfly Equivalent          |
|-------|----------------------------------|----------------------------|
| F700  | Aircraft document set            | `/mayfly check` (overview) |
| F703  | Limitations log                  | `/mayfly limit/unlimit`    |
| F704  | Deferred defect record           | `/mayfly defer`            |
| F707  | Servicing record (SNOW entries)  | `/mayfly report/rectify`   |
