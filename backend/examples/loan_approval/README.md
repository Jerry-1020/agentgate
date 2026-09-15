# Loan Approval Demo

First recommended demo.

The demo should show:

- business policy validation
- required and forbidden tool calls
- tool argument constraints
- final state assertions
- release gate decision

The two deterministic versions are `loan-agent-v1-risky`, which directly approves the high-risk case, and `loan-agent-v2-fixed`, which requests human review. Run either version:

```bash
agentgate evaluate --version loan-agent-v1-risky --database ./agentgate.db
agentgate evaluate --version loan-agent-v2-fixed --database ./agentgate.db
```
