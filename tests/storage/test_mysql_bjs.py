"""The deployed BJS process shares the API database configuration."""

from test_bjs_execution import create_demo_run, prepare_script_tree, run_script


def test_bjs_process_executes_mysql_run(mysql_repository, mysql_config, tmp_path):
    _, run = create_demo_run(mysql_repository)
    root = prepare_script_tree(
        tmp_path,
        {
            "AGENTGATE_DB_TYPE": "tdsql",
            "AGENTGATE_TDSQL_URL": mysql_config.url,
            "AGENTGATE_TDSQL_USER": mysql_config.username,
            "AGENTGATE_TDSQL_PASSWORD": mysql_config.password.get_secret_value(),
            "AGENT_TASK_DISPATCHER_TYPE": "bjs",
        },
    )
    result = run_script(root, "execute-run", run.id)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "completed"
    assert mysql_repository.get_run(run.id).status == "completed"
    assert mysql_repository.list_results(run.id)
    assert mysql_repository.list_traces(run.id)
    repeated = run_script(root, "execute-run", run.id)
    assert repeated.returncode == 0, repeated.stderr
