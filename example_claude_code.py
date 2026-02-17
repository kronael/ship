#!/usr/bin/env python3
"""example: using ClaudeCodeClient as a library"""

import asyncio
from ship.claude_code import ClaudeCodeClient


async def main():
    # create client
    client = ClaudeCodeClient(model="sonnet", cwd=".")

    # execute prompt
    result = await client.execute(
        prompt="create a hello.txt file with 'hello world'", timeout=30
    )

    print(f"result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
