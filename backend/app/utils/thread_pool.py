"""线程池创建工厂 + 任务队列 — 统一的生命周期管理和任务调度。

使用示例::

    # ── 直接使用线程池 ──
    cpu_pool = create_thread_pool(max_workers=4, thread_name_prefix="cpu-worker")
    io_pool = create_thread_pool(max_workers=16, thread_name_prefix="io-worker")

    # ── 使用任务队列（推荐）──
    queue = TaskQueue(max_workers=8, thread_name_prefix="kb-worker")

    # 提交单个任务
    fut = queue.submit(some_blocking_fn, arg1, arg2)

    # 批量提交并等待全部完成
    results = queue.submit_all(fn, [(arg_a,), (arg_b,), (arg_c,)])

    # 批量映射（无序，先完成先返回）
    for result in queue.map_unordered(fn, items):
        process(result)

    # 优雅关闭
    queue.shutdown(wait=True)
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from typing import TYPE_CHECKING, Any, Callable, TypeVar

if TYPE_CHECKING:
    import asyncio

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


# ── 线程池工厂 ───────────────────────────────────────────────────────────


def create_thread_pool(
    max_workers: int | None = None,
    *,
    thread_name_prefix: str = "kb-pool",
    initializer: object | None = None,
    initargs: tuple = (),
    set_as_default: bool = False,
    loop: "asyncio.AbstractEventLoop | None" = None,
) -> ThreadPoolExecutor:
    """创建并返回一个 ThreadPoolExecutor，核心参数均可自定义。

    Args:
        max_workers: 最大工作线程数。默认为 None（Python 内部按
            ``min(32, os.cpu_count() + 4)`` 自动计算）。
        thread_name_prefix: 线程名前缀，方便在调试/日志中区分池来源。
        initializer: 每个工作线程启动时调用的初始化函数。
        initargs: 传递给 initializer 的位置参数。
        set_as_default: 是否将该池注册为当前事件循环的默认执行器。
            设为 True 后，后续 ``loop.run_in_executor(None, fn)``
            将使用此池而非默认池。
        loop: 目标事件循环。为 None 时自动获取当前运行中的事件循环。
            仅在 set_as_default=True 时使用。

    Returns:
        配置好的 ThreadPoolExecutor 实例。

    Raises:
        RuntimeError: set_as_default=True 但未找到运行中的事件循环。
    """
    executor = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
        initializer=initializer,
        initargs=initargs,
    )

    logger.info(
        "线程池已创建 — 名称前缀=%s, max_workers=%s",
        thread_name_prefix,
        max_workers,
    )

    if set_as_default:
        _loop = loop
        if _loop is None:
            import asyncio as _asyncio

            try:
                _loop = _asyncio.get_running_loop()
            except RuntimeError:
                raise RuntimeError(
                    "set_as_default=True 要求存在运行中的事件循环，"
                    "请传入 loop 参数或在 async 上下文中调用。"
                ) from None

        _loop.set_default_executor(executor)
        logger.info("已将线程池设为事件循环的默认执行器")

    return executor


# ── 关闭辅助 ─────────────────────────────────────────────────────────────


def shutdown_thread_pool(
    executor: ThreadPoolExecutor,
    *,
    wait: bool = True,
    cancel_futures: bool = False,
    timeout: float | None = None,
) -> None:
    """安全关闭线程池，等待/取消未完成任务。

    Args:
        executor: 要关闭的 ThreadPoolExecutor 实例。
        wait: True 表示等待所有已提交任务完成后再关闭。
        cancel_futures: True 表示取消所有尚未开始执行的任务。
        timeout: 等待已提交任务完成的最大秒数。None 表示无限等待。
            Python 3.13+ 才支持此参数（内部自动兼容）。
    """
    try:
        # Python 3.13+ 支持 timeout 参数
        if timeout is not None:
            executor.shutdown(wait=wait, cancel_futures=cancel_futures, timeout=timeout)
        else:
            executor.shutdown(wait=wait, cancel_futures=cancel_futures)
    except TypeError:
        # 低版本 Python 不支持 timeout 参数，降级调用
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    logger.info("线程池已关闭 — wait=%s, cancel_futures=%s", wait, cancel_futures)


# ── 便捷工厂：常用预设 ────────────────────────────────────────────────────


def create_io_pool(
    max_workers: int = 16,
    *,
    thread_name_prefix: str = "kb-io",
    **kwargs,
) -> ThreadPoolExecutor:
    """创建 I/O 密集型任务线程池（高并发，适合网络/磁盘 I/O）。"""
    return create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
        **kwargs,
    )


def create_cpu_pool(
    max_workers: int | None = None,
    *,
    thread_name_prefix: str = "kb-cpu",
    **kwargs,
) -> ThreadPoolExecutor:
    """创建 CPU 密集型任务线程池（默认 worker 数 = CPU 核数）。

    Args:
        max_workers: 最大工作线程数。None 时自动取 ``os.cpu_count()``。
    """
    if max_workers is None:
        import os

        max_workers = os.cpu_count() or 4
    return create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
        **kwargs,
    )


# ── 任务队列 ───────────────────────────────────────────────────────────────


class TaskQueue:
    """线程池之上的任务队列封装，提供便捷的批量提交、映射和优雅关闭。

    两种用法::

        # 1) TaskQueue 自己创建线程池（默认）
        queue = TaskQueue(max_workers=8, thread_name_prefix="ingest")

        # 2) 复用外部已有线程池（多队列共享一个池）
        pool = create_io_pool(max_workers=16)
        q1 = TaskQueue(executor=pool)
        q2 = TaskQueue(executor=pool)  # 同池，独立 Future 追踪

        # 单个提交
        fut = queue.submit(parse_file, path)

        # 批量提交，按完成顺序返回
        for result in queue.map_unordered(parse_file, paths):
            save(result)

        # 关闭（外部池不会被关，由调用方管理生命周期）
        queue.shutdown()
    """

    def __init__(
        self,
        max_workers: int | None = None,
        *,
        executor: ThreadPoolExecutor | None = None,
        thread_name_prefix: str = "kb-queue",
        initializer: Callable[..., object] | None = None,
        initargs: tuple = (),
        set_as_default: bool = False,
    ):
        """初始化任务队列。

        Args:
            max_workers: 线程池最大工作线程数（仅 executor=None 时生效）。
            executor: 外部已有的 ThreadPoolExecutor。传入后忽略 max_workers
                等创建参数，shutdown 不会关闭外部池。
            thread_name_prefix: 线程名前缀（仅 executor=None 时生效）。
            initializer: 工作线程初始化函数（仅 executor=None 时生效）。
            initargs: 初始化函数参数（仅 executor=None 时生效）。
            set_as_default: 是否注册为 asyncio 默认执行器
                （仅 executor=None 时生效）。
        """
        if executor is not None:
            self._executor = executor
            self._own_executor = False
        else:
            self._executor = create_thread_pool(
                max_workers=max_workers,
                thread_name_prefix=thread_name_prefix,
                initializer=initializer,
                initargs=initargs,
                set_as_default=set_as_default,
            )
            self._own_executor = True
        self._futures: list[Future] = []
        self._lock = threading.Lock()
        self._closed = False

    # ── 属性 ──────────────────────────────────────────────────────────

    @property
    def executor(self) -> ThreadPoolExecutor:
        """底层 ThreadPoolExecutor 实例。"""
        return self._executor

    @property
    def pending_count(self) -> int:
        """当前未完成的任务数。"""
        with self._lock:
            return sum(1 for f in self._futures if not f.done())

    # ── 任务提交 ──────────────────────────────────────────────────────

    def submit(
        self,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> Future[T]:
        """提交单个任务到队列。

        Args:
            fn: 要在工作线程中执行的可调用对象。
            *args: 传递给 fn 的位置参数。
            **kwargs: 传递给 fn 的关键字参数。

        Returns:
            代表该任务的 Future 对象。

        Raises:
            RuntimeError: 队列已关闭。
        """
        if self._closed:
            raise RuntimeError("任务队列已关闭，无法提交新任务")

        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures.append(future)
        return future

    def submit_all(
        self,
        fn: Callable[..., T],
        arg_list: list[tuple] | None = None,
        *,
        kwargs_list: list[dict[str, Any]] | None = None,
    ) -> list[T]:
        """批量提交任务并阻塞等待全部完成，按提交顺序返回结果。

        Args:
            fn: 要在工作线程中执行的可调用对象。
            arg_list: 位置参数列表，每个元素是传给 fn 的 ``*args``。
                为 None 时表示无参数调用 fn 一次。
            kwargs_list: 关键字参数列表，与 arg_list 一一对应。

        Returns:
            按提交顺序排列的结果列表。某个任务抛异常时对应位置为 None。

        Raises:
            RuntimeError: 队列已关闭。
        """
        if arg_list is None:
            arg_list = [()]

        futures: list[Future[T]] = []
        for i, args in enumerate(arg_list):
            kwargs = (kwargs_list or [{}] * len(arg_list))[i] if kwargs_list else {}
            futures.append(self.submit(fn, *args, **kwargs))

        results: list[T | None] = [None] * len(futures)
        for i, f in enumerate(futures):
            try:
                results[i] = f.result()
            except Exception:
                logger.exception("任务 %d/%d 执行异常", i + 1, len(futures))
        return results

    def map_unordered(
        self,
        fn: Callable[[T], R],
        items: list[T],
        *,
        timeout: float | None = None,
    ):
        """对每个 item 调用 ``fn(item)``，按完成顺序逐个产出结果。

        适合 I/O 密集型批量处理 — 快的先返回，不阻塞等慢的。

        Args:
            fn: 单参数可调用对象，接收 items 中的每个元素。
            items: 输入元素列表。
            timeout: 单个任务的最大等待秒数。None 表示无限等待。

        Yields:
            按完成顺序产出的 ``fn(item)`` 结果。
            某任务抛异常时该位置被跳过（日志记录异常）。
        """
        futures_map: dict[Future[R], int] = {}
        for idx, item in enumerate(items):
            f = self.submit(fn, item)
            futures_map[f] = idx

        for f in as_completed(futures_map, timeout=timeout):
            idx = futures_map[f]
            try:
                yield f.result()
            except Exception:
                logger.exception("map_unordered 任务异常 — item[%d]", idx)

    # ── 等待与清理 ────────────────────────────────────────────────────

    def wait_all(
        self,
        timeout: float | None = None,
    ) -> tuple[set[Future], set[Future]]:
        """阻塞等待所有已提交任务完成。

        Args:
            timeout: 最大等待秒数。None 表示无限等待。

        Returns:
            ``(done, not_done)`` 两个 Future 集合。
        """
        with self._lock:
            futures = list(self._futures)
        return wait(futures, timeout=timeout)

    def clear_completed(self) -> int:
        """清理已完成的 Future 引用，释放内存。

        Returns:
            清理掉的 Future 数量。
        """
        with self._lock:
            before = len(self._futures)
            self._futures = [f for f in self._futures if not f.done()]
            removed = before - len(self._futures)
        if removed:
            logger.debug("清理已完成 Future: %d 个", removed)
        return removed

    def shutdown(
        self,
        *,
        wait: bool = True,
        cancel_futures: bool = False,
        timeout: float | None = None,
    ) -> None:
        """关闭任务队列，仅关闭自己创建的线程池。

        外部注入的 executor 不会被关闭 — 由调用方管理生命周期。

        Args:
            wait: True 表示等待所有已提交任务完成。
            cancel_futures: True 表示取消未开始的任务。
            timeout: 等待超时秒数（Python 3.13+）。
        """
        if self._closed:
            return
        self._closed = True
        if self._own_executor:
            shutdown_thread_pool(
                self._executor,
                wait=wait,
                cancel_futures=cancel_futures,
                timeout=timeout,
            )
        with self._lock:
            self._futures.clear()

    def __enter__(self) -> "TaskQueue":
        return self

    def __exit__(self, *args: object) -> None:
        self.shutdown(wait=True)

    def __repr__(self) -> str:
        return (
            f"TaskQueue(pending={self.pending_count}, "
            f"closed={self._closed}, prefix={self._executor._thread_name_prefix})"
        )


# ── 健康检查线程池（生命周期由 lifespan 管理） ────────────────────────────

health_executor: ThreadPoolExecutor | None = None
"""健康检查专用线程池，4 线程。不作为 asyncio 默认执行器 — 调用方需显式传入。

