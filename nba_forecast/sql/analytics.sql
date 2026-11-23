CREATE TABLE sources (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
) STRICT;

CREATE TABLE teams (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
) STRICT;

CREATE TABLE games (
    game_id TEXT PRIMARY KEY,
    season TEXT NOT NULL,
    start TEXT NOT NULL,
    slate_date TEXT NOT NULL,
    home_id TEXT NOT NULL REFERENCES teams,
    away_id TEXT NOT NULL REFERENCES teams,
    status TEXT NOT NULL CHECK (status IN ('scheduled','awaiting_final','final','archived')),
    home_score INTEGER CHECK (home_score >= 0),
    away_score INTEGER CHECK (away_score >= 0),
    completed_at TEXT,
    CHECK (home_id <> away_id),
    CHECK ((status = 'final') = (home_score IS NOT NULL AND away_score IS NOT NULL AND completed_at IS NOT NULL)),
    CHECK (status <> 'final' OR (home_score <> away_score AND completed_at >= start))
) STRICT;

CREATE TABLE team_games (
    game_id TEXT NOT NULL REFERENCES games,
    side TEXT NOT NULL CHECK (side IN ('home','away')),
    team_id TEXT NOT NULL REFERENCES teams,
    points INTEGER NOT NULL CHECK (points >= 0),
    fgm INTEGER NOT NULL, fga INTEGER NOT NULL,
    threem INTEGER NOT NULL, threea INTEGER NOT NULL,
    ftm INTEGER NOT NULL, fta INTEGER NOT NULL,
    oreb INTEGER NOT NULL, dreb INTEGER NOT NULL,
    ast INTEGER NOT NULL, stl INTEGER NOT NULL,
    tov INTEGER NOT NULL, largest_lead INTEGER NOT NULL,
    PRIMARY KEY (game_id, side),
    UNIQUE (game_id, team_id)
) STRICT;

CREATE TABLE issued_forecasts (
    forecast_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games,
    home_id TEXT NOT NULL REFERENCES teams,
    away_id TEXT NOT NULL REFERENCES teams,
    issued_at TEXT NOT NULL,
    cutoff TEXT NOT NULL,
    captured_start TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_sha256 TEXT,
    parameter_hash TEXT,
    home_probability REAL NOT NULL CHECK (home_probability BETWEEN 0 AND 1),
    away_probability REAL NOT NULL CHECK (away_probability BETWEEN 0 AND 1),
    base_home_probability REAL CHECK (base_home_probability BETWEEN 0 AND 1),
    eligible INTEGER NOT NULL CHECK (eligible IN (0,1)),
    injury_status TEXT,
    record_json TEXT NOT NULL,
    source_path TEXT NOT NULL REFERENCES sources,
    CHECK (abs(home_probability + away_probability - 1) <= 1e-12),
    CHECK (issued_at < captured_start AND cutoff <= issued_at),
    CHECK (home_id <> away_id)
) STRICT;

CREATE INDEX issued_game_time ON issued_forecasts(game_id, issued_at DESC);

CREATE TABLE upcoming (
    game_id TEXT PRIMARY KEY REFERENCES games,
    forecast_id TEXT NOT NULL UNIQUE REFERENCES issued_forecasts
) STRICT;

CREATE TABLE evaluation_runs (
    run_id TEXT PRIMARY KEY,
    season TEXT NOT NULL,
    evidence TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_sha256 TEXT,
    source_path TEXT NOT NULL REFERENCES sources
) STRICT;

CREATE TABLE evaluation_predictions (
    run_id TEXT NOT NULL REFERENCES evaluation_runs,
    game_id TEXT NOT NULL REFERENCES games,
    home_probability REAL NOT NULL CHECK (home_probability BETWEEN 0 AND 1),
    away_probability REAL NOT NULL CHECK (away_probability BETWEEN 0 AND 1),
    cutoff TEXT NOT NULL,
    captured_start TEXT NOT NULL,
    eligible INTEGER NOT NULL CHECK (eligible IN (0,1)),
    injury_status TEXT,
    CHECK (abs(home_probability + away_probability - 1) <= 1e-12),
    CHECK (cutoff < captured_start),
    PRIMARY KEY (run_id, game_id)
) STRICT;

CREATE TABLE team_ratings (
    season TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams,
    elo REAL NOT NULL,
    games INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    source_path TEXT NOT NULL REFERENCES sources,
    PRIMARY KEY (season, team_id)
) STRICT;

CREATE TABLE rating_history (
    season TEXT NOT NULL,
    game_id TEXT NOT NULL REFERENCES games,
    team_id TEXT NOT NULL REFERENCES teams,
    effective_at TEXT NOT NULL,
    elo REAL NOT NULL,
    change REAL,
    PRIMARY KEY (game_id, team_id)
) STRICT;

CREATE VIEW latest_pregame AS
WITH ordered AS (
    SELECT f.*, row_number() OVER (
        PARTITION BY f.game_id ORDER BY f.issued_at DESC, f.forecast_id
    ) AS revision
    FROM issued_forecasts f JOIN games g USING (game_id)
    WHERE g.status IN ('final', 'awaiting_final') AND f.home_id = g.home_id AND f.away_id = g.away_id
        AND f.issued_at < g.start
)
SELECT * FROM ordered WHERE revision = 1;

CREATE VIEW latest_issued AS
SELECT f.* FROM latest_pregame f JOIN games g USING (game_id) WHERE g.status = 'final';

CREATE VIEW ranked_teams AS
SELECT r.*, t.name, rank() OVER (PARTITION BY r.season ORDER BY r.elo DESC) AS elo_rank
FROM team_ratings r JOIN teams t USING (team_id);

CREATE VIEW evaluation_rows AS
SELECT g.game_id, g.season, 'issued' AS evidence, f.model_version, f.model_sha256,
    f.home_probability, f.away_probability, f.cutoff, f.captured_start, f.eligible,
    f.injury_status, g.home_score > g.away_score AS home_win
FROM latest_issued f JOIN games g USING (game_id)
UNION ALL
SELECT g.game_id, g.season, r.evidence, r.model_version, r.model_sha256,
    p.home_probability, p.away_probability, p.cutoff, p.captured_start, p.eligible,
    p.injury_status, g.home_score > g.away_score AS home_win
FROM evaluation_predictions p JOIN evaluation_runs r USING (run_id)
JOIN games g USING (game_id);

CREATE VIEW game_slate AS
SELECT g.*, h.name AS home, a.name AS away, u.forecast_id
FROM games g JOIN teams h ON h.team_id = g.home_id
JOIN teams a ON a.team_id = g.away_id LEFT JOIN upcoming u USING (game_id)
WHERE g.status <> 'archived';
