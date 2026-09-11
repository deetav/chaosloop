# import asyncio
#
#
# async def noop():
#     pass
#
#
# async def show():
#     task = asyncio.create_task(noop())
#
#     print(task.get_name())
#
#     await task
#
#
# for _ in range(3):
#     asyncio.run(show())
