"""
Fix for duplicate pilot awards after Mayfly migration.

The migration can create duplicate awards when the same award exists
with different granted_at timestamps (e.g., original 2024 date + migration date).

This script keeps only the earliest grant for each (player, award) pair.

Run from the DCSServerBot directory:
    python plugins/logbook/db/fix_duplicate_awards.py

Or specify a database URL directly:
    python plugins/logbook/db/fix_duplicate_awards.py --target "postgresql://user:pass@host/db"
"""
import sys
import re


def get_db_url():
    """Read database URL from config/nodes.yaml"""
    try:
        with open('config/nodes.yaml', 'r') as f:
            content = f.read()
        match = re.search(r'url:\s*(postgres\S+)', content)
        if not match:
            print("ERROR: No database URL found in config/nodes.yaml")
            sys.exit(1)
        url = match.group(1)
        if url.startswith('postgres://'):
            url = 'postgresql://' + url[len('postgres://'):]
        return url
    except FileNotFoundError:
        print("ERROR: config/nodes.yaml not found. Run this from the DCSServerBot directory.")
        sys.exit(1)


def main():
    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg not installed. Run: pip install psycopg[binary]")
        sys.exit(1)

    if '--target' in sys.argv:
        idx = sys.argv.index('--target')
        db_url = sys.argv[idx + 1]
    else:
        db_url = get_db_url()

    print("Connecting to database...")
    conn = psycopg.connect(db_url)
    conn.autocommit = True

    # Find duplicates
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pa.player_ucid, p.name, a.name as award_name,
                   COUNT(*) as copies,
                   MIN(pa.granted_at) as earliest,
                   MAX(pa.granted_at) as latest
            FROM logbook_pilot_awards pa
            JOIN players p ON pa.player_ucid = p.ucid
            JOIN logbook_awards a ON pa.award_id = a.id
            GROUP BY pa.player_ucid, pa.award_id, p.name, a.name
            HAVING COUNT(*) > 1
            ORDER BY p.name, a.name
        """)
        dupes = cur.fetchall()

    if not dupes:
        print("No duplicate awards found. Nothing to fix.")
        conn.close()
        return

    print(f"\nFound {len(dupes)} duplicate award(s):\n")
    total_removals = 0
    print(f"  {'Pilot':<25} {'Award':<30} {'Copies':>6} {'Keep (earliest)':>20} {'Remove (latest)':>20}")
    print(f"  {'-'*25} {'-'*30} {'-'*6} {'-'*20} {'-'*20}")
    for ucid, name, award, copies, earliest, latest in dupes:
        removals = copies - 1
        total_removals += removals
        print(f"  {name:<25} {award:<30} {copies:>6} {earliest.strftime('%Y-%m-%d %H:%M'):>20} {latest.strftime('%Y-%m-%d %H:%M'):>20}")

    print(f"\n  Total rows to remove: {total_removals}")

    if '--dry-run' in sys.argv:
        print("\n  Dry run — no changes made.")
        conn.close()
        return

    # Apply fix: delete all but earliest grant for each (player, award) pair
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM logbook_pilot_awards pa
            WHERE EXISTS (
                SELECT 1 FROM logbook_pilot_awards pa2
                WHERE pa2.player_ucid = pa.player_ucid
                AND pa2.award_id = pa.award_id
                AND pa2.granted_at < pa.granted_at
            )
        """)
        removed = cur.rowcount

    print(f"\n  Removed {removed} duplicate award rows.")

    # Verify
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT player_ucid, award_id
                FROM logbook_pilot_awards
                GROUP BY player_ucid, award_id
                HAVING COUNT(*) > 1
            ) dupes
        """)
        remaining = cur.fetchone()[0]

    if remaining == 0:
        print("  Verified: no duplicates remain.")
    else:
        print(f"  WARNING: {remaining} duplicate(s) still remain!")

    conn.close()
    print("\nDone. Run /logbook pilot to verify awards are correct.")


if __name__ == '__main__':
    main()