多池模式下各业务线持有独立的池引用，避免相互争抢线程。
"""


def startup_health_pool(
    max_workers: int = 4,
    *,
    thread_name_prefix: str = "kb-health",
) -> ThreadPoolExecutor:
    """创建健康检查专用线程池。

    应在 FastAPI lifespan startup 阶段调用。
    不作为默认执行器 — health 端点通过 ``health_executor`` 显式使用。

    Args:
        max_workers: 最大工作线程数，默认 4（对齐 4 路并行探测）。
        thread_name_prefix: 线程名前缀。

    Returns:
        配置好的 ThreadPoolExecutor 实例。
    """
    global health_executor
    health_executor = create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
    )
    return health_executor


def shutdown_health_pool() -> None:
    """关闭健康检查线程池。

    应在 FastAPI lifespan shutdown 阶段调用。
    """
    global health_executor
    if health_executor is not None:
        shutdown_thread_pool(health_executor, wait=True, cancel_futures=False)
        health_executor = None


# ── 上传线程池（生命周期由 lifespan 管理） ────────────────────────────────

upload_executor: ThreadPoolExecutor | None = None
"""上传专用线程池，8 线程。处理文件读取、MinIO 写入、ingest 等 I/O 密集操作。

不作为默认执行器 — documents.py 通过 ``upload_executor`` 显式使用。
"""


def startup_upload_pool(
    max_workers: int = 8,
    *,
    thread_name_prefix: str = "kb-upload",
) -> ThreadPoolExecutor:
    """创建上传专用线程池。

    应在 FastAPI lifespan startup 阶段调用。
    8 线程允许 8 个文件同时上传入库，互不阻塞。

    Args:
        max_workers: 最大工作线程数，默认 8。
        thread_name_prefix: 线程名前缀。

    Returns:
        配置好的 ThreadPoolExecutor 实例。
    """
    global upload_executor
    upload_executor = create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
    )
    return upload_executor


def shutdown_upload_pool() -> None:
    """关闭上传线程池。

    应在 FastAPI lifespan shutdown 阶段调用。
    """
    global upload_executor
    if upload_executor is not None:
        shutdown_thread_pool(upload_executor, wait=True, cancel_futures=False)
        upload_executor = None


# ── 资源处理线程池（生命周期由 deps.py 模块级管理） ──────────────────────────

asset_worker_pool: ThreadPoolExecutor | None = None
"""资源处理专用线程池，6 线程。

