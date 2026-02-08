import discord
import logging

from core import Plugin, PluginRequiredError, utils, Group
from datetime import datetime, timezone
from discord import app_commands
from psycopg.rows import dict_row
from services.bot import DCSServerBot
from typing import Literal, Optional

from .listener import MayflyEventListener

log = logging.getLogger(__name__)


# ==================== AUTOCOMPLETE FUNCTIONS ====================

async def squadron_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Autocomplete for squadrons the user belongs to or all (if admin)."""
    try:
        async with interaction.client.apool.connection() as conn:
            if utils.check_roles(interaction.client.roles.get("DCS Admin", []), interaction.user):
                cursor = await conn.execute(
                    "SELECT id, name FROM squadrons WHERE name ILIKE %s ORDER BY name LIMIT 25",
                    ('%' + current + '%',)
                )
            else:
                ucid = await interaction.client.get_ucid_by_member(interaction.user)
                if not ucid:
                    return []
                cursor = await conn.execute("""
                    SELECT s.id, s.name FROM squadrons s
                    JOIN squadron_members sm ON s.id = sm.squadron_id
                    WHERE sm.player_ucid = %s AND s.name ILIKE %s
                    ORDER BY s.name LIMIT 25
                """, (ucid, '%' + current + '%'))
            return [
                app_commands.Choice(name=row[1], value=row[0])
                async for row in cursor
            ]
    except Exception as e:
        log.warning(f"Squadron autocomplete error: {e}")
        return []


async def aircraft_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Autocomplete for aircraft by tail number within a squadron."""
    try:
        squadron_id = interaction.namespace.squadron
        if not squadron_id:
            return []
        async with interaction.client.apool.connection() as conn:
            cursor = await conn.execute("""
                SELECT id, tail_number || ' (' || aircraft_type || ')' AS label
                FROM mayfly_aircraft
                WHERE squadron_id = %s
                  AND status != 'written_off'
                  AND tail_number ILIKE %s
                ORDER BY tail_number LIMIT 25
            """, (squadron_id, '%' + current + '%'))
            return [
                app_commands.Choice(name=row[1], value=row[0])
                async for row in cursor
            ]
    except Exception as e:
        log.warning(f"Aircraft autocomplete error: {e}")
        return []


async def serviceable_aircraft_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Autocomplete for serviceable aircraft only (for signout)."""
    try:
        squadron_id = interaction.namespace.squadron
        if not squadron_id:
            return []
        async with interaction.client.apool.connection() as conn:
            cursor = await conn.execute("""
                SELECT id, tail_number || ' (' || aircraft_type || ')' AS label
                FROM mayfly_aircraft
                WHERE squadron_id = %s
                  AND status = 'serviceable'
                  AND current_pilot_ucid IS NULL
                  AND tail_number ILIKE %s
                ORDER BY tail_number LIMIT 25
            """, (squadron_id, '%' + current + '%'))
            return [
                app_commands.Choice(name=row[1], value=row[0])
                async for row in cursor
            ]
    except Exception as e:
        log.warning(f"Serviceable aircraft autocomplete error: {e}")
        return []


async def signed_out_aircraft_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Autocomplete for aircraft currently signed out to the calling pilot."""
    try:
        ucid = await interaction.client.get_ucid_by_member(interaction.user)
        if not ucid:
            return []
        async with interaction.client.apool.connection() as conn:
            cursor = await conn.execute("""
                SELECT a.id, a.tail_number || ' (' || a.aircraft_type || ')' AS label
                FROM mayfly_aircraft a
                WHERE a.current_pilot_ucid = %s
                  AND a.tail_number ILIKE %s
                ORDER BY a.tail_number LIMIT 25
            """, (ucid, '%' + current + '%'))
            return [
                app_commands.Choice(name=row[1], value=row[0])
                async for row in cursor
            ]
    except Exception as e:
        log.warning(f"Signed-out aircraft autocomplete error: {e}")
        return []


async def open_defect_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    """Autocomplete for open defects on an aircraft."""
    try:
        aircraft_id = interaction.namespace.aircraft
        if not aircraft_id:
            return []
        async with interaction.client.apool.connection() as conn:
            cursor = await conn.execute("""
                SELECT id, 'SNOW ' || snow || ': ' || LEFT(description, 60) AS label
                FROM mayfly_defects
                WHERE aircraft_id = %s AND status = 'open'
                ORDER BY snow LIMIT 25
            """, (aircraft_id,))
            return [
                app_commands.Choice(name=row[1], value=row[0])
                async for row in cursor
            ]
    except Exception as e:
        log.warning(f"Defect autocomplete error: {e}")
        return []


