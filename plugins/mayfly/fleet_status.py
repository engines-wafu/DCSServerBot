from core import report
from datetime import datetime, timezone
from psycopg.rows import dict_row


STATUS_EMOJI = {
    'serviceable': '\U0001f7e2',     # green circle
    'signed_out': '\U0001f535',      # blue circle
    'unserviceable': '\U0001f534',   # red circle
    'grounded': '\u26d4',            # no entry
    'limited': '\U0001f7e1',         # yellow circle
}

# Short display names for DCS module types
TYPE_SHORT = {
    'F-4E-45MC': 'Phantom',
    'AV-8B-NA': 'Harrier',
    'Mi-8MTV2': 'Sea King',
    'OH-58D': 'Lynx',
    'SA342M': 'Gazelle',
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
        svc = sum(1 for a in aircraft if a['status'] == 'serviceable' and not a['current_pilot_ucid'])
        out = sum(1 for a in aircraft if a['current_pilot_ucid'] is not None)
        unsvc = sum(1 for a in aircraft if a['status'] == 'unserviceable')
        gnd = sum(1 for a in aircraft if a['status'] == 'grounded')
        ltd = sum(1 for a in aircraft if a['status'] == 'limited')

        # Aircraft type for this squadron
        ac_type = aircraft[0]['aircraft_type']
        type_name = TYPE_SHORT.get(ac_type, ac_type)

        summary_parts = [f"**{total}x {type_name}**"]
        if svc:
            summary_parts.append(f"\U0001f7e2 {svc} svc")
        if out:
            summary_parts.append(f"\U0001f535 {out} flying")
        if unsvc:
            summary_parts.append(f"\U0001f534 {unsvc} u/s")
        if ltd:
            summary_parts.append(f"\U0001f7e1 {ltd} ltd")
        if gnd:
            summary_parts.append(f"\u26d4 {gnd} gnd")

        self.embed.description = " | ".join(summary_parts)

        # Build rows
        tail_w = max(len(ac['tail_number']) for ac in aircraft)
        tail_w = max(tail_w, 4)

        lines = []
        for ac in aircraft:
            if ac['current_pilot_ucid']:
                emoji = STATUS_EMOJI['signed_out']
            else:
                emoji = STATUS_EMOJI.get(ac['status'], '\u2753')

            tail = ac['tail_number']
            hours = float(ac['total_flight_hours']) if ac['total_flight_hours'] else 0

            # Build info string
            parts = []
            if ac['current_pilot_ucid'] and ac['pilot_name']:
                parts.append(f"\u2192 {ac['pilot_name']}")
            if ac['status'] == 'unserviceable' and not ac['current_pilot_ucid']:
                parts.append("U/S")
            if ac['status'] == 'grounded' and not ac['current_pilot_ucid']:
                parts.append("GND")
            if ac['status'] == 'limited' and not ac['current_pilot_ucid']:
                parts.append("LTD")
            if ac['open_defects']:
                parts.append(f"{ac['open_defects']} def")
            if ac['active_limits']:
                parts.append(f"{ac['active_limits']} lim")
            if hours > 0:
                parts.append(f"{hours:.1f}h")

            info = " \u2502 ".join(parts) if parts else ""
            line = f"{emoji} `{tail:<{tail_w}}`"
            if info:
                line += f"  {info}"
            lines.append(line)

        self.add_field(name="", value="\n".join(lines), inline=False)


class FleetBoardFooter(report.EmbedElement):
    async def render(self, **kwargs):
        self.embed.set_footer(text=f"Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%Mz')}")
