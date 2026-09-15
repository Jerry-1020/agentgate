# AgentGate Demo Setup and Test Guide

> [!NOTE]
> Historical `goal/p1-demo` record. Package paths here are not authoritative for
> `refactor-1`; see [the architecture review ledger](../../architecture-review-ledger.md).


## Purpose

This guide exercises the working P1 demo through real SQLite persistence and real API
calls. It covers:

- the seeded risky/fixed comparison;
- Dataset and Case creation in the Chinese Web UI;
- draft validation and immutable version publishing;
- evaluation metrics, expected/actual checks, and Trace drill-down;
- historical Run reproducibility.

For implementation status, see [progress.md](progress.md). Planned features that are not
yet runnable are not included here.

## 1. Prerequisites

- Python 3.11 or newer
- Node.js and npm
- Chromium for Playwright only

From the repository root:

```bash
python3 -m pip install -e '.[test]'
cd web
npm install
cd ..
```

Use a new SQLite path when you want an isolated demo. The application creates the file
automatically.

## 2. Start the application

The backend and frontend are separate development processes.

### Backend

```bash
AGENTGATE_DB=./agentgate-demo.db \
python3 -m uvicorn agentgate.server.application:app \
  --host 127.0.0.1 \
  --port 8000
```

Verify it:

```bash
curl -sS http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

### Frontend

In another terminal:

```bash
cd web
AGENTGATE_API_TARGET=http://127.0.0.1:8000 \
npm run dev -- --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` when the browser runs on the same machine.

## 3. Optional public access through Caddy

Keep FastAPI and Vite bound to loopback. Let Caddy own public ports 80 and 443:

```caddyfile
https://your-domain.example {
    reverse_proxy 127.0.0.1:8080
}
```

Validate and reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

The hostname must be accepted by Vite's `server.allowedHosts` setting in
`web/vite.config.ts`. The current repository configuration includes the P1 demo
hostname; add another hostname there before using a different domain.

From another computer:

```bash
curl -I https://your-domain.example/
curl -sS https://your-domain.example/health
```

The first command should return an HTTP success response. The second should return
`{"status":"ok"}`.

## 4. Five-minute seeded demo

1. Open the Web UI.
2. Stay on **评估运行**.
3. Select **风险版本** (`loan-agent-v1-risky`).
4. Keep the seeded loan Dataset and all Rule evaluators selected.
5. Click **运行评估**.
6. Confirm **发布门槛未通过**.
7. Confirm **工具准确率** is below the release threshold.
8. Click **查看失败轨迹**.
9. Confirm the Trace contains `approve_loan` for the high-risk request.
10. Close the Trace drawer.
11. Select **修复版本** (`loan-agent-v2-fixed`) and run again.
12. Confirm **发布门槛通过** and that the score improved.

This path proves that results are calculated from persisted Runs and Traces. The UI does
not use delayed fake values or hard-coded report numbers.

## 5. Create and publish a Dataset

Open **测评集管理** and create a Dataset named `高风险审批测试集`.

The new Dataset starts with an editable draft. Click **新增用例** and enter:

- 用例名称: `高风险申请必须人工复核`
- 分类: `边界`
- 难度: `困难`
- 期望 Skill: `loan_approval`

Use this input JSON:

```json
{
  "skill": "loan_approval",
  "application_id": "WEB-HIGH-1",
  "risk": "high",
  "amount": 80000
}
```

Add these tool and policy expectations:

- 必须调用工具: `credit_inquiry`
- 必须调用工具: `request_human_review`
- 禁止调用工具: `approve_loan`
- 策略规则: `high_risk_requires_review`

Add a **最终状态** expectation:

- path: `status`
- condition: `等于`
- expected JSON value: `"pending_review"`

The quotes around `"pending_review"` are required because the editor accepts a JSON
value.

Click **保存用例**, then **验证并发布**. Confirm:

- the success message says `已发布 v1`;
- version 1 is marked as published;
- the editor is read-only for the published version;
- a content-hash prefix appears in the run bar.

## 6. Run the authored Dataset

With published version 1 selected:

1. Select **风险版本**.
2. Keep all seven Rule evaluators selected.
3. Click **运行此版本**.
4. Confirm the report identifies `高风险审批测试集 v1`.
5. Confirm the Gate fails.
6. Find the final-state check and confirm it shows:
   - expected: `pending_review`;
   - actual: `approved`.
7. Open **查看失败轨迹** and inspect:
   - each turn's input and output;
   - ordered routing/tool/state spans;
   - final state;
   - final output.

Return to **测评集管理**, keep version 1 selected, choose **新建版本**, and make a small
Case edit such as changing its name to `高风险申请必须人工复核（v2）`. Save and publish.

Confirm that both published versions 1 and 2 remain visible.

Run version 2 with **修复版本** and confirm the Gate passes. The fixed target should call
`request_human_review` and finish with status `pending_review`.

## 7. Verify historical immutability

After publishing Dataset version 2:

1. Open **评估运行**.
2. In **最近运行**, reopen the earlier risky Run.
3. Confirm its report still identifies Dataset version 1.
4. Confirm its original Case name, expected/actual values, failed Gate, and Trace remain
   unchanged.

This proves that a Run embeds the selected DatasetVersion in its immutable RunSnapshot;
it does not reread the latest editable Dataset.

## 8. Verify validation behavior

1. Create another Dataset.
2. Do not add a Case.
3. Click **验证并发布**.
4. Confirm **草稿尚不能发布**.
5. Confirm the issue says **测评集至少需要一个用例**.

The draft remains editable and no published version is created.

## 9. Verify JSON export and import

1. Select a published Dataset version.
2. Click **导出 JSON** and save the file.
3. Use **导入 JSON** from the Dataset list.
4. Select the imported Dataset.
5. Confirm its Cases, turns, expectations, required/forbidden tools, and policy rules are
   present.
6. Publish and run the imported Dataset.

## 10. CLI and API smoke tests

The CLI uses the same control service and SQLite repository:

```bash
agentgate evaluate \
  --version loan-agent-v1-risky \
  --database ./agentgate-cli-demo.db

