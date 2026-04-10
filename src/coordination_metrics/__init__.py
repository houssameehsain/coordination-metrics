"""coordination-metrics: Metrics that predict design coordination failure before it hits site.

Designed for BIM managers, design coordinators, and digital engineering leads
working on complex AEC projects.

Core metrics:
    - Hard Clash Trajectory Slope — are clashes trending up or down?
    - Recurring Clash Rate — do resolved clashes keep coming back?
    - First-Submission Approval Rate — how clean are submittals by discipline?
    - RFI Response Time Distribution — where are the bottleneck disciplines?
    - Meeting Decision Resolution Rate — are coordination meetings productive?
    - Earned Coordination Value (ECV) — is coordination on schedule?
"""

__version__ = "0.2.0"

from coordination_metrics.core import (
    ClashPoint,
    ClashRoundSummary,
    CoordinationHealth,
    HealthLevel,
    MeetingSummary,
)
from coordination_metrics.clash_trajectory import (
    build_trajectory,
    compute_trajectory_slope,
)
from coordination_metrics.recurring_clashes import (
    detect_recurrences,
    extract_clash_points,
)
from coordination_metrics.approval_rates import (
    compute_approval_rates,
    cross_reference_with_rfis,
)
from coordination_metrics.rfi_distribution import analyse_rfi_distribution
from coordination_metrics.meeting_decisions import (
    compute_attendance_decision_correlation,
    parse_meeting_csv,
)
from coordination_metrics.dashboard import CoordinationHealthDashboard
from coordination_metrics.cross_correlation import (
    CrossCorrelation,
    discover_cross_correlations,
)
from coordination_metrics.ecv import (
    ECVConfig,
    ECVSnapshot,
    compute_ecv,
    compute_ecv_trend,
)
from coordination_metrics.benchmarks import (
    Benchmark,
    compare_to_benchmark,
    generate_benchmark_report,
    get_benchmark,
)

__all__ = [
    "Benchmark",
    "ClashPoint",
    "ClashRoundSummary",
    "CoordinationHealth",
    "CoordinationHealthDashboard",
    "CrossCorrelation",
    "ECVConfig",
    "ECVSnapshot",
    "HealthLevel",
    "MeetingSummary",
    "analyse_rfi_distribution",
    "build_trajectory",
    "compare_to_benchmark",
    "compute_approval_rates",
    "compute_attendance_decision_correlation",
    "compute_ecv",
    "compute_ecv_trend",
    "compute_trajectory_slope",
    "cross_reference_with_rfis",
    "detect_recurrences",
    "discover_cross_correlations",
    "extract_clash_points",
    "generate_benchmark_report",
    "get_benchmark",
    "parse_meeting_csv",
]
