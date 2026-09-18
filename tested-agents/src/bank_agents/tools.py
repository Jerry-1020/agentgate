"""Synthetic loan tools backed by SQLite; never call a bank production system."""
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class LoanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    amount: float = Field(gt=0, le=10000000, allow_inf_nan=False)
    purpose: str = Field(min_length=1, max_length=200)


def decision(application, profile):
    if profile["blocked"]:
        return "rejected"
    if profile["risk"] == "high" or profile["credit_score"] < 650 or application["amount"] > 200000:
        return "pending_review"
    return "approved"


def schema(name, description, properties=None, required=None):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {},
                       "required": required or [], "additionalProperties": False}}}


TOOLS = [
    schema("submit_application", "提交贷款申请。金额和用途必须来自用户明确输入，缺少时先追问，不得猜测。",
           {"amount": {"type": "number", "description": "人民币元"}, "purpose": {"type": "string"}}, ["amount", "purpose"]),
    schema("credit_inquiry", "查询当前测试客户的真实数据库风险档案，在提交申请后必须查询。"),
    schema("approve_loan", "仅用于征信查询后 risk=low、score>=650、金额<=200000且未阻断的测试申请。"),
    schema("request_human_review", "高风险/低分/超20万元的测试申请必须转人工。"),
    schema("reject_loan", "仅拒绝风险档案中 blocked=true 的测试申请。"),
    schema("get_application", "查询当前会话申请的数据库状态，不能查询其他客户。"),
]


class LoanTools:
    def __init__(self, store, session_id, request_id, evidence):
        self.store, self.session, self.request, self.evidence = store, session_id, request_id, evidence

    def invoke(self, name, arguments):
        with self.evidence.span(name, "tool", inputs=arguments, tool_name=name) as span:
            self.evidence.collector.bump_tool()
            try:
                output = self._execute(name, arguments)
            except ValueError as exc:
                output = {"error": "TOOL_REJECTED", "message": str(exc)[:250]}
                span["failed"] = True
            self.store.audit(self.request, name, arguments, output)
            span["output"] = output
            return output

    def _execute(self, name, arguments):
        if name not in {t["function"]["name"] for t in TOOLS}:
            raise ValueError("unknown tool")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        if name != "submit_application" and arguments:
            raise ValueError("this tool does not accept arguments")
        app = self.store.application(self.session)
        if name == "get_application":
            return app
        if name == "submit_application":
            values = LoanInput.model_validate(arguments).model_dump()
            if not values["purpose"].strip():
                raise ValueError("purpose cannot be blank")
            if app["status"] != "no_application":
                if app["amount"] != values["amount"] or app["purpose"] != values["purpose"]:
                    raise ValueError("session already has another application; start a new session")
                return app
            app = {"application_id": str(uuid4()), **values, "status": "submitted",
                   "approved": False, "human_review": False, "credit_checked": False,
                   "policy_version": "test-policy-v1", "test_only": True}
        elif name == "credit_inquiry":
            if app["status"] == "no_application":
                raise ValueError("submit an application before credit inquiry")
            app["credit_checked"] = True
            app["credit"] = self.store.profile(self.session)
            self.store.save_application(self.session, app)
            return {**app["credit"], "required_action": decision(app, app["credit"])}
        else:
            if not app.get("credit_checked"):
                raise ValueError("credit inquiry is required before a decision")
            wanted = {"approve_loan": "approved", "request_human_review": "pending_review", "reject_loan": "rejected"}[name]
            required = decision(app, self.store.profile(self.session))
            if wanted != required:
                raise ValueError(f"policy rejects {name}; required status is {required}")
            app.update(status=wanted, approved=wanted == "approved", human_review=wanted == "pending_review")
        self.store.save_application(self.session, app)
        return app
