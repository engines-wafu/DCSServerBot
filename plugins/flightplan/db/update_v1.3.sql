-- Flight Plan Plugin v1.3 Update
-- Add foreign key constraint on server_name

ALTER TABLE flightplan_plans
    ADD CONSTRAINT fk_flightplan_plans_server
    FOREIGN KEY (server_name)
    REFERENCES servers(server_name)
    ON UPDATE CASCADE
    ON DELETE CASCADE;
