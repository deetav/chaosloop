# import asyncio
#
#
# def run_experiment(use_python_task):
#     captured = []
#
#     class Probe(asyncio.SelectorEventLoop):
#         def _run_once(self):
#             for handle in self._ready:
#                 callback = handle._callback
#                 callback_type = type(callback).__name__
#                 owner = getattr(callback, "__self__", None)
#                 owner_type = type(owner).__name__
#                 captured.append(
#                     (callback_type, owner_type)
#                 )
#
#             super()._run_once()
#
#     async def child():
#         await asyncio.sleep(0)
#
#     async def main():
#         await asyncio.gather(
#             child(),
#             child(),
#         )
#
#     loop = Probe()
#
#     try:
#         if use_python_task:
#             loop.set_task_factory(
#                 lambda loop, coro: asyncio.tasks._PyTask(
#                     coro,
#                     loop=loop,
#                 )
#             )
#
#         loop.run_until_complete(main())
#
#     finally:
#         loop.close()
#
#     if use_python_task:
#         print("\nPure-Python _PyTask")
#     else:
#         print("\nDefault C Task")
#     for row in dict.fromkeys(captured):
#         print(row)
#
#
# run_experiment(use_python_task=False)
# run_experiment(use_python_task=True)
