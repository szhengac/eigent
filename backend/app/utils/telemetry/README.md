# Workforce Telemetry

OpenTelemetry-based telemetry for CAMEL workforce events, sent to Langfuse for observability.

## Configuration

Add the following environment variables to `~/.paxs/.env`:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com  # Optional, defaults to US cloud
```

**If these keys are not specified, telemetry will be disabled.**

## Langfuse Setup

- **Cloud**: Sign up at [Langfuse Cloud](https://cloud.langfuse.com)
- **Self-hosted**: Use the [open-source version](https://langfuse.com/self-hosting)
- **Documentation**: [https://langfuse.com/docs](https://langfuse.com/docs)

## Privacy

Only **metadata** is captured (task IDs, timings, model names, token counts, quality scores). **No PII or detailed task content** is sent to Langfuse.

## Architecture

### Singleton TracerProvider

The `TracerProvider` is initialized once during FastAPI startup (`main.py`) to ensure only one `BatchSpanProcessor` is running, regardless of how many `WorkforceMetricsCallback` instances are created. This prevents:

- Resource leaks from multiple background export threads
- OOM issues from unbounded span queuing (max queue: 4096 spans)
- Excessive memory usage across multiple workforce sessions

The initialization happens in the startup event:

```python
@api.on_event("startup")
async def startup_event():
    from app.utils.telemetry.workforce_metrics import initialize_tracer_provider
    initialize_tracer_provider()
```

### Batch Processing Configuration

- `max_queue_size`: 4096 spans (drops oldest when full)
- `export_timeout_millis`: 30000 (30s timeout for exports)
- `schedule_delay_millis`: 3000 (exports every 3s)
- `max_export_batch_size`: 1024 (max spans per export)

## Span Structure

All spans share common resource attributes and scope information:

```json
{
  "resourceAttributes": {
    "service.name": "paxs-workforce",
    "paxs.project.id": "1768815931733-6575",
    "paxs.task.id": "1768815944094-9806"
  },
  "scope": {
    "name": "paxs.workforce",
    "version": "0.2.83a9"
  }
}
```

### worker.created

Emitted when a worker is created.

```json
{
  "attributes": {
    "paxs.worker.id": "73d20286-2c17-467a-8153-2a6ea8cbb6c2",
    "paxs.worker.type": "SingleAgentWorker",
    "paxs.worker.role": "Developer Agent: A master-level coding...",
    "paxs.worker.agent": "developer_agent",
    "paxs.worker.model.type": "gpt-4.1-mini"
  }
}
```

### task.created

Emitted when a task is created.

```json
{
  "attributes": {
    "paxs.task.id": "1768815944094-9806.1",
    "paxs.task.description": "Task description",
    "paxs.project.id": "1768815931733-6575",
    "paxs.task.parent_id": "1768815944094-9806",
    "paxs.task.type": "task_type"
  }
}
```

### task.assigned

Emitted when a task is assigned to a worker.

```json
{
  "attributes": {
    "paxs.task.id": "1768815944094-9806.1",
    "paxs.worker.id": "0fae2d3d-7c0a-4b50-b09d-da35ae61786d",
    "paxs.project.id": "1768815931733-6575",
    "paxs.task.queue_time_seconds": "1.5",
    "paxs.task.dependencies": "[\"dep_1\", \"dep_2\"]"
  }
}
```

### task.execution:{task_id}

Long-running span tracking task execution from start to completion.

```json
{
  "attributes": {
    "paxs.task.id": "1768815944094-9806.1",
    "paxs.project.id": "1768815931733-6575",
    "paxs.task.status": "completed",
    "paxs.worker.id": "0fae2d3d-7c0a-4b50-b09d-da35ae61786d",
    "paxs.task.timestamp": "2026-01-19T09:46:40.045077+00:00",
    "paxs.task.parent_id": "1768815944094-9806",
    "paxs.task.processing_time_seconds": "10.926168203353882",
    "paxs.task.quality_score": "80",
    "paxs.task.token_usage.total_tokens": "37284"
  }
}
```

### workforce.all_tasks_completed

Emitted when all tasks in the workforce are completed.

```json
{
  "attributes": {
    "paxs.project.id": "1768815931733-6575",
    "paxs.task.id": "1768815944094-9806",
    "paxs.task.timestamp": "2026-01-19T09:46:44.901068+00:00",
    "workforce.total_tasks": "5"
  }
}
```

### log.message

Emitted for error and critical log messages.

```json
{
  "attributes": {
    "log.level": "error",
    "log.message": "Error message",
    "paxs.project.id": "1768815931733-6575"
  }
}
```

## Captured Attributes Reference

### Project & Task

- `paxs.project.id` - Workforce/project identifier
- `paxs.task.id` - Task identifier
- `paxs.task.description` - Task description
- `paxs.task.parent_id` - Parent task ID
- `paxs.task.type` - Task type
- `paxs.task.status` - Task status (started, completed, failed)
- `paxs.task.timestamp` - ISO 8601 timestamp
- `paxs.task.dependencies` - JSON array of dependency task IDs
- `paxs.task.queue_time_seconds` - Time in queue before assignment
- `paxs.task.processing_time_seconds` - Task execution duration
- `paxs.task.quality_score` - Quality score (0-100)

### Worker

- `paxs.worker.id` - Worker UUID
- `paxs.worker.type` - Worker class type
- `paxs.worker.role` - Worker role description
- `paxs.worker.agent` - Agent type (developer_agent, browser_agent, etc.)
- `paxs.worker.model.type` - Model name (gpt-4, claude-3, etc.)

### Token Usage

- `paxs.task.token_usage.total_tokens` - Total tokens used
- `paxs.task.token_usage.*` - Additional token usage metrics

### Langfuse

- `langfuse.session.id` - Set to project ID for grouping
- `langfuse.tags` - ["workforce", "paxs", "super-agent"]

### Workforce

- `workforce.total_tasks` - Total number of tasks completed
