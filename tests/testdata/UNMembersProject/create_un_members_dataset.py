"""Create Current UN Member States Dataset.

This script processes UN member states data to create a clean list of current members
with ISO country codes.

Output:
    current_un_member_states.csv - List of current UN members with ISO codes

Author: Sunstone Institute
Version: 1.0.0
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import sunstone.pandas as pd
import pycountry

# Project path for dataset registration
PROJECT_PATH = Path(__file__).parent

# Dataset slugs (from datasets.yaml)
INPUT_DATASET_SLUG = "official-un-member-states"
OUTPUT_DATASET_SLUG = "current-un-member-states"

# Output file path
OUTPUT_FILE = "outputs/current_un_member_states.csv"

# Column names in source data
COL_MEMBER_STATE = "Member State"
COL_START_DATE = "Start date"
COL_END_DATE = "End date"

# Reference date for membership status (matches input dataset acquisition date)
REFERENCE_DATE = pd.Timestamp("2025-10-08")

# Logging
LOG_FILE = "pipeline.log"
LOG_LEVEL = logging.INFO

# Metadata
VERSION = "1.0.0"

# Status constants
STATUS_ACTIVE = "Active member"
STATUS_FUTURE = "Future (not yet active)"
STATUS_TERMINATED = "Terminated/Withdrawn"
STATUS_UNKNOWN = "Unknown"


def setup_logging(log_file: str = LOG_FILE, level: int = LOG_LEVEL) -> None:
    """Configure logging with file and console output."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )


logger = logging.getLogger(__name__)


def _split_date_strings(cell: str) -> List[str]:
    """Split cell containing multiple dates separated by semicolons, commas, or 'and'."""
    if not isinstance(cell, str) or not cell.strip():
        return []
    # Replace "and" with comma, then split on semicolons and commas
    normalized = re.sub(r"\band\b", ",", cell, flags=re.IGNORECASE)
    return [p.strip() for p in re.split(r"[;,]", normalized) if p.strip()]


def _parse_dates(items: List[str]) -> List[pd.Timestamp]:
    """Parse date strings to Timestamps."""
    return [pd.to_datetime(x, errors="coerce") for x in items]


def _determine_status(start: pd.Timestamp, end: pd.Timestamp, reference: pd.Timestamp) -> str:
    """Determine membership status for a period."""
    if pd.isna(start):
        if pd.isna(end):
            return STATUS_UNKNOWN
        return STATUS_TERMINATED if end <= reference else STATUS_FUTURE

    if start > reference:
        return STATUS_FUTURE

    if pd.isna(end) or end > reference:
        return STATUS_ACTIVE

    return STATUS_TERMINATED


def _rollup_status(statuses: pd.Series) -> str:
    """Determine overall country status."""
    if (statuses == STATUS_ACTIVE).any():
        return STATUS_ACTIVE
    if (statuses == STATUS_FUTURE).any():
        return STATUS_FUTURE
    if (statuses == STATUS_TERMINATED).any():
        return STATUS_TERMINATED
    return STATUS_UNKNOWN


def process_un_members(dataset_slug: Optional[str] = None) -> pd.DataFrame:
    """Process UN member states to extract current members.

    Args:
        dataset_slug: Optional dataset slug to load. If None, uses INPUT_DATASET_SLUG.
    """
    if dataset_slug is None:
        dataset_slug = INPUT_DATASET_SLUG

    logger.info("Processing UN member states (reference date: %s)", REFERENCE_DATE)

    # Load raw data by slug - sunstone.pandas handles URL fetching automatically
    un_members_raw = pd.read_csv(dataset_slug, project_path=PROJECT_PATH)

    # Expand to periods
    period_rows = []

    for _, row in un_members_raw.iterrows():
        starts = sorted(_parse_dates(_split_date_strings(row.get(COL_START_DATE, ""))))
        ends = sorted(_parse_dates(_split_date_strings(row.get(COL_END_DATE, ""))))

        max_periods = max(len(starts), len(ends), 1)

        for i in range(max_periods):
            start = starts[i] if i < len(starts) else pd.NaT
            end = ends[i] if i < len(ends) else pd.NaT

            # Fix inverted dates
            if not pd.isna(start) and not pd.isna(end) and end < start:
                later = [x for x in ends[i:] if not pd.isna(x) and x >= start]
                end = later[0] if later else end

            period_record = {
                **row.to_dict(),
                "_period_index": i + 1,
                "_start": start,
                "_end": end,
                "_period_status": _determine_status(start, end, REFERENCE_DATE),
            }
            period_rows.append(period_record)

    # Create DataFrame preserving lineage from source
    un_members_periods = pd.DataFrame(period_rows, lineage=un_members_raw.lineage, project_path=PROJECT_PATH)

    # Country rollup - groupby returns regular pandas, need to wrap back
    country_status_data = (
        un_members_periods.groupby(COL_MEMBER_STATE, dropna=False)["_period_status"]
        .apply(_rollup_status)
        .reset_index()
        .rename(columns={"_period_status": "country_status"})
    )

    first_joined_data = (
        un_members_periods.groupby(COL_MEMBER_STATE, dropna=False)["_start"]
        .min()
        .reset_index()
        .rename(columns={"_start": "first_joined"})
    )

    # Merge preserving lineage - need to wrap in Sunstone DataFrames
    country_status = pd.DataFrame(country_status_data, lineage=un_members_periods.lineage, project_path=PROJECT_PATH)
    first_joined = pd.DataFrame(first_joined_data, lineage=un_members_periods.lineage, project_path=PROJECT_PATH)

    countries_curated = country_status.merge(first_joined, on=COL_MEMBER_STATE, how="left").sort_values(
        COL_MEMBER_STATE, kind="stable"
    )

    # Extract current members only - preserve lineage
    current_members_data = (
        countries_curated.loc[
            countries_curated["country_status"] == STATUS_ACTIVE,
            [COL_MEMBER_STATE, "first_joined", "country_status"],
        ]
        .sort_values(COL_MEMBER_STATE, kind="stable")
        .reset_index(drop=True)
    )

    # Wrap in Sunstone DataFrame with lineage
    current_members = pd.DataFrame(current_members_data, lineage=un_members_periods.lineage, project_path=PROJECT_PATH)

    logger.info("Identified %d current UN members", len(current_members))
    return current_members


