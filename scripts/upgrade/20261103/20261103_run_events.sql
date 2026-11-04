-- Additive MySQL/TDSQL upgrade. Run before deploying execution-flow logging.
-- CREATE IF NOT EXISTS also makes a repeated application safe.
CREATE TABLE IF NOT EXISTS agentgate_run_events (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    run_key BINARY(32) NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NULL,
    request_key BINARY(32) NULL,
    request_id LONGTEXT COLLATE utf8mb4_bin NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    stage VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    started_at DATETIME(6) NOT NULL,
    ended_at DATETIME(6) NULL,
    duration_ms DOUBLE NULL,
    error_code LONGTEXT COLLATE utf8mb4_bin NULL,
    message LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_run_events PRIMARY KEY (id_key),
    INDEX ix_run_events_run_time (run_key, started_at, id_key),
    INDEX ix_run_events_request (request_key, user_team_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;
