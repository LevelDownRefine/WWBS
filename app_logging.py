"""WWBS 的 GUI 与本地文件日志。"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue


class GuiQueueHandler(logging.Handler):
    """将格式化后的日志交给 Tk 主线程显示。"""

    def __init__(self, target: Queue[str]) -> None:
        super().__init__()
        self.target = target

    def emit(self, record: logging.LogRecord) -> None:
        """格式化一条日志并写入 GUI 队列。

        Args:
            record: Python logging 生成的日志记录。
        """
        try:
            self.target.put_nowait(self.format(record))
        except Exception:
            self.handleError(record)


def configure_app_logging(
    target: Queue[str],
    log_path: Path,
) -> tuple[logging.Logger, str | None]:
    """配置同时写入 GUI 和本地文件的应用日志。

    Args:
        target: GUI 主线程读取的字符串队列。
        log_path: 当前日志文件路径。

    Returns:
        配置好的 logger，以及文件日志初始化失败时的错误信息。
    """
    logger = logging.getLogger("wwbs")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # 测试或重复创建窗口时先关闭旧 handler，避免一条日志被写入多次。
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    gui_handler = GuiQueueHandler(target)
    gui_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(gui_handler)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError as exc:
        return logger, str(exc)

    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)
    return logger, None
