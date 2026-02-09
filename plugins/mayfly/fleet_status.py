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

        # Build tabular layout
        # Determine column widths from data
        tail_w = max(len(ac['tail_number']) for ac in aircraft)
        tail_w = max(tail_w, 4)  # min width for "TAIL" header

        rows = []
        for ac in aircraft:
            if ac['current_pilot_ucid']:
                status_ch = '\u2708'
            elif ac['status'] == 'serviceable':
                status_ch = '\u2705'
            elif ac['status'] == 'unserviceable':
                status_ch = '\u26a0'
            elif ac['status'] == 'grounded':
                status_ch = '\u26d4'
            else:
                status_ch = '\u2753'

            tail = ac['tail_number']
            hours = float(ac['total_flight_hours']) if ac['total_flight_hours'] else 0
            hrs_str = f"{hours:.1f}"

            # Notes column: pilot name, defects, limitations
            notes = []
            if ac['current_pilot_ucid'] and ac['pilot_name']:
                notes.append(ac['pilot_name'])
            elif ac['status'] not in ('serviceable', 'signed_out'):
                notes.append(ac['status'].replace('_', ' ').upper())
            if ac['open_defects']:
                notes.append(f"{ac['open_defects']} def")
            if ac['active_limits']:
                notes.append(f"{ac['active_limits']} lim")
            note_str = ", ".join(notes) if notes else ""

            rows.append((status_ch, tail, hrs_str, note_str))

        # Build the table as a code block
        hrs_w = max(len(r[2]) for r in rows)
        hrs_w = max(hrs_w, 3)

        lines = []
        for status_ch, tail, hrs_str, note_str in rows:
            line = f"{status_ch} {tail:<{tail_w}}  {hrs_str:>{hrs_w}}h"
            if note_str:
                line += f"  {note_str}"
            lines.append(line)

        self.add_field(name="", value="\n".join(lines), inline=False)


class FleetBoardFooter(report.EmbedElement):
    async def render(self, **kwargs):
        self.embed.set_footer(text=f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%Mz')}")
