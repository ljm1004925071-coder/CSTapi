import argparse
import sys
import traceback

from cst.interface import DesignEnvironment, running_design_environments


def log(message: str) -> None:
    print(f"[CST-PY] {message}", flush=True)


def cmd_info(_: argparse.Namespace) -> int:
    pids = list(running_design_environments())
    log(f"Running design environments: {pids}")
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    log("Connecting to CST design environment")

    if args.connect_to_any:
        de = DesignEnvironment.connect_to_any_or_new()
    else:
        de = DesignEnvironment.new(options=args.options or None)

    log(f"Connected: {type(de).__name__}")
    log(f"Open projects: {de.list_open_projects()}")
    return 0


def cmd_new_mws(args: argparse.Namespace) -> int:
    log("Creating or connecting to design environment")

    if args.connect_to_any:
        de = DesignEnvironment.connect_to_any_or_new()
    else:
        de = DesignEnvironment.new(options=args.options or None)

    log("Trying de.new_mws()")
    project = de.new_mws()
    log(f"Project created: {type(project).__name__}")

    if args.save_as:
        log(f"Saving project: {args.save_as}")
        project.save(args.save_as, include_results=False)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal CST Python automation smoke tests using CST's bundled Python."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("info", help="List running CST design environments.")
    info_parser.set_defaults(handler=cmd_info)

    connect_parser = subparsers.add_parser(
        "connect", help="Connect to an existing or new CST design environment."
    )
    connect_parser.add_argument(
        "--connect-to-any",
        action="store_true",
        help="Connect to any running CST instance, or create one if none exists.",
    )
    connect_parser.add_argument(
        "--options",
        nargs="*",
        default=[],
        help="Optional CST startup options, for example: --options --hide",
    )
    connect_parser.set_defaults(handler=cmd_connect)

    new_mws_parser = subparsers.add_parser(
        "new-mws", help="Create a new Microwave Studio project."
    )
    new_mws_parser.add_argument(
        "--connect-to-any",
        action="store_true",
        help="Connect to any running CST instance, or create one if none exists.",
    )
    new_mws_parser.add_argument(
        "--options",
        nargs="*",
        default=[],
        help="Optional CST startup options, for example: --options --hide",
    )
    new_mws_parser.add_argument(
        "--save-as",
        help="Optional target .cst path for saving the new project.",
    )
    new_mws_parser.set_defaults(handler=cmd_new_mws)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.handler(args)
    except Exception as exc:
        log(f"FAILED: {exc!r}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
