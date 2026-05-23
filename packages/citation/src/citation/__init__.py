"""Three-stage citation pipeline: JSON synth → Markdown assembly → AST verify. ADR-0013."""

from .assemble import assemble
from .ast_parse import ParsedClaim, ParsedReport, parse_report
from .repair import RepairOutcome, repair_loop
from .schema import Claim, Report, Section, report_json_schema
from .synth import build_messages, synthesise
from .verify import (
    ClaimFailure,
    FailureKind,
    VerificationReport,
    chunks_for_context,
    quote_in_source,
    verify_report,
)

__all__ = [
    "Claim",
    "ClaimFailure",
    "FailureKind",
    "ParsedClaim",
    "ParsedReport",
    "RepairOutcome",
    "Report",
    "Section",
    "VerificationReport",
    "assemble",
    "build_messages",
    "chunks_for_context",
    "parse_report",
    "quote_in_source",
    "repair_loop",
    "report_json_schema",
    "synthesise",
    "verify_report",
]
