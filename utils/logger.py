import logging
import queue
import json
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, Any
from rich.console import Console
from rich.logging import RichHandler

# Third-party loggers that spam INFO every few seconds (and leak the Telegram
# bot token in httpx request URLs). Pin them to WARNING so /debug logs stay
# useful, the log file/buffer don't churn, and the token isn't logged.
_NOISY_LOGGERS = (
    "httpx", "httpcore", "telegram", "telegram.ext", "apscheduler",
    "urllib3", "selenium", "asyncio", "WDM", "undetected_chromedriver",
)

# Global log queue for real-time streaming - increased size for detailed logging
log_queue: queue.Queue = queue.Queue(maxsize=5000)

# In-memory buffer for debug endpoint — keeps last 300 messages
log_buffer: deque = deque(maxlen=300)

class QueueHandler(logging.Handler):
    """Custom handler to send logs to queue and buffer"""

    def emit(self, record):
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName
            }
            serialized = json.dumps(log_entry)

            log_buffer.append(log_entry)

            for _ in range(3):
                try:
                    log_queue.put_nowait(serialized)
                    return
                except queue.Full:
                    try:
                        log_queue.get_nowait()  # drop one oldest
                    except queue.Empty:
                        return

        except Exception:
            pass

def setup_logging():
    """Setup logging. Idempotent — safe to call multiple times."""
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger("freelance_mvp")

    import os
    os.makedirs("logs", exist_ok=True)

    console = Console()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            RotatingFileHandler("logs/app.log", maxBytes=5 * 1024 * 1024,
                                backupCount=2, encoding="utf-8"),
            QueueHandler()
        ]
    )

    # Silence noisy third-party loggers (also stops the bot token leaking via httpx).
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger = logging.getLogger("freelance_mvp")
    logger.setLevel(logging.INFO)
    return logger

# Global logger instance
logger = setup_logging()

def log_agent_action(agent: str, action: str, details: Dict[str, Any] = None, level: str = "INFO"):
    """Log agent actions with structured data"""
    message = f"🤖 {agent}: {action}"

    if details:
        details_str = " | ".join(f"{k}: {v}" for k, v in details.items())
        message += f" | {details_str}"

    if level.upper() == "DEBUG":
        logger.debug(message)
    elif level.upper() == "WARNING":
        logger.warning(message)
    elif level.upper() == "ERROR":
        logger.error(message)
    else:
        logger.info(message)


def get_recent_logs() -> list:
    """Последние строки лога для /debug.

    Хостинг на бесплатном тарифе не даёт удобного доступа к логам, а понимать
    состояние бота надо — этого буфера хватает, чтобы увидеть запуск,
    индексацию роликов и то, что случилось с последним сообщением.
    """
    return list(log_buffer)
