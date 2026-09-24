from __future__ import annotations

import json
import os

from .bridge import FactoryA2ABridge, parse_a2a_text
from .card import build_sdk_agent_card


def _is_loopback(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def validate_bind_policy(host: str, allow_remote: bool = False) -> None:
    if not _is_loopback(host) and not allow_remote:
        raise RuntimeError(
            "Refusing non-loopback A2A bind. Set TRAFICLAB_A2A_ALLOW_REMOTE=1 "
            "only after authentication/reverse-proxy policy is configured."
        )


def build_app(
    *,
    public_url: str = "http://127.0.0.1:8787",
    bridge: FactoryA2ABridge | None = None,
):
    """Build an A2A v1.0 JSON-RPC Starlette application."""
    try:
        from a2a.helpers import (
            get_message_text,
            new_task_from_user_message,
            new_text_message,
            new_text_part,
        )
        from a2a.server.agent_execution import AgentExecutor, RequestContext
        from a2a.server.events import EventQueue
        from a2a.server.request_handlers import DefaultRequestHandler
        from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
        from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
        from a2a.types.a2a_pb2 import TaskState
        from starlette.applications import Starlette
    except ImportError as exc:  # pragma: no cover - deployment-only dependency
        raise RuntimeError(
            'A2A runtime dependencies are not installed. Install with: pip install -e ".[a2a]"'
        ) from exc

    live_bridge = bridge or FactoryA2ABridge()
    card = build_sdk_agent_card(public_url)

    class FactoryExecutor(AgentExecutor):
        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            if context.current_task:
                task = context.current_task
            else:
                task = new_task_from_user_message(context.message)
                await event_queue.enqueue_event(task)

            updater = TaskUpdater(
                event_queue=event_queue,
                task_id=task.id,
                context_id=task.context_id,
            )
            await updater.update_status(
                state=TaskState.TASK_STATE_WORKING,
                message=new_text_message("Evaluating in advisory shadow mode."),
            )

            payload = parse_a2a_text(get_message_text(context.message))
            result = live_bridge.handle(payload).as_dict()
            body = json.dumps(result, sort_keys=True, ensure_ascii=False)
            await updater.add_artifact(
                parts=[new_text_part(text=body, media_type="application/json")]
            )
            await updater.update_status(
                state=TaskState.TASK_STATE_COMPLETED,
                message=new_text_message("Advisory evaluation complete."),
            )

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            raise NotImplementedError("Cancel is not supported.")

    handler = DefaultRequestHandler(
        agent_executor=FactoryExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = []
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url="/a2a"))
    return Starlette(routes=routes)


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            'uvicorn is required for the A2A server. Install with: pip install -e ".[a2a]"'
        ) from exc

    host = os.getenv("TRAFICLAB_A2A_HOST", "127.0.0.1")
    port = int(os.getenv("TRAFICLAB_A2A_PORT", "8787"))
    public_url = os.getenv("TRAFICLAB_A2A_PUBLIC_URL", f"http://{host}:{port}")
    allow_remote = os.getenv("TRAFICLAB_A2A_ALLOW_REMOTE", "0").strip() == "1"
    validate_bind_policy(host, allow_remote=allow_remote)
    uvicorn.run(build_app(public_url=public_url), host=host, port=port)


if __name__ == "__main__":
    main()
