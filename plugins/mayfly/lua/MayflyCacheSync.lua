-- MayflyCacheSync.lua
-- Client-side DCS hook for automatic F-4E persistence file sync.
-- Install: Copy to Saved Games/DCS/Scripts/Hooks/
--
-- On server connect: downloads all squadron .cache files (pre-seed).
-- On deslot/disconnect: uploads only the flown aircraft's .cache file.
--
-- Requires: DCSServerBot with Mayfly plugin running on the server.

local mayflySyncVersion = "0.2"

local lfs       = require('lfs')
local socket    = require('socket')
local net       = net
local DCS       = DCS
local log       = log

-- Configuration
local CONFIG = {
    -- Bot API base URL - set this to your DCSServerBot address and port
    api_base    = "http://YOUR_SERVER_IP:9876/mayfly",
    -- Timeout for HTTP requests in seconds
    timeout     = 10,
    -- Enable debug logging
    debug       = false,
}

-- State
local state = {
    connected       = false,
    current_slot    = nil,       -- slot ID of current aircraft
    current_key     = nil,       -- persistence key of current aircraft
    current_type    = nil,       -- unit type name
    seeded          = false,     -- whether pre-seed has completed
    cache_dir       = nil,       -- resolved path to persistent_ac folder
    my_ucid         = nil,       -- local player UCID
}

local mayflySync = {}

--------------------------------------------------------------------------------
-- Logging
--------------------------------------------------------------------------------

local function logInfo(msg)
    log.write('MayflyCacheSync', log.INFO, msg)
end

local function logDebug(msg)
    if CONFIG.debug then
        log.write('MayflyCacheSync', log.DEBUG, msg)
    end
end

local function logError(msg)
    log.write('MayflyCacheSync', log.ERROR, msg)
end

--------------------------------------------------------------------------------
-- Path resolution
--------------------------------------------------------------------------------

local function getCacheDir()
    if state.cache_dir then return state.cache_dir end

    -- DCS_F4E saves to a sibling folder of the main DCS Saved Games folder.
    -- lfs.writedir() returns e.g. "C:\Users\X\Saved Games\DCS\"
    -- F-4E cache lives at "C:\Users\X\Saved Games\DCS_F4E\cache\persistent_ac\"
    local write_dir = lfs.writedir()
    -- Strip trailing slash and replace "DCS" or "DCS.xxx" with "DCS_F4E"
    local base = write_dir:gsub("[/\\]$", "")
    local parent = base:match("(.+)[/\\]")
    local f4e_dir = parent .. "\\DCS_F4E\\cache\\persistent_ac"

    -- Ensure the directory exists
    lfs.mkdir(parent .. "\\DCS_F4E")
    lfs.mkdir(parent .. "\\DCS_F4E\\cache")
    lfs.mkdir(parent .. "\\DCS_F4E\\cache\\persistent_ac")

    state.cache_dir = f4e_dir
    logInfo("Cache directory: " .. f4e_dir)
    return f4e_dir
end

--------------------------------------------------------------------------------
-- HTTP via curl (io.popen)
--------------------------------------------------------------------------------

local function httpGet(url, output_path)
    local cmd = string.format(
        'curl.exe -s -f -o "%s" --connect-timeout %d --max-time %d "%s"',
        output_path, CONFIG.timeout, CONFIG.timeout * 3, url
    )
    logDebug("GET: " .. url)
    local handle = io.popen(cmd .. " 2>&1", "r")
    local result = handle:read("*a")
    local ok, _, code = handle:close()
    if ok then
        logDebug("GET OK: " .. url)
        return true
    else
        logError("GET failed (" .. tostring(code) .. "): " .. url .. " -> " .. tostring(result))
        return false
    end
end

local function httpPut(url, file_path, ucid)
    local cmd = string.format(
        'curl.exe -s -f -X PUT --data-binary "@%s" --connect-timeout %d --max-time %d -H "Content-Type: application/octet-stream" -H "X-Pilot-UCID: %s" -H "X-Source: hook" "%s"',
        file_path, CONFIG.timeout, CONFIG.timeout * 6, ucid or "", url
    )
    logDebug("PUT: " .. url)
    local handle = io.popen(cmd .. " 2>&1", "r")
    local result = handle:read("*a")
    local ok, _, code = handle:close()
    if ok then
        logDebug("PUT OK: " .. url)
        return true
    else
        logError("PUT failed (" .. tostring(code) .. "): " .. url .. " -> " .. tostring(result))
        return false
    end
