import asyncio
import argparse
from pathlib import Path
from .server import main

def run():
    parser = argparse.ArgumentParser(description='MCP Logic Server')
    parser.add_argument('--prover-path', type=str, required=True,
                      help='Path to Prover9/Mace4 binaries')
    
    args = parser.parse_args()
    asyncio.run(main(args.prover_path))

if __name__ == '__main__':
    run()