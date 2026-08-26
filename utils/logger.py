# 统一日志管理：所有模块用同一个 logger，级别统一控制

import logging
import sys


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """获取一个配置好的 logger 实例"""
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 输出到终端
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # 格式：时间 | 级别 | 模块名 | 消息
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
