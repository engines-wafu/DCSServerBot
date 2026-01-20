-----------------------------------------------------
-- Flight Plan Plugin - Commands
-- Handles commands from Python -> DCS
-----------------------------------------------------
local base      = _G
local dcsbot    = base.dcsbot
local utils     = base.require("DCSServerBotUtils")

-- Create markers for a flight plan
function dcsbot.createFlightPlanMarkers(json)
    log.write('DCSServerBot', log.DEBUG, 'FlightPlan: createFlightPlanMarkers()')
    local channel = json.channel or "-1"
    local timeout = json.timeout or 0
    local script = 'dcsbot.createFlightPlanMarkers(' ..
        json.plan_id .. ', ' ..
        json.coalition .. ', ' ..
        utils.basicSerialize(json.callsign) .. ', ' ..
        utils.basicSerialize(json.departure_name) .. ', ' ..
        '{x=' .. json.departure_x .. ', y=0, z=' .. json.departure_z .. '}, ' ..
        utils.basicSerialize(json.destination_name) .. ', ' ..
        '{x=' .. json.destination_x .. ', y=0, z=' .. json.destination_z .. '}, ' ..
        utils.basicSerialize(json.alternate_name or '') .. ', ' ..
        (json.alternate_x and ('{x=' .. json.alternate_x .. ', y=0, z=' .. json.alternate_z .. '}') or 'nil') .. ', ' ..
        utils.basicSerialize(json.aircraft_type or '') .. ', ' ..
        (json.cruise_altitude or 0) .. ', ' ..
        utils.basicSerialize(json.etd or '') .. ', ' ..
        utils.basicSerialize(json.waypoints or '[]') .. ', ' ..
        '"' .. channel .. '", ' ..
        timeout .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

-- Remove markers for a flight plan
function dcsbot.removeFlightPlanMarkers(json)
    log.write('DCSServerBot', log.DEBUG, 'FlightPlan: removeFlightPlanMarkers()')
    local channel = json.channel or "-1"
    local script = 'dcsbot.removeFlightPlanMarkers(' .. json.plan_id .. ', "' .. channel .. '")'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

-- Show navigation fixes on the F10 map
function dcsbot.showNavFixes(json)
    log.write('DCSServerBot', log.DEBUG, 'FlightPlan: showNavFixes()')
    local channel = json.channel or "-1"
    local fixes_str = json.fixes_json or '[]'
    local batch_num = json.batch_num or 1
    local total_batches = json.total_batches or 1
    local script = 'dcsbot.showNavFixes(' ..
        utils.basicSerialize(json.player_ucid) .. ', ' ..
        json.coalition .. ', ' ..
        utils.basicSerialize(fixes_str) .. ', ' ..
        '"' .. channel .. '", ' ..
        batch_num .. ', ' ..
        total_batches .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

-- Hide navigation fixes for a player
function dcsbot.hideNavFixes(json)
    log.write('DCSServerBot', log.DEBUG, 'FlightPlan: hideNavFixes()')
    local channel = json.channel or "-1"
    local script = 'dcsbot.hideNavFixes(' ..
        utils.basicSerialize(json.player_ucid) .. ', ' ..
        '"' .. channel .. '")'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

-- Hide all navigation fixes (server-wide)
function dcsbot.hideAllNavFixes(json)
    log.write('DCSServerBot', log.DEBUG, 'FlightPlan: hideAllNavFixes()')
    local channel = json.channel or "-1"
    local script = 'dcsbot.hideAllNavFixes("' .. channel .. '")'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end
