"""Command line entry point: `fleetlens download | etl | train | serve | all`."""

from __future__ import annotations

import argparse
import json

from .config import Settings
from .observability import configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fleetlens")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download", help="fetch the EPA vehicles CSV")
    sub.add_parser("etl", help="validate, transform and load into SQLite")
    sub.add_parser("train", help="train the MPG model with a time-based split")
    serve = sub.add_parser("serve", help="run the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("all", help="download + etl + train")
    args = parser.parse_args(argv)

    s = Settings.from_env()
    configure_logging(s.log_level)

    if args.cmd in ("download", "all"):
        from .etl import download

        if not s.raw_csv_path.exists():
            download(s.source_url, s.raw_csv_path)
    if args.cmd in ("etl", "all"):
        from .etl import run

        print(json.dumps(run(s.raw_csv_path, s.db_path).to_dict(), indent=2))
    if args.cmd in ("train", "all"):
        from .model import train

        print(json.dumps(train(s.db_path, s.model_path).__dict__, indent=2))
    if args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(
            create_app(s), host=args.host, port=args.port, log_config=None, access_log=False
        )


if __name__ == "__main__":
    main()