end

local function httpGetJson(url)
    local cmd = string.format(
        'curl.exe -s -f --connect-timeout %d --max-time %d "%s"',
        CONFIG.timeout, CONFIG.timeout * 3, url
    )
    local handle = io.popen(cmd, "r")
    local result = handle:read("*a")
    local ok = handle:close()
    if ok and result and #result > 0 then
        return result
    end
    return nil
end

--------------------------------------------------------------------------------
-- Persistence key resolution from mission data
--------------------------------------------------------------------------------

local function getPersistenceKeyForSlot(slot_id)
    -- Read the mission table to find the PersistentAircraftKey for this slot.
    local mission = DCS.getCurrentMission()
    if not mission or not mission.mission then return nil end

    local coalitions = mission.mission.coalition
    if not coalitions then return nil end

    for _, coal_data in pairs(coalitions) do
        if coal_data.country then
            for _, country in pairs(coal_data.country) do
                -- Check planes and helicopters groups
                for _, group_type in pairs({"plane", "helicopter"}) do
                    if country[group_type] and country[group_type].group then
                        for _, group in pairs(country[group_type].group) do
                            if group.units then
                                for _, unit in pairs(group.units) do
                                    if tostring(unit.unitId) == tostring(slot_id) then
                                        -- Found the unit, check for persistence key
                                        if unit.AddPropAircraft and unit.AddPropAircraft.PersistentAircraftKey then
                                            return unit.AddPropAircraft.PersistentAircraftKey, unit.type
                                        end
                                        return nil, unit.type
                                    end
                                end
                            end
                        end
                    end
                end
            end
        end
    end
    return nil
end

--------------------------------------------------------------------------------
-- Pre-seed: download all squadron caches on connect
--------------------------------------------------------------------------------

local function preseedCaches()
    if state.seeded then return end
    state.seeded = true

    logInfo("Pre-seeding persistence caches from server...")
    local cache_dir = getCacheDir()

    -- Get list of all aircraft with persistence keys from the API
    local json_str = httpGetJson(CONFIG.api_base .. "/cache")
    if not json_str then
        logError("Failed to fetch cache list from API")
        return
    end

    -- Parse the JSON response (basic parser for simple arrays of objects)
    -- We look for persistence_key values and download each
    local count = 0
    for key in json_str:gmatch('"persistence_key"%s*:%s*"([^"]+)"') do
        for has_data in json_str:gmatch('"persistence_key"%s*:%s*"' .. key:gsub("([%.%-%+])", "%%%1") .. '".-"has_data"%s*:%s*(%a+)') do
            if has_data == "true" then
                local file_path = cache_dir .. "\\" .. key .. ".cache"
                local url = CONFIG.api_base .. "/cache/" .. key
                if httpGet(url, file_path) then
                    count = count + 1
                    logDebug("Downloaded: " .. key .. ".cache")
                end
            end
            break
        end
    end

    logInfo("Pre-seed complete: " .. count .. " cache file(s) downloaded")
end

--------------------------------------------------------------------------------
-- Upload: send the flown aircraft's cache back to server
--------------------------------------------------------------------------------

local function uploadCurrentCache()
    if not state.current_key then return end

    local cache_dir = getCacheDir()
    local file_path = cache_dir .. "\\" .. state.current_key .. ".cache"

    -- Check if the file exists
    local f = io.open(file_path, "rb")
    if not f then
        logDebug("No cache file to upload: " .. file_path)
        return
    end
    f:close()

    local url = CONFIG.api_base .. "/cache/" .. state.current_key
    logInfo("Uploading cache for " .. state.current_key)
    if httpPut(url, file_path, state.my_ucid) then
        logInfo("Upload complete: " .. state.current_key)
    else
        logError("Upload failed: " .. state.current_key)
    end
end

