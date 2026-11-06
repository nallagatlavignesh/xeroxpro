-- daily_closings gains opening_cash (rebuilt so the stored DDL matches the models exactly)
ALTER TABLE daily_closings RENAME TO daily_closings_old;
CREATE TABLE daily_closings (
	id INTEGER NOT NULL, 
	closing_date VARCHAR NOT NULL, 
	opening_cash INTEGER NOT NULL, 
	expected_cash INTEGER NOT NULL, 
	counted_cash INTEGER NOT NULL, 
	difference INTEGER NOT NULL, 
	notes VARCHAR NOT NULL, 
	created_at VARCHAR NOT NULL, 
	CONSTRAINT pk_daily_closings PRIMARY KEY (id), 
	CONSTRAINT uq_daily_closings_closing_date UNIQUE (closing_date)
);
INSERT INTO daily_closings (id, closing_date, opening_cash, expected_cash, counted_cash, difference, notes, created_at)
  SELECT id, closing_date, 0, expected_cash, counted_cash, difference, notes, created_at FROM daily_closings_old;
DROP TABLE daily_closings_old;
