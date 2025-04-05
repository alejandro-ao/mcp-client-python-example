import asyncio
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env


class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.llm = Anthropic()
        self.tools = []
        self.messages = []

    # methods will go here
    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server

        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith(".py")
        is_js = server_script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command, args=[server_script_path], env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()
        mcp_tools = await self.get_mcp_tools()
        self.tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in mcp_tools
        ]
        print(f"Connected to server with tools: {mcp_tools}")

    async def get_mcp_tools(self):
        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        return tools

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        self.messages.append({"role": "user", "content": query})

        final_text = []

        while True:
            # Call Claude API
            response = self.llm.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                messages=self.messages,
                tools=self.tools,
            )

            if response.content[0].type == "text" and len(response.content) == 1:
                final_text.append(response.content[0].text)
                break

            for content in response.content:
                if content.type == "text":
                    final_text.append(content.text)
                    self.messages.append({"role": "assistant", "content": content.text})
                elif content.type == "tool_use":
                    tool_name = content.name
                    tool_args = content.input
                    result = await self.session.call_tool(tool_name, tool_args)
                    final_text.append(result.content)
                    self.messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": content.id,
                                    "content": result.content,
                                }
                            ],
                        }
                    )

    def print_conversation(self):
        """Print the entire conversation history"""
        print("\n=== Conversation History ===")
        for msg in self.messages:
            role = msg["role"].capitalize()
            if isinstance(msg["content"], str):
                content = msg["content"]
            elif isinstance(msg["content"], list):
                if any(item.get("type") == "tool_result" for item in msg["content"]):
                    content = "[Tool Result]"
                else:
                    content = "\n".join(
                        item.text for item in msg["content"] if hasattr(item, "text")
                    )
            print(f"\n{role}: {content}")
        print("\n=========================")

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == "quit":
                    break

                response = await self.process_query(query)
                print("\n" + response)
                self.print_conversation()  # Show updated conversation after response

            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    import sys

    asyncio.run(main())
