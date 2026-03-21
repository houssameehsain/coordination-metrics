"""BCF (BIM Collaboration Format) parser.

Parses BCF-ZIP archives exported from Solibri, BIMcollab, Revizto,
Trimble Connect, Tekla, ArchiCAD, and any BCF-compliant tool.

BCF specification: https://github.com/BuildingSMART/BCF-XML

BCF-ZIP structure::

    bcf.version
    {guid}/markup.bcf    (XML with topic, comments, viewpoints)
    {guid}/viewpoint.bcfv (XML with camera position, components)
    {guid}/snapshot.png   (optional)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from coordination_metrics.core import ClashPoint


@dataclass
class BCFIssue:
    """A single issue/topic extracted from a BCF-ZIP archive."""

    guid: str
    title: str
    status: str  # Active, Resolved, Closed
    type: str  # Clash, Issue, Request, etc.
    priority: str
    creation_date: str
    modified_date: str
    assigned_to: str
    description: str
    # Viewpoint data (if available)
    camera_x: float | None = None
    camera_y: float | None = None
    camera_z: float | None = None
    # Clash point (from selection/visibility)
    point_x: float | None = None
    point_y: float | None = None
    point_z: float | None = None


def parse_bcf_zip(bcf_path: Union[str, Path]) -> list[BCFIssue]:
    """Parse a BCF-ZIP archive and extract all issues/topics.

    Args:
        bcf_path: Path to the ``.bcf`` or ``.bcfzip`` file.

    Returns:
        List of BCFIssue objects with topic metadata and, where
        available, viewpoint camera/clash positions.
    """
    bcf_path = Path(bcf_path)
    issues: list[BCFIssue] = []

    with zipfile.ZipFile(bcf_path, "r") as zf:
        # Find all markup.bcf files
        markup_files = [f for f in zf.namelist() if f.endswith("markup.bcf")]

        for markup_path in markup_files:
            guid = markup_path.split("/")[0]

            try:
                markup_xml = zf.read(markup_path)
                root = ET.fromstring(markup_xml)

                # Handle optional XML namespace
                ns = ""
                if root.tag.startswith("{"):
                    ns = root.tag.split("}")[0] + "}"

                # Parse topic
                topic = root.find(f".//{ns}Topic")
                if topic is None:
                    continue

                issue = BCFIssue(
                    guid=topic.get("Guid", guid),
                    title=_text(topic, f"{ns}Title"),
                    status=_text(topic, f"{ns}TopicStatus", "Active"),
                    type=_text(topic, f"{ns}TopicType", "Issue"),
                    priority=_text(topic, f"{ns}Priority", ""),
                    creation_date=_text(topic, f"{ns}CreationDate", ""),
                    modified_date=_text(topic, f"{ns}ModifiedDate", ""),
                    assigned_to=_text(topic, f"{ns}AssignedTo", ""),
                    description=_text(topic, f"{ns}Description", ""),
                )

                # Try to get viewpoint position
                viewpoint_ref = root.find(f".//{ns}Viewpoints/{ns}ViewPoint")
                if viewpoint_ref is None:
                    # Try without namespace prefix on ViewPoint
                    viewpoint_ref = root.find(f".//Viewpoints/ViewPoint")

                if viewpoint_ref is not None:
                    vp_guid = viewpoint_ref.get("Guid", "")
                    # Try several naming conventions
                    vp_candidates = [
                        f"{guid}/{vp_guid}.bcfv",
                        f"{guid}/viewpoint.bcfv",
                        f"{guid}/{vp_guid}",
                    ]
                    for vp_path in vp_candidates:
                        if vp_path in zf.namelist():
                            try:
                                vp_xml = zf.read(vp_path)
                                vp_root = ET.fromstring(vp_xml)

                                # Detect namespace
                                vp_ns = ""
                                if vp_root.tag.startswith("{"):
                                    vp_ns = vp_root.tag.split("}")[0] + "}"

                                # Camera position (perspective or orthogonal)
                                camera = vp_root.find(
                                    f".//{vp_ns}PerspectiveCamera/{vp_ns}CameraViewPoint"
                                )
                                if camera is None:
                                    camera = vp_root.find(
                                        f".//{vp_ns}OrthogonalCamera/{vp_ns}CameraViewPoint"
                                    )

                                if camera is not None:
                                    issue.camera_x = _float(camera, f"{vp_ns}X")
                                    issue.camera_y = _float(camera, f"{vp_ns}Y")
                                    issue.camera_z = _float(camera, f"{vp_ns}Z")
                                    # Use camera position as approximate
                                    # clash location when no better data
                                    issue.point_x = issue.camera_x
                                    issue.point_y = issue.camera_y
                                    issue.point_z = issue.camera_z
                            except Exception:
                                pass
                            break

                issues.append(issue)

            except Exception:
                continue

    return issues


def bcf_issues_to_clash_points(issues: list[BCFIssue]) -> list[ClashPoint]:
    """Convert BCF issues to ClashPoint objects for recurring clash detection.

    Note: BCF viewpoint camera positions approximate the clash location
    but may be offset by 2-5 metres from the actual clash point. For
    precise spatial recurrence detection, Navisworks XML exports with
    exact clash coordinates are preferred.

    Only issues with spatial data (point_x/y/z) are converted.

    Args:
        issues: List of BCFIssue objects from ``parse_bcf_zip()``.

    Returns:
        List of ClashPoint objects with ``guid`` populated for
        persistent ID matching.
    """
    points: list[ClashPoint] = []
    for issue in issues:
        if issue.point_x is not None:
            # Map BCF status to internal status
            status = issue.status.lower()
            if status in ("closed", "resolved"):
                mapped_status = "resolved"
            elif status == "active":
                mapped_status = "active"
            else:
                mapped_status = "new"

            points.append(
                ClashPoint(
                    clash_id=issue.guid,
                    x=issue.point_x,
                    y=issue.point_y,
                    z=issue.point_z,
                    status=mapped_status,
                    test_name=issue.type,
                    description=issue.title,
                    guid=issue.guid,
                )
            )
    return points


def bcf_to_status_counts(issues: list[BCFIssue]) -> dict:
    """Convert BCF issues to status counts.

    Compatible with Navisworks parser output format for use with
    ``ClashRoundSummary.from_counts()``.

    Args:
        issues: List of BCFIssue objects from ``parse_bcf_zip()``.

    Returns:
        Dict with keys: new, active, reviewed, approved, resolved.
    """
    counts = {"new": 0, "active": 0, "reviewed": 0, "approved": 0, "resolved": 0}
    for issue in issues:
        status = issue.status.lower()
        if status in ("closed", "resolved"):
            counts["resolved"] += 1
        elif status == "active":
            counts["active"] += 1
        elif status in ("reviewed",):
            counts["reviewed"] += 1
        elif status in ("approved",):
            counts["approved"] += 1
        else:
            counts["new"] += 1
    return counts


def _text(element: ET.Element, tag: str, default: str = "") -> str:
    """Extract text from an XML child element."""
    child = element.find(tag)
    return child.text.strip() if child is not None and child.text else default


def _float(element: ET.Element, tag: str) -> float | None:
    """Extract float from an XML child element."""
    child = element.find(tag)
    if child is not None and child.text:
        try:
            return float(child.text.strip())
        except ValueError:
            pass
    return None
