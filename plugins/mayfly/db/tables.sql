-- Mayfly: Aircraft Management & MF700 Documentation Plugin
-- Version 0.1 - Alpha (Lite Mode)

-- Aircraft registry
CREATE TABLE IF NOT EXISTS mayfly_aircraft (
    id SERIAL PRIMARY KEY,
    squadron_id INTEGER NOT NULL REFERENCES squadrons(id) ON DELETE CASCADE,
    tail_number TEXT NOT NULL,
    aircraft_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'serviceable',
    current_pilot_ucid TEXT,
    total_flight_hours DECIMAL NOT NULL DEFAULT 0,
    persistence_key TEXT,
    livery_id TEXT,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    written_off_at TIMESTAMP,
    written_off_reason TEXT,
    FOREIGN KEY (current_pilot_ucid) REFERENCES players (ucid) ON UPDATE CASCADE ON DELETE SET NULL,
    UNIQUE (squadron_id, tail_number)
);
CREATE INDEX IF NOT EXISTS idx_mayfly_aircraft_squadron ON mayfly_aircraft (squadron_id);
CREATE INDEX IF NOT EXISTS idx_mayfly_aircraft_status ON mayfly_aircraft (status);
CREATE INDEX IF NOT EXISTS idx_mayfly_aircraft_tail ON mayfly_aircraft (tail_number);

-- Flight log per sortie
CREATE TABLE IF NOT EXISTS mayfly_flights (
    id SERIAL PRIMARY KEY,
    aircraft_id INTEGER NOT NULL REFERENCES mayfly_aircraft(id) ON DELETE CASCADE,
    pilot_ucid TEXT NOT NULL REFERENCES players (ucid) ON UPDATE CASCADE ON DELETE CASCADE,
    signed_out_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    signed_in_at TIMESTAMP,
    flight_hours DECIMAL,
    mission_id INTEGER,
    departure_airbase TEXT,
    arrival_airbase TEXT,
    result TEXT NOT NULL DEFAULT 'normal'
);
CREATE INDEX IF NOT EXISTS idx_mayfly_flights_aircraft ON mayfly_flights (aircraft_id);
CREATE INDEX IF NOT EXISTS idx_mayfly_flights_pilot ON mayfly_flights (pilot_ucid);
CREATE INDEX IF NOT EXISTS idx_mayfly_flights_signout ON mayfly_flights (signed_out_at);

-- F707 defect entries (Serial Number of Work)
CREATE TABLE IF NOT EXISTS mayfly_defects (
    id SERIAL PRIMARY KEY,
    aircraft_id INTEGER NOT NULL REFERENCES mayfly_aircraft(id) ON DELETE CASCADE,
    snow INTEGER NOT NULL,
    flight_id INTEGER REFERENCES mayfly_flights(id) ON DELETE SET NULL,
    reported_by_ucid TEXT REFERENCES players (ucid) ON UPDATE CASCADE ON DELETE SET NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    rectified_by_ucid TEXT REFERENCES players (ucid) ON UPDATE CASCADE ON DELETE SET NULL,
    rectified_at TIMESTAMP,
    deferred_category TEXT,
    deferred_until TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS idx_mayfly_defects_aircraft ON mayfly_defects (aircraft_id);
CREATE INDEX IF NOT EXISTS idx_mayfly_defects_status ON mayfly_defects (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mayfly_defects_snow ON mayfly_defects (aircraft_id, snow);

-- F703 limitations log
CREATE TABLE IF NOT EXISTS mayfly_limitations (
    id SERIAL PRIMARY KEY,
    aircraft_id INTEGER NOT NULL REFERENCES mayfly_aircraft(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    added_by_ucid TEXT REFERENCES players (ucid) ON UPDATE CASCADE ON DELETE SET NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    removed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mayfly_limitations_aircraft ON mayfly_limitations (aircraft_id);
CREATE INDEX IF NOT EXISTS idx_mayfly_limitations_active ON mayfly_limitations (active);
