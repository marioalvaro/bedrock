"""scenario cases: scenario_case, driver_value.case_id, scenario.base_id dropped

A scenario holds exactly three cases, `base`, `bull` and `bear`; Bull and Bear are overrides on
their scenario's Base (docs/erd/forecasting.md "Scenarios and cases"). The flat Base, Bull and
Bear scenarios of a company become one scenario "Main" with its cases; another scenario becomes
its own scenario with its value rows on `base`.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-31

"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CASES = ("base", "bull", "bear")
SCENARIO_BASE_CHECK = (
    "(is_default = 1 AND base_id IS NULL) OR (is_default = 0 AND base_id IS NOT NULL)"
)
DRIVER_COLUMNS = (
    "id, driver_code, fiscal_year, fiscal_period, kind, value, source, engine_code, "
    "created_at, updated_at"
)


def _rebuild_without_cascades() -> None:
    """Rebuilding `scenario` drops the old table, and with foreign keys on SQLite then deletes
    every row that cascades from it (G34). The pragma is a no-op once a statement has opened a
    transaction, so this runs before anything else."""
    op.execute("PRAGMA foreign_keys=OFF")


def _create_driver_value(table: str, key: str, parent: str) -> None:
    """`driver_value` keyed by `key` (a column of `parent`); the 0009 table, its key aside."""
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(key, sa.Integer(), nullable=False),
        sa.Column("driver_code", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("engine_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("fiscal_period = 'FY'", name=op.f("ck_driver_value_fiscal_period")),
        sa.CheckConstraint("kind IN ('value', 'offset')", name=op.f("ck_driver_value_kind")),
        sa.CheckConstraint("source IN ('manual', 'engine')", name=op.f("ck_driver_value_source")),
        sa.ForeignKeyConstraint(
            [key],
            [f"{parent}.id"],
            name=op.f(f"fk_driver_value_{key}_{parent}"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driver_value")),
        sa.UniqueConstraint(
            key,
            "driver_code",
            "fiscal_year",
            "fiscal_period",
            name=op.f(f"uq_driver_value_{key}"),
        ),
    )


def _swap_driver_value(key: str) -> None:
    """Replaces `driver_value` by `driver_value_new` (built with `key`), keeping every row that
    has a `key`."""
    op.execute(
        f"INSERT INTO driver_value_new ({key}, {DRIVER_COLUMNS}) "
        f"SELECT {key}, {DRIVER_COLUMNS} FROM driver_value WHERE {key} IS NOT NULL"
    )
    op.drop_table("driver_value")
    op.rename_table("driver_value_new", "driver_value")


def _free_name(wanted: str, taken: Collection[str]) -> str:
    """`wanted`, or `wanted 2`, `wanted 3`… when the company already has a scenario of that name."""
    name, number = wanted, 1
    while name in taken:
        number += 1
        name = f"{wanted} {number}"
    return name


def _by_company(scenarios: Sequence[Mapping[str, Any]]) -> dict[int, list[Mapping[str, Any]]]:
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for scenario in scenarios:
        grouped.setdefault(scenario["company_id"], []).append(scenario)
    return grouped


def upgrade() -> None:
    _rebuild_without_cascades()
    op.create_table(
        "scenario_case",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("case", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "\"case\" IN ('base', 'bull', 'bear')", name=op.f("ck_scenario_case_case")
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_scenario_case_scenario_id_scenario"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_case")),
        sa.UniqueConstraint("scenario_id", "case", name=op.f("uq_scenario_case_scenario_id")),
    )
    op.add_column("driver_value", sa.Column("case_id", sa.Integer(), nullable=True))
    superseded = _move_into_cases()
    _create_driver_value("driver_value_new", "case_id", "scenario_case")
    _swap_driver_value("case_id")
    for scenario_id in superseded:
        op.execute(sa.text("DELETE FROM scenario WHERE id = :id").bindparams(id=scenario_id))
    with op.batch_alter_table("scenario") as batch:
        batch.drop_constraint(op.f("ck_scenario_base"), type_="check")
        batch.drop_constraint(op.f("fk_scenario_base_id_scenario"), type_="foreignkey")
        batch.drop_column("base_id")


def _move_into_cases() -> list[int]:
    """Gives every scenario its cases and points its driver rows at them; returns the ids of the
    old Bull and Bear scenarios, which the default scenario's cases replace. A company with
    scenarios but no default one (impossible under the old CHECK and its cascade) is left as it
    is, and its driver rows are dropped with the swap."""
    bind = op.get_bind()
    scenarios = (
        bind.execute(
            sa.text(
                "SELECT id, company_id, name, is_default, base_id, created_at, updated_at "
                "FROM scenario ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    superseded: list[int] = []
    for owned in _by_company(scenarios).values():
        default = next((s for s in owned if s["is_default"]), None)
        if default is None:
            continue
        folded = {
            s["name"].lower(): s
            for s in owned
            if not s["is_default"]
            and s["base_id"] == default["id"]
            and s["name"] in ("Bull", "Bear")
        }
        kept = [s for s in owned if s not in folded.values()]
        case_of = {(s["id"], case): _add_case(bind, s, case) for s in kept for case in CASES}
        for s in kept:
            if s is not default:  # an offset on the old Base has no Base to offset
                bind.execute(
                    sa.text("DELETE FROM driver_value WHERE scenario_id = :id AND kind = 'offset'"),
                    {"id": s["id"]},
                )
            _point_rows(bind, s["id"], case_of[(s["id"], "base")])
        for case, s in folded.items():
            _point_rows(bind, s["id"], case_of[(default["id"], case)])
            superseded.append(s["id"])
        taken = {s["name"] for s in kept if s is not default}
        bind.execute(
            sa.text("UPDATE scenario SET name = :name WHERE id = :id"),
            {"name": _free_name("Main", taken), "id": default["id"]},
        )
    return superseded


def _add_case(bind: sa.Connection, scenario: Mapping[str, Any], case: str) -> int:
    result = bind.execute(
        sa.text(
            'INSERT INTO scenario_case (scenario_id, "case", created_at, updated_at) '
            "VALUES (:scenario_id, :case, :created_at, :updated_at)"
        ),
        {
            "scenario_id": scenario["id"],
            "case": case,
            "created_at": scenario["created_at"],
            "updated_at": scenario["updated_at"],
        },
    )
    return int(result.lastrowid)


def _point_rows(bind: sa.Connection, scenario_id: int, case_id: int) -> None:
    bind.execute(
        sa.text("UPDATE driver_value SET case_id = :case_id WHERE scenario_id = :scenario_id"),
        {"case_id": case_id, "scenario_id": scenario_id},
    )


def downgrade() -> None:
    _rebuild_without_cascades()
    with op.batch_alter_table("scenario") as batch:
        batch.add_column(sa.Column("base_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_scenario_base_id_scenario"),
            "scenario",
            ["base_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.add_column("driver_value", sa.Column("scenario_id", sa.Integer(), nullable=True))
    _flatten()
    _create_driver_value("driver_value_new", "scenario_id", "scenario")
    _swap_driver_value("scenario_id")
    op.drop_table("scenario_case")
    with op.batch_alter_table("scenario") as batch:
        batch.create_check_constraint(op.f("ck_scenario_base"), SCENARIO_BASE_CHECK)


def _flatten() -> None:
    """Each scenario's `base` becomes a flat scenario (the default one "Base"); the default
    scenario's `bull` and `bear` become "Bull" and "Bear", another scenario's "<name> Bull" and
    "<name> Bear" when they hold rows, all on the default one as their Base, with their
    scenario's settings."""
    bind = op.get_bind()
    scenarios = (
        bind.execute(
            sa.text(
                "SELECT id, company_id, name, is_default, revenue_method, segment_dimension, "
                "volume_kpi, price_kpi, created_at, updated_at FROM scenario ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    cases = {
        (r["scenario_id"], r["case"]): r["id"]
        for r in bind.execute(
            sa.text('SELECT id, scenario_id, "case" FROM scenario_case')
        ).mappings()
    }
    for owned in _by_company(scenarios).values():
        default = next((s for s in owned if s["is_default"]), None)
        if default is None:
            continue
        # The default scenario's flat scenarios keep the plain names the upgrade looks for; a user
        # scenario that has one of them gives it up ("Bull" becomes "Bull 2").
        reserved = {"Base", "Bull", "Bear"}
        taken = set(reserved)
        for s in owned:
            if s is not default:
                name = _free_name(s["name"], taken) if s["name"] in reserved else s["name"]
                taken.add(name)
                if name != s["name"]:
                    bind.execute(
                        sa.text("UPDATE scenario SET name = :name WHERE id = :id"),
                        {"name": name, "id": s["id"]},
                    )
        bind.execute(
            sa.text("UPDATE scenario SET name = 'Base' WHERE id = :id"), {"id": default["id"]}
        )
        for s in owned:
            if s is not default:
                bind.execute(
                    sa.text("UPDATE scenario SET base_id = :base WHERE id = :id"),
                    {"base": default["id"], "id": s["id"]},
                )
            bind.execute(
                sa.text("UPDATE driver_value SET scenario_id = :id WHERE case_id = :case"),
                {"id": s["id"], "case": cases[(s["id"], "base")]},
            )
            for case in ("bull", "bear"):
                case_id = cases[(s["id"], case)]
                held = bind.execute(
                    sa.text("SELECT count(*) FROM driver_value WHERE case_id = :case"),
                    {"case": case_id},
                ).scalar_one()
                if not (s is default or held):
                    continue
                label = case.capitalize()
                name = label if s is default else _free_name(f"{s['name']} {label}", taken)
                taken.add(name)
                flat = bind.execute(
                    sa.text(
                        "INSERT INTO scenario (company_id, name, is_default, base_id, "
                        "revenue_method, segment_dimension, volume_kpi, price_kpi, created_at, "
                        "updated_at) VALUES (:company_id, :name, 0, :base, :revenue_method, "
                        ":segment_dimension, :volume_kpi, :price_kpi, :created_at, :updated_at)"
                    ),
                    {
                        **{k: s[k] for k in s.keys() if k not in ("id", "name", "is_default")},
                        "name": name,
                        "base": default["id"],
                    },
                ).lastrowid
                bind.execute(
                    sa.text("UPDATE driver_value SET scenario_id = :id WHERE case_id = :case"),
                    {"id": flat, "case": case_id},
                )
