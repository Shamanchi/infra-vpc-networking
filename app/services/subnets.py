"""Планировщик подсетей VPC и валидация. Без сети."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

from pydantic import BaseModel, Field


class SubnetInfo(BaseModel):
    cidr: str
    az: str
    tier: str
    usable_hosts: int


class VpcPlan(BaseModel):
    vpc_cidr: str
    azs: int = Field(ge=1, le=6)
    newbits: int = Field(ge=1, le=16)
    subnets: list[SubnetInfo]


def _parse_cidr(value: str, field: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"{field}: invalid CIDR {value!r}") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError(f"{field}: only IPv4 CIDR supported, got {value!r}")
    return network


def plan_vpc(vpc_cidr: str, azs: int = 2, newbits: int = 8) -> VpcPlan:
    """Нарезать VPC на public/private подсети по зонам. Детерминировано."""
    if azs < 1 or azs > 6:
        raise ValueError("azs must be 1..6")
    if newbits < 1 or newbits > 16:
        raise ValueError("newbits must be 1..16")
    vpc = _parse_cidr(vpc_cidr, "vpc_cidr")
    need = azs * 2
    try:
        subnets = list(vpc.subnets(prefixlen_diff=newbits))
    except ValueError as exc:
        raise ValueError(f"CIDR {vpc} too small for newbits {newbits}") from exc
    if len(subnets) < need:
        raise ValueError(f"CIDR {vpc} too small for {azs} AZs x 2 tiers with newbits {newbits}")
    result: list[SubnetInfo] = []
    for idx in range(azs):
        pub = subnets[idx]
        priv = subnets[idx + azs]
        for tier, net in (("public", pub), ("private", priv)):
            usable = max(int(net.num_addresses) - 5, 0) if net.prefixlen < 31 else 0
            result.append(
                SubnetInfo(
                    cidr=str(net),
                    az=f"az-{idx + 1}",
                    tier=tier,
                    usable_hosts=usable,
                )
            )
    # Сортировка: public сначала, затем private, внутри по AZ.
    result.sort(key=lambda s: (0 if s.tier == "public" else 1, s.az))
    return VpcPlan(vpc_cidr=str(vpc), azs=azs, newbits=newbits, subnets=result)


def validate_plan(plan: VpcPlan) -> list[str]:
    """Проверить план на пересечения и выход за VPC."""
    errors: list[str] = []
    vpc = _parse_cidr(plan.vpc_cidr, "vpc_cidr")
    nets: list[ipaddress.IPv4Network] = []
    for info in plan.subnets:
        try:
            net = ipaddress.ip_network(info.cidr, strict=False)
        except ValueError:
            errors.append(f"subnet {info.cidr}: invalid CIDR")
            continue
        if not isinstance(net, ipaddress.IPv4Network):
            errors.append(f"subnet {info.cidr}: only IPv4 supported")
            continue
        if not net.subnet_of(vpc):
            errors.append(f"subnet {info.cidr} is outside VPC {vpc}")
        nets.append(net)
    for i, a in enumerate(nets):
        for j, b in enumerate(nets):
            if j <= i:
                continue
            if a.overlaps(b):
                errors.append(f"overlap: {a} overlaps {b}")
    if len(plan.subnets) != plan.azs * 2:
        errors.append(f"expected {plan.azs * 2} subnets, got {len(plan.subnets)}")
    return errors


def load_plan(path: str | Path) -> VpcPlan:
    """Прочитать план из JSON."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read plan file: {exc}") from exc
    return VpcPlan.model_validate(data)


def save_plan(plan: VpcPlan, path: str | Path) -> None:
    """Сохранить план в JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def generate_hcl(vpc_cidr: str, azs: int = 2, region: str = "eu-central-1") -> str:
    """Сгенерировать VPC + подсети + IGW/NAT в HCL."""
    plan = plan_vpc(vpc_cidr, azs, newbits=8)
    lines = [
        f'# Generated VPC {plan.vpc_cidr} in {region}',
        'terraform { required_version = ">= 1.5" }',
        "",
        'resource "aws_vpc" "main" {',
        f'  cidr_block = "{plan.vpc_cidr}"',
        "}",
        "",
        'resource "aws_internet_gateway" "igw" {',
        "  vpc_id = aws_vpc.main.id",
        "}",
    ]
    for info in plan.subnets:
        lines += [
            "",
            f'resource "aws_subnet" "{info.tier}_{info.az}" {{',
            "  vpc_id     = aws_vpc.main.id",
            f'  cidr_block = "{info.cidr}"',
            f'  availability_zone = "{region}{chr(96 + int(info.az.split("-")[1]))}"',
            f'  map_public_ip_on_launch = {"true" if info.tier == "public" else "false"}',
            "}",
        ]
    return "\n".join(lines) + "\n"
