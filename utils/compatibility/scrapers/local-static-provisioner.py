import re
from collections import OrderedDict

from utils import (
    current_kube_version,
    expand_kube_versions,
    fetch_page,
    get_chart_versions,
    print_error,
    update_compatibility_info,
    validate_semver,
)


APP_NAME = "local-static-provisioner"
COMPATIBILITY_URL = (
    "https://raw.githubusercontent.com/kubernetes-sigs/"
    "sig-storage-local-static-provisioner/master/README.md"
)


def _decode(content):
    return content.decode("utf-8") if isinstance(content, bytes) else content


def _parse_minimum_kube_version(value):
    match = re.fullmatch(r"v?(\d+\.\d+)\+", value.strip())
    return match.group(1) if match else None


def _is_not_future(minimum_kube, latest_kube):
    try:
        minimum = tuple(int(part) for part in minimum_kube.split("."))
        latest = tuple(int(part) for part in latest_kube.split("."))
    except (AttributeError, ValueError):
        return False
    return minimum <= latest


def parse_compatibility_matrix(content, latest_kube):
    rows = OrderedDict()
    in_matrix = False

    for line in _decode(content).splitlines():
        stripped = line.strip()
        if stripped == "## Version Compatibility":
            in_matrix = True
            continue
        if in_matrix and stripped.startswith("## "):
            break
        if not in_matrix or not stripped.startswith("|"):
            continue

        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) != 2 or columns[0] == "Provisioner Version":
            continue
        if all(set(column) <= {"-", ":", " "} for column in columns):
            continue

        version_match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", columns[0])
        minimum_kube = _parse_minimum_kube_version(columns[1])
        if not version_match or not minimum_kube:
            continue
        if not _is_not_future(minimum_kube, latest_kube):
            continue

        version = validate_semver(version_match.group(1))
        if not version:
            continue

        rows[str(version)] = expand_kube_versions(minimum_kube, latest_kube)

    if not rows:
        print_error("No local-static-provisioner compatibility matrix rows found.")
    return rows


def build_rows(compatibility_matrix, chart_versions):
    rows = []
    for app_version, kube_versions in compatibility_matrix.items():
        version_info = OrderedDict(
            [
                ("version", app_version),
                ("kube", kube_versions),
                ("requirements", []),
                ("incompatibilities", []),
            ]
        )

        chart_version = chart_versions.get(app_version)
        if chart_version:
            version_info["chart_version"] = chart_version
            version_info["images"] = []

        rows.append(version_info)

    return rows


def scrape():
    page_content = fetch_page(COMPATIBILITY_URL)
    if not page_content:
        return

    latest_kube = current_kube_version()
    if not latest_kube:
        print_error("No current Kubernetes version available.")
        return

    compatibility_matrix = parse_compatibility_matrix(page_content, latest_kube)
    if not compatibility_matrix:
        return

    chart_versions = get_chart_versions(APP_NAME)
    rows = build_rows(compatibility_matrix, chart_versions)
    if not rows:
        print_error("No local-static-provisioner compatibility rows generated.")
        return

    update_compatibility_info(
        f"../../static/compatibilities/{APP_NAME}.yaml", rows
    )
