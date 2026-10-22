"""Run the MCP server on stdio: python -m rootsignal_agent.mcp_server"""

import logging
import sys

from rootsignal_agent.mcp_server.server import create_server


def main() -> None:
    # stdout is the protocol channel, so all logging goes to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    create_server().run("stdio")


if __name__ == "__main__":
    main()
