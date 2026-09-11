import asyncio

captured = []


class Probe(asyncio.SelectorEventLoop):
    def _run_once(self):
        for h in self._ready:
            cb = h._callback
            captured.append((type(cb).__name__,
                             type(getattr(cb, "__self__", None)).__name__))
        super()._run_once()


async def child():
    await asyncio.sleep(0)


async def main():
    await asyncio.gather(child(), child())


loop = Probe()
try:
    loop.run_until_complete(main())
finally:
    loop.close()

for row in dict.fromkeys(captured):
    print(row)