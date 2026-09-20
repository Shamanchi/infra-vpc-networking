"""CLI: plan/validate/generate для VPC."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.subnets import generate_hcl, load_plan, plan_vpc, save_plan, validate_plan


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        plan = plan_vpc(args.cidr, args.azs, args.newbits)
        save_plan(plan, args.out)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"Wrote {args.out} with {len(plan.subnets)} subnets")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        plan = load_plan(args.file)
        errors = validate_plan(plan)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    if errors:
        print("INVALID:")
        for error in errors:
            print(f"  - {error}")
        return 2
    print("OK: plan is valid")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        hcl = generate_hcl(args.cidr, args.azs, settings.aws_region)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    out = Path(args.out) if args.out else Path(settings.output_dir) / "generated.tf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(hcl, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infra-vpc-networking", description="VPC subnet planner")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Plan subnets")
    plan.add_argument("--cidr", required=True, help="VPC CIDR, e.g. 10.0.0.0/16")
    plan.add_argument("--azs", type=int, default=2, help="Availability zones")
    plan.add_argument("--newbits", type=int, default=8, help="New bits for subnetting")
    plan.add_argument("--out", required=True, help="Output JSON path")
    plan.set_defaults(func=cmd_plan)
    validate = sub.add_parser("validate", help="Validate plan JSON")
    validate.add_argument("--file", required=True, help="Path to plan JSON")
    validate.set_defaults(func=cmd_validate)
    generate = sub.add_parser("generate", help="Generate Terraform HCL")
    generate.add_argument("--cidr", required=True, help="VPC CIDR")
    generate.add_argument("--azs", type=int, default=2, help="Availability zones")
    generate.add_argument("--out", default="", help="Output file")
    generate.set_defaults(func=cmd_generate)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