_prepare_assets 六路分发时使用：
- image / video / image_link / video_link → 魔数校验 + 视觉理解 + MinIO 上传
- document_link → HTTP 下载 → 子文档预占位 → MinIO 上传

独立池 → _prepare_assets 无论被谁调用都不会与调用方争抢 worker。
"""


def startup_asset_worker_pool(
    max_workers: int = 6,
    *,
    thread_name_prefix: str = "kb-asset-worker",
) -> ThreadPoolExecutor:
    """创建资源处理专用线程池。

    应在 FastAPI lifespan startup 阶段调用。

    Args:
        max_workers: 最大工作线程数，默认 6。
        thread_name_prefix: 线程名前缀。

    Returns:
        配置好的 ThreadPoolExecutor 实例。
    """
    global asset_worker_pool
    asset_worker_pool = create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
    )
    return asset_worker_pool


def shutdown_asset_worker_pool() -> None:
    """关闭资源处理线程池。

    应在 FastAPI lifespan shutdown 阶段调用。
    """
    global asset_worker_pool
    if asset_worker_pool is not None:
        shutdown_thread_pool(asset_worker_pool, wait=True, cancel_futures=False)
        asset_worker_pool = None


# ── 检索线程池（生命周期由 lifespan 管理） ──────────────────────────

search_executor: ThreadPoolExecutor | None = None
"""检索专用线程池，8 线程。