# ==================== HELPER FUNCTIONS ====================

def format_hours(hours) -> str:
    """Format decimal hours as Xh Ym."""
    if not hours:
        return "0h 0m"
    h = int(hours)
    m = int((float(hours) - h) * 60)
    return f"{h}h {m}m"


STATUS_EMOJI = {
    'serviceable': '\U0001f7e2',      # green circle
    'unserviceable': '\U0001f534',    # red circle
    'limited': '\U0001f7e1',          # yellow circle
    'grounded': '\u26d4',             # no entry
    'written_off': '\u2620\ufe0f',    # skull
}


def status_display(status: str) -> str:
    emoji = STATUS_EMOJI.get(status, '\u2753')
    return f"{emoji} {status.replace('_', ' ').title()}"


# ==================== PLUGIN CLASS ====================

class Mayfly(Plugin[MayflyEventListener]):
    """Aircraft management & MF700 documentation plugin."""

    mayfly = Group(name="mayfly", description="Aircraft management & MF700 documentation")

    # ==================== /mayfly board ====================

    @mayfly.command(description='Display squadron fleet status board')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(squadron='Squadron to display')
    @app_commands.autocomplete(squadron=squadron_autocomplete)
    async def board(self, interaction: discord.Interaction, squadron: int):
        ephemeral = utils.get_ephemeral(interaction)
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=ephemeral)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Get squadron name
                await cursor.execute("SELECT name FROM squadrons WHERE id = %s", (squadron,))
                sq = await cursor.fetchone()
                if not sq:
                    await interaction.followup.send("Squadron not found.", ephemeral=True)
                    return

                # Get all aircraft for this squadron
                await cursor.execute("""
                    SELECT a.*, p.name as pilot_name
                    FROM mayfly_aircraft a
                    LEFT JOIN players p ON a.current_pilot_ucid = p.ucid
                    WHERE a.squadron_id = %s AND a.status != 'written_off'
                    ORDER BY a.tail_number
                """, (squadron,))
                aircraft = await cursor.fetchall()

        if not aircraft:
            await interaction.followup.send(
                f"No aircraft registered for **{sq['name']}**. Use `/mayfly add` to register aircraft.",
                ephemeral=ephemeral
            )
            return

        # Build fleet status embed
        embed = discord.Embed(
            title=f"Fleet Status Board - {sq['name']}",
            color=discord.Color.dark_blue(),
            timestamp=datetime.now(timezone.utc)
        )

        # Summary counts
        total = len(aircraft)
        serviceable = sum(1 for a in aircraft if a['status'] == 'serviceable')
        unserviceable = sum(1 for a in aircraft if a['status'] in ('unserviceable', 'grounded'))
        signed_out = sum(1 for a in aircraft if a['current_pilot_ucid'])

        embed.description = (
            f"**Total:** {total} | "
            f"**Serviceable:** {serviceable} | "
            f"**U/S:** {unserviceable} | "
            f"**Signed Out:** {signed_out}"
        )

        # List each aircraft (Discord embed max 25 fields)
        for ac in aircraft[:25]:
            pilot_info = f" \u2708 {ac['pilot_name']}" if ac['pilot_name'] else ""
            hours = format_hours(ac['total_flight_hours'])
            value = f"{ac['aircraft_type']} | {hours}{pilot_info}"
            embed.add_field(
                name=f"{status_display(ac['status'])} {ac['tail_number']}",
                value=value,
                inline=True
            )

        footer = "Mayfly v0.1"
        if len(aircraft) > 25:
            footer = f"Showing 25 of {len(aircraft)} aircraft | {footer}"
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    # ==================== /mayfly check ====================

    @mayfly.command(description='Show detailed aircraft status card')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(squadron='Squadron', aircraft='Aircraft to inspect')
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def check(self, interaction: discord.Interaction, squadron: int, aircraft: int):
        ephemeral = utils.get_ephemeral(interaction)
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=ephemeral)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Get aircraft details
                await cursor.execute("""
                    SELECT a.*, s.name as squadron_name, p.name as pilot_name
                    FROM mayfly_aircraft a
                    JOIN squadrons s ON a.squadron_id = s.id
                    LEFT JOIN players p ON a.current_pilot_ucid = p.ucid
                    WHERE a.id = %s
                """, (aircraft,))
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                # Get open defects
                await cursor.execute("""
                    SELECT d.snow, d.description, d.status, d.deferred_category,
                           p.name as reported_by
                    FROM mayfly_defects d
                    LEFT JOIN players p ON d.reported_by_ucid = p.ucid
                    WHERE d.aircraft_id = %s AND d.status IN ('open', 'deferred')
                    ORDER BY d.snow
                """, (aircraft,))
                defects = await cursor.fetchall()

                # Get active limitations
                await cursor.execute("""
                    SELECT description FROM mayfly_limitations
                    WHERE aircraft_id = %s AND active = TRUE
                    ORDER BY created_at
                """, (aircraft,))
                limitations = await cursor.fetchall()

                # Get recent flights (last 5)
                await cursor.execute("""
                    SELECT f.signed_out_at, f.signed_in_at, f.flight_hours,
                           f.result, p.name as pilot_name
                    FROM mayfly_flights f
                    JOIN players p ON f.pilot_ucid = p.ucid
                    WHERE f.aircraft_id = %s
                    ORDER BY f.signed_out_at DESC LIMIT 5
                """, (aircraft,))
                flights = await cursor.fetchall()

        # Build status card embed
        embed = discord.Embed(
            title=f"{ac['tail_number']} - {ac['aircraft_type']}",
            description=f"**{ac['squadron_name']}**",
            color=discord.Color.green() if ac['status'] == 'serviceable' else
                  discord.Color.yellow() if ac['status'] == 'limited' else
                  discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )

        # Status & basic info
        embed.add_field(name="Status", value=status_display(ac['status']), inline=True)
        embed.add_field(name="Total Hours", value=format_hours(ac['total_flight_hours']), inline=True)
        if ac['pilot_name']:
            embed.add_field(name="Signed Out To", value=ac['pilot_name'], inline=True)
        else:
            embed.add_field(name="Availability", value="Available", inline=True)

        if ac['persistence_key']:
            embed.add_field(name="Persistence Key", value=f"`{ac['persistence_key']}`", inline=True)
        if ac['livery_id']:
            embed.add_field(name="Livery", value=ac['livery_id'], inline=True)
        if ac['notes']:
            embed.add_field(name="Notes", value=ac['notes'], inline=False)

        # Defects section
        if defects:
            defect_lines = []
            for d in defects:
                prefix = "\U0001f7e1 DEF" if d['status'] == 'deferred' else "\U0001f534"
                cat = f" [{d['deferred_category']}]" if d['deferred_category'] else ""
                defect_lines.append(f"{prefix} **SNOW {d['snow']}**: {d['description'][:80]}{cat}")
            embed.add_field(
                name=f"Open Defects ({len(defects)})",
                value="\n".join(defect_lines[:10]),
                inline=False
            )
        else:
            embed.add_field(name="Defects", value="No open defects", inline=False)

        # Limitations section
        if limitations:
            lim_lines = [f"\u26a0\ufe0f {l['description']}" for l in limitations]
            embed.add_field(
                name=f"Limitations ({len(limitations)})",
                value="\n".join(lim_lines[:10]),
                inline=False
            )

        # Recent flights
        if flights:
            flight_lines = []
            for f in flights:
                date = f['signed_out_at'].strftime('%d %b') if f['signed_out_at'] else '?'
                hours = format_hours(f['flight_hours']) if f['flight_hours'] else 'in progress'
                result = f" [{f['result']}]" if f['result'] != 'normal' else ''
                flight_lines.append(f"{date}: {f['pilot_name']} - {hours}{result}")
            embed.add_field(
                name="Recent Flights",
                value="\n".join(flight_lines),
                inline=False
            )

        embed.set_footer(text="Mayfly v0.1")
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    # ==================== /mayfly signout ====================

    @mayfly.command(description='Sign out an aircraft for a sortie')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft to sign out (must be serviceable and available)',
        departure='Departure airbase'
    )
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=serviceable_aircraft_autocomplete)
    async def signout(self, interaction: discord.Interaction,
                      squadron: int, aircraft: int,
                      departure: Optional[str] = None):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        ucid = await self.bot.get_ucid_by_member(interaction.user)
        if not ucid:
            await interaction.followup.send("You are not linked to a DCS account.", ephemeral=True)
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Verify aircraft exists and is available
                await cursor.execute("""
                    SELECT a.*, s.name as squadron_name
                    FROM mayfly_aircraft a
                    JOIN squadrons s ON a.squadron_id = s.id
                    WHERE a.id = %s AND a.squadron_id = %s
                """, (aircraft, squadron))
                ac = await cursor.fetchone()

                if not ac:
                    await interaction.followup.send("Aircraft not found in that squadron.", ephemeral=True)
                    return

                if ac['status'] != 'serviceable':
                    await interaction.followup.send(
                        f"**{ac['tail_number']}** is **{ac['status']}** and cannot be signed out.",
                        ephemeral=True
                    )
                    return

                if ac['current_pilot_ucid']:
                    await interaction.followup.send(
                        f"**{ac['tail_number']}** is already signed out to another pilot.",
                        ephemeral=True
                    )
                    return

                # Check pilot isn't already flying another aircraft
                await cursor.execute(
                    "SELECT tail_number FROM mayfly_aircraft WHERE current_pilot_ucid = %s",
                    (ucid,)
                )
                existing = await cursor.fetchone()
                if existing:
                    await interaction.followup.send(
                        f"You already have **{existing['tail_number']}** signed out. Sign it in first.",
                        ephemeral=True
                    )
                    return

                # Sign out the aircraft
                await conn.execute(
                    "UPDATE mayfly_aircraft SET current_pilot_ucid = %s WHERE id = %s",
                    (ucid, aircraft)
                )

                # Create flight record
                await conn.execute("""
                    INSERT INTO mayfly_flights (aircraft_id, pilot_ucid, departure_airbase)
                    VALUES (%s, %s, %s)
                """, (aircraft, ucid, departure))

        embed = discord.Embed(
            title=f"\u2708\ufe0f Aircraft Signed Out",
            description=f"**{ac['tail_number']}** ({ac['aircraft_type']})",
            color=discord.Color.green()
        )
        embed.add_field(name="Squadron", value=ac['squadron_name'], inline=True)
        embed.add_field(name="Pilot", value=interaction.user.display_name, inline=True)
        if departure:
            embed.add_field(name="Departure", value=departure, inline=True)
        embed.set_footer(text="Sign in with /mayfly signin when complete")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly signin ====================

    @mayfly.command(description='Sign in an aircraft after a sortie')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(
        aircraft='Aircraft to sign in (must be signed out to you)',
        flight_hours='Flight time in decimal hours (e.g. 1.5)',
        arrival='Arrival airbase',
        result='Sortie result'
    )
    @app_commands.autocomplete(aircraft=signed_out_aircraft_autocomplete)
    async def signin(self, interaction: discord.Interaction,
                     aircraft: int,
                     flight_hours: float,
                     arrival: Optional[str] = None,
                     result: Literal['normal', 'diverted', 'emergency', 'crashed', 'ejected'] = 'normal'):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        ucid = await self.bot.get_ucid_by_member(interaction.user)
        if not ucid:
            await interaction.followup.send("You are not linked to a DCS account.", ephemeral=True)
            return

        if flight_hours < 0 or flight_hours > 24:
            await interaction.followup.send(
                "Flight hours must be between 0 and 24.", ephemeral=True
            )
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Verify aircraft is signed out to this pilot
                await cursor.execute("""
                    SELECT a.*, s.name as squadron_name
                    FROM mayfly_aircraft a
                    JOIN squadrons s ON a.squadron_id = s.id
                    WHERE a.id = %s AND a.current_pilot_ucid = %s
                """, (aircraft, ucid))
                ac = await cursor.fetchone()

                if not ac:
                    await interaction.followup.send(
                        "This aircraft is not signed out to you.", ephemeral=True
                    )
                    return

                # Update the open flight record
                await conn.execute("""
                    UPDATE mayfly_flights
                    SET signed_in_at = NOW() AT TIME ZONE 'utc',
                        flight_hours = %s,
                        arrival_airbase = %s,
                        result = %s
                    WHERE aircraft_id = %s AND pilot_ucid = %s AND signed_in_at IS NULL
                """, (flight_hours, arrival, result, aircraft, ucid))

                # Update aircraft: release pilot, add flight hours
                new_status = 'serviceable'
                if result in ('crashed', 'ejected'):
                    new_status = 'unserviceable'

                await conn.execute("""
                    UPDATE mayfly_aircraft
                    SET current_pilot_ucid = NULL,
                        total_flight_hours = total_flight_hours + %s,
                        status = %s
                    WHERE id = %s
                """, (flight_hours, new_status, aircraft))

        embed = discord.Embed(
            title=f"\U0001f6ec Aircraft Signed In",
            description=f"**{ac['tail_number']}** ({ac['aircraft_type']})",
            color=discord.Color.blue() if result == 'normal' else discord.Color.orange()
        )
        embed.add_field(name="Squadron", value=ac['squadron_name'], inline=True)
        embed.add_field(name="Flight Time", value=format_hours(flight_hours), inline=True)
        embed.add_field(name="Result", value=result.title(), inline=True)
        if arrival:
            embed.add_field(name="Arrival", value=arrival, inline=True)
        if result in ('crashed', 'ejected'):
            embed.add_field(
                name="\u26a0\ufe0f Status Changed",
                value="Aircraft marked **unserviceable** due to crash/ejection",
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly report ====================

    @mayfly.command(description='Report a defect (F707 SNOW entry)')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft with defect',
        description='Description of the defect'
    )
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def report(self, interaction: discord.Interaction,
                     squadron: int, aircraft: int,
                     description: str):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        ucid = await self.bot.get_ucid_by_member(interaction.user)
        if not ucid:
            await interaction.followup.send("You are not linked to a DCS account.", ephemeral=True)
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Verify aircraft
                await cursor.execute("""
                    SELECT a.tail_number, a.aircraft_type, s.name as squadron_name
                    FROM mayfly_aircraft a
                    JOIN squadrons s ON a.squadron_id = s.id
                    WHERE a.id = %s AND a.squadron_id = %s
                """, (aircraft, squadron))
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                # Get next SNOW number for this aircraft
                await cursor.execute(
                    "SELECT COALESCE(MAX(snow), 0) + 1 as next_snow FROM mayfly_defects WHERE aircraft_id = %s",
                    (aircraft,)
                )
                row = await cursor.fetchone()
                snow = row['next_snow']

                # Find current open flight for this aircraft (if any)
                await cursor.execute("""
                    SELECT id FROM mayfly_flights
                    WHERE aircraft_id = %s AND signed_in_at IS NULL
                    ORDER BY signed_out_at DESC LIMIT 1
                """, (aircraft,))
                flight = await cursor.fetchone()
                flight_id = flight['id'] if flight else None

                # Create defect
                await conn.execute("""
                    INSERT INTO mayfly_defects
                    (aircraft_id, snow, flight_id, reported_by_ucid, description)
                    VALUES (%s, %s, %s, %s, %s)
                """, (aircraft, snow, flight_id, ucid, description))

        embed = discord.Embed(
            title=f"\U0001f534 Defect Reported - SNOW {snow}",
            description=f"**{ac['tail_number']}** ({ac['aircraft_type']})",
            color=discord.Color.red()
        )
        embed.add_field(name="Squadron", value=ac['squadron_name'], inline=True)
        embed.add_field(name="Reported By", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Description", value=description, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly defects ====================

    @mayfly.command(description='List open defects for an aircraft')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(squadron='Squadron', aircraft='Aircraft to check')
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def defects(self, interaction: discord.Interaction, squadron: int, aircraft: int):
        ephemeral = utils.get_ephemeral(interaction)
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=ephemeral)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT a.tail_number, a.aircraft_type, s.name as squadron_name
                    FROM mayfly_aircraft a
                    JOIN squadrons s ON a.squadron_id = s.id
                    WHERE a.id = %s AND a.squadron_id = %s
                """, (aircraft, squadron))
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                await cursor.execute("""
                    SELECT d.*, p.name as reported_by, r.name as rectified_by
                    FROM mayfly_defects d
                    LEFT JOIN players p ON d.reported_by_ucid = p.ucid
                    LEFT JOIN players r ON d.rectified_by_ucid = r.ucid
                    WHERE d.aircraft_id = %s AND d.status IN ('open', 'deferred')
                    ORDER BY d.snow
                """, (aircraft,))
                defects = await cursor.fetchall()

        if not defects:
            await interaction.followup.send(
                f"No open defects for **{ac['tail_number']}**.", ephemeral=ephemeral
            )
            return

        embed = discord.Embed(
            title=f"F707 Defect Log - {ac['tail_number']}",
            description=f"{ac['aircraft_type']} | {ac['squadron_name']}",
            color=discord.Color.red()
        )

        for d in defects[:15]:
            status_icon = "\U0001f7e1 DEFERRED" if d['status'] == 'deferred' else "\U0001f534 OPEN"
            cat = f" [{d['deferred_category']}]" if d['deferred_category'] else ""
            name = f"SNOW {d['snow']} - {status_icon}{cat}"
            value = d['description'][:100]
            if d['reported_by']:
                value += f"\n*Reported by {d['reported_by']}*"
            embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text=f"{len(defects)} open defect(s)")
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    # ==================== /mayfly rectify ====================

    @mayfly.command(description='Rectify (close) a defect')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft',
        defect='Defect to rectify'
    )
    @app_commands.autocomplete(
        squadron=squadron_autocomplete,
        aircraft=aircraft_autocomplete,
        defect=open_defect_autocomplete
    )
    async def rectify(self, interaction: discord.Interaction,
                      squadron: int, aircraft: int, defect: int):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        ucid = await self.bot.get_ucid_by_member(interaction.user)
        if not ucid:
            await interaction.followup.send("You are not linked to a DCS account.", ephemeral=True)
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT d.snow, d.description, a.tail_number
                    FROM mayfly_defects d
                    JOIN mayfly_aircraft a ON d.aircraft_id = a.id
                    WHERE d.id = %s AND d.aircraft_id = %s AND d.status IN ('open', 'deferred')
                """, (defect, aircraft))
                d = await cursor.fetchone()
                if not d:
                    await interaction.followup.send("Defect not found or already rectified.", ephemeral=True)
                    return

                await conn.execute("""
                    UPDATE mayfly_defects
                    SET status = 'rectified',
                        rectified_by_ucid = %s,
                        rectified_at = NOW() AT TIME ZONE 'utc'
                    WHERE id = %s
                """, (ucid, defect))

        embed = discord.Embed(
            title=f"\u2705 Defect Rectified - SNOW {d['snow']}",
            description=f"**{d['tail_number']}**: {d['description'][:100]}",
            color=discord.Color.green()
        )
        embed.add_field(name="Rectified By", value=interaction.user.display_name, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly defer ====================

    @mayfly.command(description='Defer a defect (F704)')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft',
        defect='Defect to defer',
        category='Deferral category'
    )
    @app_commands.autocomplete(
        squadron=squadron_autocomplete,
        aircraft=aircraft_autocomplete,
        defect=open_defect_autocomplete
    )
    async def defer(self, interaction: discord.Interaction,
                    squadron: int, aircraft: int, defect: int,
                    category: Literal['CAT A', 'CAT B', 'CAT C', 'CAT D'] = 'CAT B'):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT d.snow, d.description, a.tail_number
                    FROM mayfly_defects d
                    JOIN mayfly_aircraft a ON d.aircraft_id = a.id
                    WHERE d.id = %s AND d.aircraft_id = %s AND d.status = 'open'
                """, (defect, aircraft))
                d = await cursor.fetchone()
                if not d:
                    await interaction.followup.send("Defect not found or not open.", ephemeral=True)
                    return

                await conn.execute("""
                    UPDATE mayfly_defects
                    SET status = 'deferred', deferred_category = %s
                    WHERE id = %s
                """, (category, defect))

        embed = discord.Embed(
            title=f"\U0001f7e1 Defect Deferred - SNOW {d['snow']}",
            description=f"**{d['tail_number']}**: {d['description'][:100]}",
            color=discord.Color.yellow()
        )
        embed.add_field(name="Category", value=category, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly limit ====================

    @mayfly.command(description='Add a limitation to an aircraft (F703)')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft',
        description='Limitation description'
    )
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def limit(self, interaction: discord.Interaction,
                    squadron: int, aircraft: int,
                    description: str):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        ucid = await self.bot.get_ucid_by_member(interaction.user)
        if not ucid:
            await interaction.followup.send("You are not linked to a DCS account.", ephemeral=True)
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT a.tail_number, a.aircraft_type, s.name as squadron_name
                    FROM mayfly_aircraft a
                    JOIN squadrons s ON a.squadron_id = s.id
                    WHERE a.id = %s AND a.squadron_id = %s
                """, (aircraft, squadron))
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                await conn.execute("""
                    INSERT INTO mayfly_limitations (aircraft_id, description, added_by_ucid)
                    VALUES (%s, %s, %s)
                """, (aircraft, description, ucid))

        embed = discord.Embed(
            title=f"\u26a0\ufe0f Limitation Added",
            description=f"**{ac['tail_number']}** ({ac['aircraft_type']})",
            color=discord.Color.yellow()
        )
        embed.add_field(name="Limitation", value=description, inline=False)
        embed.add_field(name="Added By", value=interaction.user.display_name, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly unlimit ====================

    @mayfly.command(description='Remove a limitation from an aircraft')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    @app_commands.describe(squadron='Squadron', aircraft='Aircraft')
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def unlimit(self, interaction: discord.Interaction, squadron: int, aircraft: int):
        """Remove the most recent active limitation. Use /mayfly check to see all."""
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT l.id, l.description, a.tail_number
                    FROM mayfly_limitations l
                    JOIN mayfly_aircraft a ON l.aircraft_id = a.id
                    WHERE l.aircraft_id = %s AND l.active = TRUE
                    ORDER BY l.created_at DESC LIMIT 1
                """, (aircraft,))
                lim = await cursor.fetchone()
                if not lim:
                    await interaction.followup.send("No active limitations on this aircraft.", ephemeral=True)
                    return

                await conn.execute("""
                    UPDATE mayfly_limitations
                    SET active = FALSE, removed_at = NOW() AT TIME ZONE 'utc'
                    WHERE id = %s
                """, (lim['id'],))

        embed = discord.Embed(
            title=f"\u2705 Limitation Removed",
            description=f"**{lim['tail_number']}**: {lim['description']}",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly ground ====================

    @mayfly.command(description='Ground an aircraft (WCPO/admin)')
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.describe(squadron='Squadron', aircraft='Aircraft', reason='Reason for grounding')
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def ground(self, interaction: discord.Interaction,
                     squadron: int, aircraft: int, reason: Optional[str] = None):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT tail_number FROM mayfly_aircraft WHERE id = %s", (aircraft,)
                )
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                await conn.execute(
                    "UPDATE mayfly_aircraft SET status = 'grounded' WHERE id = %s", (aircraft,)
                )

        msg = f"\u26d4 **{ac['tail_number']}** has been **grounded**."
        if reason:
            msg += f"\nReason: {reason}"
        await interaction.followup.send(msg, ephemeral=True)

    # ==================== /mayfly release ====================

    @mayfly.command(description='Release aircraft back to serviceable (WCPO/admin)')
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.describe(squadron='Squadron', aircraft='Aircraft')
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def release(self, interaction: discord.Interaction, squadron: int, aircraft: int):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT a.tail_number, a.status,
                           (SELECT COUNT(*) FROM mayfly_defects d
                            WHERE d.aircraft_id = a.id AND d.status = 'open') as open_defects,
                           (SELECT COUNT(*) FROM mayfly_limitations l
                            WHERE l.aircraft_id = a.id AND l.active = TRUE) as active_limitations
                    FROM mayfly_aircraft a WHERE a.id = %s
                """, (aircraft,))
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                new_status = 'serviceable'
                warnings = []
                if ac['open_defects'] > 0:
                    warnings.append(f"{ac['open_defects']} open defect(s) remain")
                if ac['active_limitations'] > 0:
                    warnings.append(f"{ac['active_limitations']} active limitation(s)")
                    new_status = 'limited'

                await conn.execute(
                    "UPDATE mayfly_aircraft SET status = %s WHERE id = %s",
                    (new_status, aircraft)
                )

        msg = f"\u2705 **{ac['tail_number']}** released to **{new_status}**."
        if warnings:
            msg += "\n\u26a0\ufe0f " + ", ".join(warnings)
        await interaction.followup.send(msg, ephemeral=True)

    # ==================== /mayfly add ====================

    @mayfly.command(description='Register a new aircraft')
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.describe(
        squadron='Squadron to assign aircraft to',
        tail_number='Tail number (e.g. XT-901)',
        aircraft_type='Aircraft type (e.g. F-4E-45MC)',
        persistence_key='DCS persistence key (optional)',
        livery_id='Livery identifier (optional)',
        notes='Additional notes (optional)'
    )
    @app_commands.autocomplete(squadron=squadron_autocomplete)
    async def add(self, interaction: discord.Interaction,
                  squadron: int, tail_number: str, aircraft_type: str,
                  persistence_key: Optional[str] = None,
                  livery_id: Optional[str] = None,
                  notes: Optional[str] = None):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Check for duplicate
                await cursor.execute("""
                    SELECT id FROM mayfly_aircraft
                    WHERE squadron_id = %s AND tail_number = %s
                """, (squadron, tail_number))
                if await cursor.fetchone():
                    await interaction.followup.send(
                        f"Aircraft **{tail_number}** already exists in this squadron.",
                        ephemeral=True
                    )
                    return

                # Get squadron name
                await cursor.execute("SELECT name FROM squadrons WHERE id = %s", (squadron,))
                sq = await cursor.fetchone()
                if not sq:
                    await interaction.followup.send("Squadron not found.", ephemeral=True)
                    return

                await conn.execute("""
                    INSERT INTO mayfly_aircraft
                    (squadron_id, tail_number, aircraft_type, persistence_key, livery_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (squadron, tail_number, aircraft_type, persistence_key, livery_id, notes))

        embed = discord.Embed(
            title=f"\u2795 Aircraft Registered",
            description=f"**{tail_number}** ({aircraft_type})",
            color=discord.Color.green()
        )
        embed.add_field(name="Squadron", value=sq['name'], inline=True)
        if persistence_key:
            embed.add_field(name="Persistence Key", value=f"`{persistence_key}`", inline=True)
        if livery_id:
            embed.add_field(name="Livery", value=livery_id, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ==================== /mayfly remove ====================

    @mayfly.command(description='Write off / remove an aircraft')
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft to write off',
        reason='Reason for write-off'
    )
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def remove(self, interaction: discord.Interaction,
                     squadron: int, aircraft: int,
                     reason: Optional[str] = None):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT tail_number, aircraft_type FROM mayfly_aircraft WHERE id = %s",
                    (aircraft,)
                )
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                # Close any open flight records
                await conn.execute("""
                    UPDATE mayfly_flights
                    SET signed_in_at = NOW() AT TIME ZONE 'utc',
                        result = 'written_off'
                    WHERE aircraft_id = %s AND signed_in_at IS NULL
                """, (aircraft,))

                await conn.execute("""
                    UPDATE mayfly_aircraft
                    SET status = 'written_off',
                        written_off_at = NOW() AT TIME ZONE 'utc',
                        written_off_reason = %s,
                        current_pilot_ucid = NULL
                    WHERE id = %s
                """, (reason, aircraft))

        msg = f"\u2620\ufe0f **{ac['tail_number']}** ({ac['aircraft_type']}) has been **written off**."
        if reason:
            msg += f"\nReason: {reason}"
        await interaction.followup.send(msg, ephemeral=True)

    # ==================== /mayfly edit ====================

    @mayfly.command(description='Edit aircraft details')
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.describe(
        squadron='Squadron',
        aircraft='Aircraft to edit',
        tail_number='New tail number',
        aircraft_type='New aircraft type',
        persistence_key='New persistence key',
        livery_id='New livery ID',
        notes='New notes'
    )
    @app_commands.autocomplete(squadron=squadron_autocomplete, aircraft=aircraft_autocomplete)
    async def edit(self, interaction: discord.Interaction,
                   squadron: int, aircraft: int,
                   tail_number: Optional[str] = None,
                   aircraft_type: Optional[str] = None,
                   persistence_key: Optional[str] = None,
                   livery_id: Optional[str] = None,
                   notes: Optional[str] = None):
        # noinspection PyUnresolvedReferences
        await interaction.response.defer(ephemeral=True)

        if not any([tail_number, aircraft_type, persistence_key, livery_id, notes]):
            await interaction.followup.send("Provide at least one field to update.", ephemeral=True)
            return

        updates = []
        params = []
        if tail_number:
            updates.append("tail_number = %s")
            params.append(tail_number)
        if aircraft_type:
            updates.append("aircraft_type = %s")
            params.append(aircraft_type)
        if persistence_key:
            updates.append("persistence_key = %s")
            params.append(persistence_key)
        if livery_id:
            updates.append("livery_id = %s")
            params.append(livery_id)
        if notes:
            updates.append("notes = %s")
            params.append(notes)

        params.append(aircraft)

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT tail_number FROM mayfly_aircraft WHERE id = %s", (aircraft,)
                )
                ac = await cursor.fetchone()
                if not ac:
                    await interaction.followup.send("Aircraft not found.", ephemeral=True)
                    return

                await conn.execute(
                    f"UPDATE mayfly_aircraft SET {', '.join(updates)} WHERE id = %s",
                    tuple(params)
                )

        await interaction.followup.send(
            f"\u2705 **{ac['tail_number']}** updated successfully.", ephemeral=True
        )


async def setup(bot: DCSServerBot):
    if 'userstats' not in bot.plugins:
        raise PluginRequiredError('userstats')
    await bot.add_cog(Mayfly(bot, MayflyEventListener))
