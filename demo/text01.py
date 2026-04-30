import asyncio
import httpx

async def send(name):
    async with httpx.AsyncClient() as client:
        res = await client.post(
            "http://127.0.0.1:8000/task",
            params={"name": name}
        )
        print(res.json())

async def main():
    tasks = [
        send("A"),
        send("B"),
        send("C"),
        send("D"),
        send("E"),
    ]
    await asyncio.gather(*tasks)

asyncio.run(main())