每次搜索内部向量检索 + BM25 检索在此池中并行执行。
全局复用避免高并发搜索时频繁创建/销毁临时线程池导致线程膨胀。

8 线程 → 最多 4 次并发搜索（每次 2 任务：向量 + BM25），匹配火山引擎 Embedding QPS 限制。
"""


def startup_search_pool(
    max_workers: int = 8,
    *,
    thread_name_prefix: str = "kb-search",
) -> ThreadPoolExecutor:
    """创建检索专用线程池。

    应在 FastAPI lifespan startup 阶段调用。

    Args:
        max_workers: 最大工作线程数，默认 8。
        thread_name_prefix: 线程名前缀。

    Returns:
        配置好的 ThreadPoolExecutor 实例。
    """
    global search_executor
    search_executor = create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
    )
    return search_executor


def shutdown_search_pool() -> None:
    """关闭检索线程池。

    应在 FastAPI lifespan shutdown 阶段调用。
    """
    global search_executor
    if search_executor is not None:
        shutdown_thread_pool(search_executor, wait=True, cancel_futures=False)
        search_executor = None


# ── 评测数据生成线程池（生命周期由 lifespan 管理） ──────────────────────

eval_gen_pool: ThreadPoolExecutor | None = None
"""评测数据生成专用线程池，8 线程。

入库完成后异步调用 LLM 生成评测数据时使用此池。
独立池 → 不与上传/检索/资源处理争抢 worker。
"""


def startup_eval_gen_pool(
    max_workers: int = 8,
    *,
    thread_name_prefix: str = "kb-eval-gen",
) -> ThreadPoolExecutor:
    """创建评测数据生成专用线程池。

    应在 FastAPI lifespan startup 阶段调用。

    Args:
        max_workers: 最大工作线程数，默认 8。
        thread_name_prefix: 线程名前缀。

    Returns:
        配置好的 ThreadPoolExecutor 实例。
    """
    global eval_gen_pool
    eval_gen_pool = create_thread_pool(
        max_workers=max_workers,
        thread_name_prefix=thread_name_prefix,
    )
    return eval_gen_pool


def shutdown_eval_gen_pool() -> None:
    """关闭评测数据生成线程池。

    应在 FastAPI lifespan shutdown 阶段调用。
    """
    global eval_gen_pool
    if eval_gen_pool is not None:
        shutdown_thread_pool(eval_gen_pool, wait=True, cancel_futures=False)
        eval_gen_pool = None
