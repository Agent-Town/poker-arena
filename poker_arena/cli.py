import argparse
import sys


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="poker-arena")
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the operator HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--data-dir", default=None, help="Root directory for operator storage (default: ./data)")

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    ns = _parse_args(sys.argv[1:] if argv is None else argv)
    if ns.cmd == "serve":
        from poker_arena.operator.app import create_app

        import uvicorn

        app = create_app(data_dir=ns.data_dir)
        uvicorn.run(app, host=ns.host, port=ns.port, log_level="info")
        return

    raise SystemExit(2)


if __name__ == "__main__":
    main()

