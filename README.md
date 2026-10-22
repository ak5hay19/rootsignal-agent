# RootSignalAgent

An agentic SRE assistant that investigates platform incidents. Given a report like "my nightly job failed", it queries metrics, searches logs, retrieves runbooks, forms a hypothesis, and replies with root cause, evidence, and a proposed (never auto-executed) remediation. Delivered through a Slack bot and a CLI, with a Go node probe as an extra tool server and a Grafana dashboard.

