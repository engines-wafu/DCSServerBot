from core import EventListener, Server, Player, event
from psycopg.rows import dict_row
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .commands import Mayfly


class MayflyEventListener(EventListener["Mayfly"]):
    """Event listener for Mayfly - tracks DCS flight events for aircraft management."""

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
