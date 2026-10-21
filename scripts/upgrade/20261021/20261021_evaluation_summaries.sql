-- Additive MySQL migration; execute via inspected migration tool for repeatability.
-- Backfill is a separate explicitly authorized operation.
-- 在 init.sql 的基础上，优化页面加载性能添加的脚本，本脚本和 init.sql 合并成 init20261021.sql 脚本

CREATE TABLE IF NOT EXISTS agentgate_run_summaries (
    run_key BINARY(32) NOT NULL,
    run_id LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    display_payload LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    fallback_name LONGTEXT COLLATE utf8mb4_bin NOT NULL,
    total_cases BIGINT NOT NULL,
    overall_score DOUBLE,
    gate_reason VARCHAR(64),
    summary_version INTEGER,
    result_count BIGINT,
    source_results_sha256 CHAR(64),
    CONSTRAINT pk_agentgate_run_summaries PRIMARY KEY (run_key)
)ENGINE=InnoDB CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agentgate_run_case_progress (
    run_key BINARY(32) NOT NULL,
    case_key BINARY(32) NOT NULL,
    completed SMALLINT NOT NULL,
    CONSTRAINT pk_agentgate_run_case_progress PRIMARY KEY (run_key, case_key)
)ENGINE=InnoDB CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS agentgate_run_expected_evaluators (
    run_key BINARY(32) NOT NULL,
    evaluator_key BINARY(32) NOT NULL,
    CONSTRAINT pk_agentgate_run_expected_evaluators PRIMARY KEY (run_key, evaluator_key)
)ENGINE=InnoDB CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC COLLATE utf8mb4_bin;

ALTER TABLE agentgate_evaluation_tasks ADD COLUMN name LONGTEXT NULL, ADD COLUMN kind VARCHAR(16) NULL, ADD COLUMN first_run_key BINARY(32) NULL;

ALTER TABLE agentgate_evaluation_task_runs ADD COLUMN is_current SMALLINT NULL, ADD COLUMN position INTEGER NULL;

CREATE INDEX ix_task_runs_current_position ON agentgate_evaluation_task_runs(task_key,is_current,position);

ALTER TABLE agentgate_dataset_versions ADD COLUMN sample_count BIGINT NULL;