# Manual ISO code mappings for edge cases
ISO_MANUAL_MAPPINGS = {
    "Bahamas (The)": ("BS", "BHS"),
    "Bolivia (Plurinational State of)": ("BO", "BOL"),
    "Democratic Republic of the Congo": ("CD", "COD"),
    "Gambia (Republic of The)": ("GM", "GMB"),
    "Guinea Bissau": ("GW", "GNB"),
    "Iran (Islamic Republic of)": ("IR", "IRN"),
    "Lao People's Democratic Republic": ("LA", "LAO"),
    "Lao People\u2019s Democratic Republic": ("LA", "LAO"),
    "Micronesia (Federated States of)": ("FM", "FSM"),
    "Netherlands (Kingdom of the)": ("NL", "NLD"),
    "Republic of Korea": ("KR", "KOR"),
    "Republic of Moldova": ("MD", "MDA"),
    "Russian Federation": ("RU", "RUS"),
    "Syrian Arab Republic": ("SY", "SYR"),
    "United Kingdom of Great Britain and Northern Ireland": ("GB", "GBR"),
    "United Republic of Tanzania": ("TZ", "TZA"),
    "United States of America": ("US", "USA"),
    "Venezuela (Bolivarian Republic of)": ("VE", "VEN"),
    "Viet Nam": ("VN", "VNM"),
}


def _get_iso_codes(country_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Look up ISO codes for a country."""
    if pd.isna(country_name) or not country_name:
        return (None, None)

    # Check manual mappings
    if country_name in ISO_MANUAL_MAPPINGS:
        return ISO_MANUAL_MAPPINGS[country_name]

    try:
        # Try exact match
        country = pycountry.countries.get(name=country_name)
        if country:
            return (country.alpha_2, country.alpha_3)

        # Try fuzzy search
        results = pycountry.countries.search_fuzzy(country_name)
        if results:
            return (results[0].alpha_2, results[0].alpha_3)

    except (LookupError, AttributeError) as e:
        logger.debug("Could not find ISO codes for '%s': %s", country_name, e)

    return (None, None)


def enrich_with_iso_codes(current_members: pd.DataFrame, country_col: str = "Member State") -> pd.DataFrame:
    """Add ISO codes to current members."""
    # Prepare for ISO enrichment
    result = current_members.copy()
    result.rename(columns={country_col: "Country"}, inplace=True)

    # Add ISO codes
    result[["Alpha-2 Code", "Alpha-3 Code"]] = result["Country"].apply(lambda x: pd.Series(_get_iso_codes(x)))

    # Rename admission date
    result.rename(columns={"first_joined": "Date of Admission"}, inplace=True)

    # Statistics
    total = len(result)
    matched = result["Alpha-3 Code"].notna().sum()
    match_rate = (matched / total * 100) if total > 0 else 0

    logger.info("ISO code enrichment: %d/%d matched (%.1f%%)", matched, total, match_rate)

    # Log unmatched
    unmatched = result[result["Alpha-3 Code"].isna()]
    if not unmatched.empty:
        logger.warning("Unmatched countries: %s", ", ".join(unmatched["Country"].values))

    # Reorder columns
    result = result[["Country", "Alpha-2 Code", "Alpha-3 Code", "Date of Admission"]]

    return result


def create_dataset(output_filepath: Optional[str] = None, include_timestamp: bool = False) -> pd.DataFrame:
    """Execute pipeline to create current UN member states dataset."""
    start_time = datetime.now()

    logger.info("Starting UN member states dataset pipeline")

    try:
        # Process UN members to extract current members
        current_members = process_un_members()

        # Enrich with ISO codes (preserves lineage)
        enriched_data = enrich_with_iso_codes(current_members, country_col=COL_MEMBER_STATE)

        # Add metadata columns (modifying in place preserves lineage)
        enriched_data["version"] = VERSION

        # enriched_data is already a Sunstone DataFrame with lineage
        current_un_members = enriched_data

        # Save output
        output_path = Path(OUTPUT_FILE if output_filepath is None else output_filepath)

        if include_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_path.parent / f"{output_path.stem}_{timestamp}{output_path.suffix}"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Use sunstone.pandas to_csv with slug for proper lineage tracking
        current_un_members.to_csv(output_path, slug=OUTPUT_DATASET_SLUG, name="Current UN Member States", index=False)

        # Summary
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Pipeline completed: %d records written to %s (%.2f seconds)",
            len(current_un_members),
            output_path,
            duration,
        )

        return current_un_members

    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        raise


def main():
    """Run pipeline when executed as script."""
    setup_logging()
    current_un_members = create_dataset(include_timestamp=False)

    # Display summary
    print(f"\nDataset created: {len(current_un_members)} current UN members")
    print("\nFirst 5 countries:")
    print(current_un_members.head().to_string(index=False))
    print("\nLast 5 countries:")
    print(current_un_members.tail().to_string(index=False))


if __name__ == "__main__":
    main()
