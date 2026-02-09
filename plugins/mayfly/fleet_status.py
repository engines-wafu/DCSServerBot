from core import report
from datetime import datetime, timezone
from psycopg.rows import dict_row


STATUS_EMOJI = {
    'serviceable': '\u2705',         # green check
    'signed_out': '\u2708\ufe0f',    # airplane
    'unserviceable': '\u26a0\ufe0f', # warning
    'grounded': '\u26d4',            # no entry
    'limited': '\U0001f7e1',         # yellow circle
}


class FleetBoardInit(report.EmbedElement):
    async def render(self, squadron_name: str, squadron_id: int):
        self.embed.set_author(name=f"{squadron_name} \u2014 Fleet Status Board")
        self.embed.description = ""


class FleetBoardAircraft(report.EmbedElement):
    async def render(self, squadron_id: int, **kwargs):
        async with self.apool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT a.tail_number, a.aircraft_type, a.status,
                           a.current_pilot_ucid, a.total_flight_hours,
                           p.name AS pilot_name,
                           (SELECT COUNT(*) FROM mayfly_defects d
                            WHERE d.aircraft_id = a.id AND d.status = 'open') AS open_defects,
                           (SELECT COUNT(*) FROM mayfly_limitations l
                            WHERE l.aircraft_id = a.id AND l.active = TRUE) AS active_limits
                    FROM mayfly_aircraft a
                    LEFT JOIN players p ON p.ucid = a.current_pilot_ucid
                    WHERE a.squadron_id = %s AND a.written_off_at IS NULL
                    ORDER BY a.tail_number
                """, (squadron_id,))
                aircraft = await cursor.fetchall()

        if not aircraft:
            self.add_field(name="No Aircraft", value="No aircraft registered for this squadron.", inline=False)
            return

        # Count by status for summary
        total = len(aircraft)
        svc = sum(1 for a in aircraft if a['status'] == 'serviceable')
        out = sum(1 for a in aircraft if a['current_pilot_ucid'] is not None)
        unsvc = sum(1 for a in aircraft if a['status'] == 'unserviceable')
        gnd = sum(1 for a in aircraft if a['status'] == 'grounded')
        ltd = sum(1 for a in aircraft if a['status'] == 'limited')

        summary_parts = [f"**{total}** aircraft"]
        if svc:
            summary_parts.append(f"\u2705 {svc}")
        if out:
            summary_parts.append(f"\u2708\ufe0f {out}")
        if unsvc:
            summary_parts.append(f"\u26a0\ufe0f {unsvc}")
        if ltd:
            summary_parts.append(f"\U0001f7e1 {ltd}")
        if gnd:
            summary_parts.append(f"\u26d4 {gnd}")

        self.embed.description = " | ".join(summary_parts)

        # Build per-aircraft fields
        for ac in aircraft:
            if ac['current_pilot_ucid']:
                emoji = STATUS_EMOJI.get('signed_out', '\u2753')
            else:
                emoji = STATUS_EMOJI.get(ac['status'], '\u2753')
            name = f"{emoji} {ac['tail_number']}"

            lines = [ac['aircraft_type']]
            if ac['current_pilot_ucid'] and ac['pilot_name']:
                lines.append(f"Pilot: {ac['pilot_name']}")
            elif ac['status'] not in ('serviceable',):
                lines.append(ac['status'].replace('_', ' ').title())

            if ac['open_defects']:
                lines.append(f"Defects: {ac['open_defects']}")
            if ac['active_limits']:
                lines.append(f"Limits: {ac['active_limits']}")

            hours = float(ac['total_flight_hours']) if ac['total_flight_hours'] else 0
            lines.append(f"{hours:.1f} hrs")

            self.add_field(name=name, value="\n".join(lines), inline=True)


class FleetBoardFooter(report.EmbedElement):
    async def render(self, **kwargs):
        self.embed.set_footer(text=f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%Mz')}")
