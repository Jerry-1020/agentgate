"""Loopback-only peer. Directory shapes follow the supplied document; no authentication."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response


def create_app():
    fixtures = json.loads(Path(__file__).with_name("fixtures.json").read_text())
    app = FastAPI(title="Agent platform local simulated peer")
    instances, sessions = {}, {}
    events = []
    app.state.events = events
    app.state.instances = instances

    def wrapped(data):
        return {"code": "0", "message": "success", "data": data}

    def page_of(records, page, limit):
        return {
            "records": records[(page - 1) * limit : page * limit],
            "total": len(records),
            "current": page,
            "size": limit,
            "pages": (len(records) + limit - 1) // limit,
        }

    def agent(agent_id):
        result = next((a for a in fixtures["agents"] if a["id"] == agent_id), None)
        if result is None:
            raise HTTPException(404, "unknown agent")
        return result

    def branches():
        return {"branch-main", "branch-review"}

    def create(agent_id, version, task_id, branch=None):
        record = agent(agent_id)
        if version not in {v["agentVersion"] for v in fixtures["versions"]}:
            raise HTTPException(404, "unknown version")
        if (record["agentType"] == "abcclaw") != (branch is not None):
            raise HTTPException(422, "wrong instance type")
        if branch is not None and branch not in branches():
            raise HTTPException(404, "unknown branch")
        name = "mock-" + uuid4().hex
        instances[name] = {
            "agentId": agent_id,
            "agentVersion": version,
            "branchId": branch,
            "type": record["agentType"],
            "taskId": task_id,
        }
        events.append({"operation": "create", "agentName": name, **instances[name]})
        return wrapped({"code": "0", "data": {"agentName": name}})

    @app.get("/health")
    @app.get("/mock/capabilities")
    def health():
        return {"mock": True, "protocol": "agentgate-platform-mock-v1"}

    @app.get("/mock/evidence")
    def evidence():
        return {"events": events, "active_instances": len(instances)}

    @app.get("/web/ops/team/getTeamRole")
    def teams(page: int = Query(1, ge=1), limit: int = Query(300, ge=1, le=1000)):
        rows = [{"id": "membership-" + t["teamId"], **t} for t in fixtures["teams"]]
        return wrapped(page_of(rows, page, limit))

    @app.get("/web/agent/agents")
    def agents(
        teamId: str,
        name: str = "",
        page: int = Query(1, ge=1),
        limit: int = Query(1000, ge=1, le=1000),
    ):
        return page_of(
            [a for a in fixtures["agents"] if a["teamId"] == teamId and name in a["name"]],
            page,
            limit,
        )

    @app.get("/web/agent/getAgentVersionList")
    def versions(agentId: str):
        if agent(agentId)["agentType"] == "abcclaw":
            raise HTTPException(422, "use branch versions")
        return wrapped(fixtures["versions"])

    @app.get("/web/abcclaw/v2/branchTree")
    def branch_tree(agentId: str):
        if agent(agentId)["agentType"] != "abcclaw":
            raise HTTPException(422, "not abcclaw")
        return wrapped(fixtures["branches"])

    @app.get("/web/abcclaw/v2/listVersions")
    def branch_versions(agentId: str, branchId: str):
        branch_tree(agentId)
        if branchId not in branches():
            raise HTTPException(404, "unknown branch")
        return wrapped([{**v, "branchId": branchId} for v in fixtures["versions"]])

    @app.post("/web/agent_endpoint/createAgent")
    async def create_workflow(request: Request, taskId: str):
        body = await request.json()
        if set(body) != {"agentId", "agentVersion"}:
            raise HTTPException(422, "expected agentId and agentVersion only")
        return create(body["agentId"], body["agentVersion"], taskId)

    @app.post("/mock/abcclaw/instances")
    async def create_claw(request: Request, taskId: str):
        body = await request.json()
        if set(body) != {"agentId", "agentVersion", "branchId"}:
            raise HTTPException(422, "invalid mock abcclaw identity")
        return create(body["agentId"], body["agentVersion"], taskId, body["branchId"])

    @app.get("/web/agent_endpoint/deleteAgent")
    def delete(agentName: str):
        instances.pop(agentName, None)
        for key in [key for key, value in sessions.items() if value == agentName]:
            sessions.pop(key)
        events.append({"operation": "delete", "agentName": agentName})
        return wrapped({"code": "0", "data": {}})

    def instance(name):
        if name not in instances:
            raise HTTPException(404, "unknown instance")
        return instances[name]

    @app.get("/agent-api/{name}/chatabc/health_check")
    def ready(name: str):
        instance(name)
        return wrapped({"data": {"status": "ok"}})

    @app.post("/agent-api/{name}/chatabc/init_session")
    async def init(name: str, request: Request):
        instance(name)
        await request.json()
        session = uuid4().hex
        sessions[session] = name
        events.append({"operation": "init", "agentName": name, "session": session})
        return wrapped({"data": {"session_id": session}})

    @app.post("/agent-api/{name}/chatabc/chat")
    @app.post("/agent-api/{name}/api/v1/message")
    async def chat(name: str, request: Request):
        record = instance(name)
        body = await request.json()
        claw = record["type"] == "abcclaw"
        data = body if claw else body["data"]
        session = data["sessionId"] if claw else data["session_id"]
        if not claw and sessions.get(session) != name:
            raise HTTPException(422, "unknown session")
        text = data["txt"]
        events.append({"operation": "chat", "agentName": name, "session": session, "input": text})
        if text == "模拟失败":
            return Response(
                'event: failed\ndata: {"message":"simulated failure"}\n\n',
                media_type="text/event-stream",
            )
        output = f"模拟回复[{record['agentId']}|{record['branchId'] or '-'}|{record['agentVersion']}]：{text}"
        message = (
            {"status": "completed", "output": output}
            if claw
            else {"node_id": "end", "additional_kwargs": {"node_output": {"output": output}}}
            if record["type"] == "workflow"
            else {"content": output}
        )
        if claw:
            wire = (
                "data: "
                + json.dumps({"event": "message", "data": message}, ensure_ascii=False)
                + '\n\ndata: {"event":"done","data":"[DONE]"}\n\n'
            )
        else:
            wire = (
                "event: message\ndata: "
                + json.dumps(message, ensure_ascii=False)
                + "\n\nevent: done\ndata: [DONE]\n\n"
            )
        return Response(wire, media_type="text/event-stream")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8119, access_log=False)
