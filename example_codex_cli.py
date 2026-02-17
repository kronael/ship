#!/usr/bin/env python3
"""example: using CodexClient as a library"""

import asyncio
from ship.codex_cli import CodexClient


async def main():
    # create client
    client = CodexClient(model="o3-mini", cwd=".")

    # execute prompt
    result = await client.execute(
        prompt="list all python files in the current directory", timeout=30
    )

    print(f"result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
