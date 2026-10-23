# 统一日志管理：所有模块用同一个 logger，级别统一控制

import logging
import sys


class _SDKLogFilter(logging.Filter):
    """SDK 调试输出可能包含请求或原始异常，统一替换而不尝试解析密钥。"""
    def filter(self, record):
        record.msg = "模型 SDK 事件（详细内容已隐藏）"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


_sdk_filter = _SDKLogFilter()


def protect_sdk_logs():
    """只过滤 DashScope 自身的记录；同一过滤器重复添加不会重复注册。"""
    logging.getLogger("dashscope").addFilter(_sdk_filter)


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