--------------------------------------------------------------------------------
-- Config file: persist API base URL so user only sets it once
--------------------------------------------------------------------------------

local function loadConfig()
    local config_path = lfs.writedir() .. "Config/MayflyCacheSync.lua"
    local f = io.open(config_path, "r")
    if f then
        local content = f:read("*a")
        f:close()
        local api_base = content:match('api_base%s*=%s*"([^"]+)"')
        if api_base then
            CONFIG.api_base = api_base
            logInfo("Config loaded: api_base = " .. api_base)
        end
        local debug_flag = content:match('debug%s*=%s*(%a+)')
        if debug_flag == "true" then
            CONFIG.debug = true
        end
    end
end

local function saveConfig()
    local config_path = lfs.writedir() .. "Config/MayflyCacheSync.lua"
    local f = io.open(config_path, "w")
    if f then
        f:write('-- MayflyCacheSync configuration\n')
        f:write('-- Edit api_base to point to your DCSServerBot server\n')
        f:write('api_base = "' .. CONFIG.api_base .. '"\n')
        f:write('debug = ' .. tostring(CONFIG.debug) .. '\n')
        f:close()
    end
end

--------------------------------------------------------------------------------
-- DCS Hook Callbacks
--------------------------------------------------------------------------------

function mayflySync.onMissionLoadEnd()
    logInfo("MayflyCacheSync v" .. mayflySyncVersion .. " - Mission loaded")
    loadConfig()

    if CONFIG.api_base:find("YOUR_SERVER_IP") then
        logError("API base URL not configured! Edit Config/MayflyCacheSync.lua")
        saveConfig()
        return
    end

    -- Get local player UCID
    local my_id = net.get_my_player_id()
    if my_id then
        state.my_ucid = net.get_player_info(my_id, 'ucid')
        logDebug("Local UCID: " .. tostring(state.my_ucid))
    end

    -- Pre-seed all persistence caches
    state.seeded = false
    preseedCaches()
end

function mayflySync.onPlayerChangeSlot(id)
    -- Only process our own slot changes
    if id ~= net.get_my_player_id() then return end

    local side, slot = net.get_slot(id)

    -- If leaving a slot (going to spectator or different aircraft), upload
    if state.current_key then
        logInfo("Deslotting from " .. state.current_key)
        uploadCurrentCache()
        state.current_key = nil
        state.current_slot = nil
        state.current_type = nil
    end

    -- If entering a new slot, check for persistence key
    if slot and slot ~= "" and side and side ~= 0 then
        -- Parse the master slot ID (handle multicrew)
        local master_slot = slot
        if not tonumber(slot) then
            local t_start = string.find(slot, '_%d+')
            if t_start then
                master_slot = tonumber(string.sub(slot, 0, t_start - 1))
            end
        else
            master_slot = tonumber(slot)
        end

        if master_slot and master_slot > 0 then
            local key, unit_type = getPersistenceKeyForSlot(master_slot)
            if key then
                state.current_slot = master_slot
                state.current_key = key
                state.current_type = unit_type
                logInfo("Slotted into " .. tostring(unit_type) .. " with persistence key: " .. key)
            else
                logDebug("Slotted into " .. tostring(unit_type or "unknown") .. " (no persistence key)")
            end
        end
    end
end

function mayflySync.onNetDisconnect()
    -- Upload current cache on disconnect
    if state.current_key then
        logInfo("Disconnecting, uploading cache for " .. state.current_key)
        uploadCurrentCache()
    end

    -- Reset state
    state.connected = false
    state.current_slot = nil
    state.current_key = nil
    state.current_type = nil
    state.seeded = false
    state.my_ucid = nil
    logInfo("Disconnected, state reset")
end

function mayflySync.onSimulationStop()
    -- Upload current cache when sim stops
    if state.current_key then
        logInfo("Simulation stopping, uploading cache for " .. state.current_key)
        uploadCurrentCache()
        state.current_key = nil
        state.current_slot = nil
        state.current_type = nil
    end
end

DCS.setUserCallbacks(mayflySync)
logInfo("MayflyCacheSync v" .. mayflySyncVersion .. " loaded")
