export type RunEvent = {
  id: string;
  request_id: string | null;
  run_id: string | null;
  stage: string;
  name: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  case_id: string | null;
  turn_id: string | null;
  evaluator_id: string | null;
  bjs_job_id?: string | null;
  bjs_batch_number?: string | null;
  agent_id?: string | null;
  pod_task_id?: string | null;
  pod_name?: string | null;
  attempt: number;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  message: string;
};

const stages = [
  { id: 'submission', name: '提交任务', stages: ['submission'] },
  { id: 'dispatch', name: '等待执行', stages: ['schedule', 'waiting', 'dispatch', 'worker_wait'] },
  {
    id: 'preparation',
    name: '准备智能体',
    stages: ['initialization', 'validation', 'pod_create', 'pod_health', 'pod_settle'],
  },
  { id: 'samples', name: '执行样本', stages: ['target', 'trace', 'turn', 'node', 'retry'] },
  {
    id: 'evaluation',
    name: '评估与汇总',
    stages: ['evaluation', 'evaluator', 'result_save', 'summary'],
  },
] as const;
const wrappers = new Set(['run', 'worker', 'execution']);
const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);

export function executionTiming(events: RunEvent[], runStatus: string) {
  const run = events
    .filter((event) => event.stage === 'run')
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))[0];
  const unknownEnd = Boolean(
    run && (run.status === 'interrupted' || (!run.ended_at && terminalStatuses.has(runStatus))),
  );
  const running = Boolean(run && !run.ended_at && !unknownEnd);
  const endedAt = unknownEnd ? null : (run?.ended_at ?? null);
  return {
    startedAt: run?.started_at ?? null,
    endedAt,
    durationMs:
      run && endedAt
        ? (run.duration_ms ?? Math.max(0, Date.parse(endedAt) - Date.parse(run.started_at)))
        : null,
    running,
    unknownEnd,
  };
}

export function groupExecutionFlow(events: RunEvent[], runStatus: string) {
  const terminal = terminalStatuses.has(runStatus);
  return stages.map((stage, index) => {
    const rows = events
      .filter(
        (event) =>
          (stage.stages as readonly string[]).includes(event.stage) ||
          (stage.id === 'samples' &&
            !wrappers.has(event.stage) &&
            !stages.some((item) => (item.stages as readonly string[]).includes(event.stage))),
      )
      .sort(
        (a, b) =>
          Date.parse(a.started_at) - Date.parse(b.started_at) ||
          a.attempt - b.attempt ||
          a.id.localeCompare(b.id),
      );
    // A successful retry resolves the earlier attempt, while its error stays in the details.
    const latest = new Map<string, RunEvent>();
    for (const event of rows) {
      latest.set(
        JSON.stringify([
          event.stage,
          event.case_id,
          event.turn_id,
          event.evaluator_id,
          event.stage === 'dispatch' ? null : event.name,
          event.stage === 'node' || event.stage === 'turn' ? event.id : null,
        ]),
        event,
      );
    }
    const current = [...latest.values()];
    const hasOpen = rows.some((event) => !event.ended_at);
    const failed = current.some((event) => event.status === 'failed');
    const interrupted = current.some((event) => event.status === 'interrupted');
    const cancelled = current.some((event) => event.status === 'cancelled');
    const issues = rows.filter((event) =>
      ['failed', 'interrupted', 'cancelled'].includes(event.status),
    );
    const laterStarted = stages
      .slice(index + 1)
      .some((item) =>
        events.some((event) => (item.stages as readonly string[]).includes(event.stage)),
      );
    const status = !rows.length
      ? terminal || !events.length || laterStarted
        ? 'uncollected'
        : 'pending'
      : hasOpen
        ? terminal
          ? 'unknown'
          : 'running'
        : failed
          ? 'failed'
          : interrupted
            ? 'interrupted'
            : cancelled
              ? 'cancelled'
              : 'completed';
    const startedAt = rows[0]?.started_at ?? null;
    const endedAt =
      !rows.length || hasOpen || interrupted
        ? null
        : rows.reduce(
            (end, row) => (Date.parse(row.ended_at!) > Date.parse(end) ? row.ended_at! : end),
            rows[0].ended_at!,
          );
    return {
      id: stage.id,
      name: stage.name,
      rows,
      status,
      issues,
      startedAt,
      endedAt,
      durationMs:
        startedAt && endedAt ? Math.max(0, Date.parse(endedAt) - Date.parse(startedAt)) : null,
      expanded: ['running', 'failed', 'interrupted', 'unknown'].includes(status),
    };
  });
}

export type FlowNode = ReturnType<typeof groupExecutionFlow>[number];

export function executionReferences(events: RunEvent[], snapshotAgent?: string) {
  const agents = [
    ...new Set(
      [...events.map((event) => event.agent_id), snapshotAgent].filter((id): id is string =>
        Boolean(id),
      ),
    ),
  ];
  const requests = [
    ...new Set(events.map((event) => event.request_id).filter((id): id is string => Boolean(id))),
  ];
  const batches = new Map<string, { number: string; job: string | null; attempt: number }>();
  const podGroups = new Map<
    string,
    { agentId: string | null; taskId: string | null; names: Set<string> }
  >();
  for (const event of events) {
    if (event.pod_task_id || event.pod_name) {
      const agentId = event.agent_id || snapshotAgent || null;
      const taskId = event.pod_task_id || null;
      const key = JSON.stringify([agentId, taskId]);
      const pod = podGroups.get(key) ?? { agentId, taskId, names: new Set<string>() };
      if (event.pod_name) pod.names.add(event.pod_name);
      podGroups.set(key, pod);
    }
    if (event.bjs_batch_number) {
      batches.set(JSON.stringify([event.bjs_job_id, event.bjs_batch_number]), {
        number: event.bjs_batch_number,
        job: event.bjs_job_id ?? null,
        attempt: event.attempt,
      });
    }
  }
  const taskErrors = events.filter(
    (event) =>
      wrappers.has(event.stage) &&
      ['failed', 'interrupted', 'cancelled'].includes(event.status) &&
      event.message,
  );
  const pods = [...podGroups.values()].flatMap((pod) =>
    (pod.names.size ? [...pod.names] : [null]).map((name) => ({
      agentId: pod.agentId,
      taskId: pod.taskId,
      name,
    })),
  );
  return { requests, batches: [...batches.values()], agents, pods, taskErrors };
}
