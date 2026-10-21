import asyncio
import logging
import signal

import asyncpg

from collector.sources import COLLECTORS
from collector.store import Store
from collector.runtime import configure_bluetooth_bus, database_options


logger = logging.getLogger("collector")




async def main():
    configure_bluetooth_bus()
    pool = await asyncpg.create_pool(**database_options())
    store = Store(pool)
    errors = {}
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)

    async def supervise(module):
        while True:
            try:
                errors.pop(module.__name__, None)
                await module.run(store)
                raise RuntimeError("采集模块意外退出")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                message = str(error) or type(error).__name__
                errors[module.__name__] = message
                logger.exception("%s 将在 10 秒后重试", module.__name__)
                await asyncio.sleep(10)

    async def heartbeat():
        while True:
            try:
                await store.heartbeat("; ".join(errors.values()) or None)
            except Exception:
                logger.exception("无法更新采集服务状态")
            await asyncio.sleep(5)

    tasks = [asyncio.create_task(heartbeat())]
    tasks.extend(asyncio.create_task(supervise(module)) for module in COLLECTORS)
    logger.info("采集服务已启动")
    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
