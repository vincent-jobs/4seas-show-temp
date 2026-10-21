-- Allow a complete snapshot even when its primary sensor (CO2) is unavailable.
ALTER TABLE samples ALTER COLUMN value DROP NOT NULL;