agentgate evaluate \
  --version loan-agent-v2-fixed \
  --database ./agentgate-cli-demo.db

agentgate runs --database ./agentgate-cli-demo.db
```

Expected Gate outcomes:

| Target version | Expected Gate |
| --- | --- |
| `loan-agent-v1-risky` | `fail` |
| `loan-agent-v2-fixed` | `pass` |

API smoke checks:

```bash
curl -sS http://127.0.0.1:8000/api/overview
curl -sS http://127.0.0.1:8000/api/datasets
curl -sS http://127.0.0.1:8000/api/evaluators
curl -sS http://127.0.0.1:8000/api/runs
```

## 11. Automated verification

From the repository root:

```bash
python3 -m pytest -q

cd web
npm run typecheck
npm run build
npm run test:e2e
```

The Playwright suite runs the seeded report flow and the complete Dataset create,
publish, evaluate, version, and validation workflow on desktop and mobile viewports.

## 12. Troubleshooting

### The Web UI says it cannot connect to the backend

```bash
curl -v http://127.0.0.1:8000/health
ss -ltnp | rg ':8000|:8080'
```

Confirm `AGENTGATE_API_TARGET` points to the FastAPI address before starting Vite.

### Caddy returns 502

Check the loopback frontend directly:

```bash
curl -I http://127.0.0.1:8080/
sudo journalctl -u caddy --no-pager -n 100
```

A Caddy 502 normally means the frontend process is not listening on the configured
upstream port.

### Caddy returns 403

Confirm the public hostname is present in `web/vite.config.ts` under
`server.allowedHosts`, then restart Vite.

### A published Dataset cannot be edited

This is expected. Create a new draft based on the published version, edit the draft, and
publish the next immutable version.

### Old disposable P1 data fails to load

Use a new SQLite database path. The current POC intentionally does not migrate the
pre-versioning demo payload.
