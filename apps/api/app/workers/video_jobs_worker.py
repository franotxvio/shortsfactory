from __future__ import annotations

import asyncio
import sys

from app.services.video_job_queue import get_video_job_queue_service


def _configure_event_loop_policy() -> None:
    if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main() -> None:
    service = get_video_job_queue_service()
    await service.run_forever()


if __name__ == "__main__":
    _configure_event_loop_policy()
    asyncio.run(main())
