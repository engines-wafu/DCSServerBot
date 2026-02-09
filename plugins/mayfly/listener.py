import asyncio

from core import EventListener, PersistentReport, Server, Player, event
from discord.ext import tasks
from psycopg.rows import dict_row
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .commands import Mayfly


class MayflyEventListener(EventListener["Mayfly"]):
    """Event listener for Mayfly - tracks DCS flight events for aircraft management."""

    def __init__(self, plugin: "Mayfly"):
        super().__init__(plugin)
        self.fleet_dirty: bool = False
        self.update_fleet_board.start()

    async def shutdown(self):
        self.update_fleet_board.cancel()

    @tasks.loop(seconds=30)
    async def update_fleet_board(self):
        if not self.fleet_dirty:
            return
        self.log.debug("Fleet board update triggered")
        try:
            await self._render_fleet_boards()
            self.log.debug("Fleet board update complete")
        except Exception as ex:
            self.log.exception(ex)
        finally:
            self.fleet_dirty = False

    @update_fleet_board.before_loop
    async def before_update_fleet_board(self):
        await self.bot.wait_until_ready()
        self.log.info("Fleet board loop ready, scheduling initial render")
        # Render boards on first loop iteration
        self.fleet_dirty = True

    def mark_fleet_dirty(self):
        self.fleet_dirty = True

    async def _render_fleet_boards(self):
        config = self.get_config()
        channel_id = config.get('fleet_channel')
        if not channel_id:
            return

        channel_id = int(channel_id)

        # Get all squadrons that have mayfly aircraft
        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT DISTINCT s.id, s.name
                    FROM squadrons s
                    JOIN mayfly_aircraft a ON a.squadron_id = s.id
                    WHERE a.written_off_at IS NULL
                    ORDER BY s.name
                """)
                squadrons = await cursor.fetchall()

        for sq in squadrons:
            try:
                report = PersistentReport(
                    self.bot, self.plugin_name, 'fleet_board.json',
                    embed_name=f"mayfly_sq_{sq['id']}",
                    channel_id=channel_id
                )
                await report.render(squadron_name=sq['name'], squadron_id=sq['id'])
            except Exception as ex:
                self.log.error(f"Failed to render fleet board for {sq['name']}: {ex}")

    @event(name="registerDCSServer")
    async def registerDCSServer(self, server: Server, data: dict) -> None:
        asyncio.create_task(self._render_fleet_boards())

    @event(name="onPlayerStart")
    async def on_player_start(self, server: Server, data: dict) -> None:
        """When a player spawns in a slot, check if they have an aircraft signed out."""
        ucid = data.get('ucid')
        if not ucid:
            return

        player: Player = server.get_player(ucid=ucid)
        if not player:
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT a.tail_number, a.aircraft_type
                    FROM mayfly_aircraft a
                    WHERE a.current_pilot_ucid = %s
                """, (ucid,))
                ac = await cursor.fetchone()

        if ac:
            await player.sendChatMessage(
                f"[MAYFLY] You have {ac['tail_number']} ({ac['aircraft_type']}) signed out. "
                f"Remember to /mayfly signin when done."
            )

    @event(name="onGameEvent")
    async def on_game_event(self, server: Server, data: dict) -> None:
        """Handle crash/ejection events to flag aircraft as unserviceable."""
        event_name = data.get('eventName')
        if event_name not in ('crash', 'eject', 'pilot_death'):
            return

        ucid = None
        if 'arg1' in data:
            player: Player = server.get_player(id=data['arg1'])
            if player:
                ucid = player.ucid

        if not ucid:
            return

        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                # Check if this pilot has a signed-out aircraft
                await cursor.execute("""
                    SELECT id, tail_number FROM mayfly_aircraft
                    WHERE current_pilot_ucid = %s
                """, (ucid,))
                ac = await cursor.fetchone()

                if not ac:
                    return

                # Mark aircraft unserviceable and release pilot
                await conn.execute("""
                    UPDATE mayfly_aircraft
                    SET status = 'unserviceable', current_pilot_ucid = NULL
                    WHERE id = %s
                """, (ac['id'],))

                # Close the flight record
                result = 'crashed' if event_name == 'crash' else 'ejected'
                await conn.execute("""
                    UPDATE mayfly_flights
                    SET result = %s,
                        signed_in_at = NOW() AT TIME ZONE 'utc'
                    WHERE aircraft_id = %s AND pilot_ucid = %s AND signed_in_at IS NULL
                """, (result, ac['id'], ucid))

                self.log.info(
                    f"Mayfly: {ac['tail_number']} marked unserviceable "
                    f"after {event_name} by {ucid}"
                )

        self.mark_fleet_dirty()
