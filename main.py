# AutoShorts entry points — do not conflate (logic below unchanged):
# - This file (root main.py): API server. Compose `api` service runs
#   `uvicorn app.asgi:app` (see host/port/reload from app.config.config).
# - cli.py: batch video pipeline. automation/runner.py:353 shells out to
#   `cli.py --batch-file <manifest>` for unattended generation.
# - flowkit/agent/main.py: Flow Kit media server (FastAPI + WebSocket),
#   separate from the API server above.
import uvicorn
from loguru import logger

from app.config import config

if __name__ == "__main__":
    logger.info(
        "start server, docs: http://127.0.0.1:" + str(config.listen_port) + "/docs"
    )
    # FFmpeg 探测已经移到 app/services/task.py 的共享任务流水线里，这样
    # API、CLI 和 WebUI 三条路径都能统一覆盖，这里不再单独检查。
    uvicorn.run(
        app="app.asgi:app",
        host=config.listen_host,
        port=config.listen_port,
        reload=config.reload_debug,
        log_level="warning",
    )
