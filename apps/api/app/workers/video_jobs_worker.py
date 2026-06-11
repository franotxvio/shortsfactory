from __future__ import annotations

import asyncio

from app.services.video_job_queue import get_video_job_queue_service


async def main() -> None:
    service = get_video_job_queue_service()
    await service.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
