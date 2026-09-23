CREATE TABLE IF NOT EXISTS agentgate_api_keys (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    scope VARCHAR(16) NOT NULL,
    provider_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    metadata_payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    encrypted_api_key LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_api_keys PRIMARY KEY (id_key),
    INDEX ix_api_keys_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_dataset_versions (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    dataset_key BINARY(32) NOT NULL,
    dataset_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    version BIGINT DEFAULT NULL,
    status VARCHAR(16) NOT NULL,
    draft_slot SMALLINT DEFAULT NULL,
    created_at DATETIME(6) NOT NULL,
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_dataset_versions PRIMARY KEY (id_key),
    CONSTRAINT uq_dataset_publication UNIQUE (dataset_key, version),
    CONSTRAINT uq_dataset_draft UNIQUE (dataset_key, draft_slot),
    INDEX ix_dataset_versions_lookup (dataset_key, status, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_datasets (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    archived SMALLINT NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_datasets PRIMARY KEY (id_key),
    INDEX ix_datasets_team_updated (user_team_key, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_evaluator_drafts (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    evaluator_key BINARY(32) NOT NULL,
    evaluator_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_evaluator_drafts PRIMARY KEY (id_key),
    CONSTRAINT uq_evaluator_draft UNIQUE (evaluator_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_evaluator_versions (
    evaluator_key BINARY(32) NOT NULL,
    version BIGINT NOT NULL,
    evaluator_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_evaluator_versions PRIMARY KEY (evaluator_key, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_evaluators (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    source VARCHAR(16) NOT NULL,
    enabled SMALLINT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_evaluators PRIMARY KEY (id_key),
    INDEX ix_evaluators_team_updated (user_team_key, enabled, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_results (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    run_key BINARY(32) NOT NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    case_key BINARY(32) NOT NULL,
    case_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    trace_key BINARY(32) NOT NULL,
    trace_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    evaluator_key BINARY(32) NOT NULL,
    evaluator_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_results PRIMARY KEY (id_key),
    CONSTRAINT uq_result_run_case_evaluator UNIQUE (run_key, case_key, evaluator_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_run_asset_refs (
    reference_key BINARY(32) NOT NULL,
    run_key BINARY(32) NOT NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    asset_lookup_key BINARY(32) NOT NULL,
    asset_kind VARCHAR(16) NOT NULL,
    source_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    asset_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    version LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    CONSTRAINT pk_agentgate_run_asset_refs PRIMARY KEY (reference_key),
    INDEX ix_run_refs_lookup (asset_lookup_key, content_sha256, run_key),
    INDEX ix_run_refs_run (run_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_runs (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    scheduled_for DATETIME(6) DEFAULT NULL,
    user_team_key BINARY(32) NOT NULL,
    user_team_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    user_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    api_key LONGTEXT COLLATE utf8mb4_bin DEFAULT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_runs PRIMARY KEY (id_key),
    INDEX ix_runs_due (status, scheduled_for, created_at),
    INDEX ix_runs_status_created (status, created_at),
    INDEX ix_runs_team_created (user_team_key, created_at),
    INDEX ix_runs_team_status (user_team_key, status, created_at),
    INDEX ix_runs_apikey_status (api_key(191), status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_skill_analysis_reports (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    target_descriptor_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_skill_analysis_reports PRIMARY KEY (id_key),
    INDEX ix_skill_reports_target (target_descriptor_sha256, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_skill_analysis_reviews (
    report_key BINARY(32) NOT NULL,
    finding_key BINARY(32) NOT NULL,
    report_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    finding_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    reviewed_at DATETIME(6) NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_skill_analysis_reviews PRIMARY KEY (report_key, finding_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_target_descriptors (
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    target_ref_key BINARY(32) NOT NULL,
    source_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    target_type VARCHAR(16) NOT NULL,
    external_target_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    external_version_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    fetched_at DATETIME(6) NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_target_descriptors PRIMARY KEY (content_sha256),
    INDEX ix_target_ref (target_ref_key, fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_traces (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    run_key BINARY(32) NOT NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    case_key BINARY(32) NOT NULL,
    case_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_traces PRIMARY KEY (id_key),
    CONSTRAINT uq_trace_run_case UNIQUE (run_key, case_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_evaluation_task_runs (
    run_key BINARY(32) NOT NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    task_key BINARY(32) NOT NULL,
    task_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_evaluation_task_runs PRIMARY KEY (run_key),
    INDEX ix_agentgate_evaluation_task_runs_task (task_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_evaluation_tasks (
    id_key BINARY(32) NOT NULL,
    id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_evaluation_tasks PRIMARY KEY (id_key),
    INDEX ix_agentgate_evaluation_tasks_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS agentgate_optimization_reports (
    evidence_key_digest BINARY(32) NOT NULL,
    evidence_key LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    run_key BINARY(32) NOT NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT pk_agentgate_optimization_reports PRIMARY KEY (evidence_key_digest),
    INDEX ix_agentgate_optimization_reports_run (run_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;
