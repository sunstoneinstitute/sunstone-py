"""Create UN Amount of Schools Dataset.

This production script processes UN member states data and enriches it with
school count information to create the final UN_amount_of_schools dataset.

Data Flow:
    un_members_raw → scope_countries → scope_countries_iso → UN_amount_of_schools
    schools_manual_raw → schools_curated → UN_amount_of_schools

Output:
    UN_amount_of_schools.csv - Analysis-ready dataset

Author: Data Team
Created: 2025-10-21
Version: 2.0.0
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from io import StringIO

import numpy as np
import pandas as pd
import pycountry
import requests


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Pipeline configuration and constants."""

    # Input data sources
    # The UN Digital Library seems to respond with empty 202 responses from scripts, so we keep a
    # copy of the file in the repo.
    UN_MEMBERS_URL = 'https://digitallibrary.un.org/record/4082085/files/member_states_auths_2025-10-08.csv'
    UN_MEMBERS_FILE = 'inputs/official_un_member_states_raw.csv'  # Fallback local file

    SCHOOLS_MANUAL_FILE = 'inputs/amount_school_data.csv'  # Curated manually

    # Output files
    OUTPUT_FILE = 'outputs/UN_amount_of_schools.csv'

    # Network settings
    REQUEST_TIMEOUT = 30  # seconds
    USE_URL_SOURCE = False  # Set to True to try official source URL first

    # Column names in source data
    COL_MEMBER_STATE = "Member State"
    COL_START_DATE = "Start date"
    COL_END_DATE = "End date"

    # Reference date for membership status
    REFERENCE_DATE = pd.Timestamp.now().normalize()

    # Data validation thresholds
    MIN_SCHOOL_COUNT = 0
    MAX_SCHOOL_COUNT = 6_000_000  # Upper bound for sanity checking

    # Logging
    LOG_FILE = 'pipeline.log'
    LOG_LEVEL = logging.INFO

    # Metadata
    VERSION = '2.0.0'


# =============================================================================
# LOGGING
# =============================================================================

def setup_logging(
    log_file: str = Config.LOG_FILE,
    level: int = Config.LOG_LEVEL
) -> None:
    """Configure logging with file and console output.

    Args:
        log_file: Path to log file.
        level: Logging level.
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )


setup_logging()
logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING UTILITIES
# =============================================================================

def load_csv_from_url(url: str, timeout: int = 30) -> pd.DataFrame:
    """Load CSV data from URL with error handling.

    Args:
        url: URL to CSV file.
        timeout: Request timeout in seconds.

    Returns:
        DataFrame loaded from URL.

    Raises:
        requests.RequestException: If download fails.
        pd.errors.ParserError: If CSV parsing fails.
    """
    try:
        logger.info("Fetching data from URL: %s", url)
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()

        # Load CSV from response content
        df = pd.read_csv(StringIO(response.text))
        logger.info("✓ Successfully loaded %d records from URL", len(df))
        return df

    except requests.Timeout:
        logger.error("Request timed out after %d seconds", timeout)
        raise
    except requests.RequestException as e:
        logger.error("Failed to fetch data from URL: %s", e)
        raise
    except pd.errors.ParserError as e:
        logger.error("Failed to parse CSV from URL: %s", e)
        raise


def load_csv_with_fallback(
    url: Optional[str],
    filepath: str,
    use_url: bool = True,
    timeout: int = 30
) -> pd.DataFrame:
    """Load CSV from URL with fallback to local file.

    Args:
        url: URL to CSV file (optional).
        filepath: Local file path (fallback).
        use_url: Whether to try URL first.
        timeout: Request timeout in seconds.

    Returns:
        DataFrame loaded from URL or local file.

    Raises:
        FileNotFoundError: If both URL and local file fail.
    """
    # Try URL first if enabled
    if use_url and url:
        try:
            return load_csv_from_url(url, timeout)
        except Exception as e:
            logger.warning("URL fetch failed, trying local file: %s", e)

    # Fallback to local file
    if not Path(filepath).exists():
        raise FileNotFoundError(
            f"File not found: {filepath}. "
            f"URL fetch {'disabled' if not use_url else 'also failed'}."
        )

    logger.info("Loading data from local file: %s", filepath)
    df = pd.read_csv(filepath)
    logger.info("✓ Loaded %d records from local file", len(df))
    return df


# =============================================================================
# STAGE 1: UN MEMBER STATES PROCESSING
# =============================================================================

class UNMemberStatesProcessor:
    """Process UN member states to identify current members (scope)."""

    # Status constants
    STATUS_ACTIVE = "Active member"
    STATUS_FUTURE = "Future (not yet active)"
    STATUS_TERMINATED = "Terminated/Withdrawn"
    STATUS_UNKNOWN = "Unknown"

    def __init__(self, config: Config = Config()):
        """Initialize processor.

        Args:
            config: Configuration object.
        """
        self.config = config

    def _split_date_strings(self, cell: str) -> List[str]:
        """Split cell containing multiple dates.

        Args:
            cell: Cell content with dates.

        Returns:
            List of date strings.
        """
        if not isinstance(cell, str) or not cell.strip():
            return []

        # Normalize 'and' to comma
        normalized = re.sub(r"\band\b", ",", cell, flags=re.IGNORECASE)
        parts = re.split(r"[;,]", normalized)
        return [p.strip() for p in parts if p.strip()]

    def _parse_dates(self, items: List[str]) -> List[pd.Timestamp]:
        """Parse date strings to Timestamps.

        Args:
            items: List of date strings.

        Returns:
            List of Timestamps.
        """
        return [pd.to_datetime(x, errors="coerce") for x in items]

    def _to_naive_timestamp(self, ts: pd.Timestamp) -> pd.Timestamp:
        """Convert to naive timestamp (remove timezone).

        Args:
            ts: Timestamp.

        Returns:
            Naive timestamp.
        """
        if pd.isna(ts):
            return ts

        try:
            return ts.tz_localize(None)
        except TypeError:
            try:
                return ts.tz_convert(None).tz_localize(None)
            except Exception:
                return ts

    def _determine_status(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        reference: pd.Timestamp
    ) -> str:
        """Determine membership status for a period.

        Args:
            start: Start date.
            end: End date.
            reference: Reference date.

        Returns:
            Status string.
        """
        if pd.isna(start):
            if pd.isna(end):
                return self.STATUS_UNKNOWN
            return (
                self.STATUS_TERMINATED
                if end <= reference
                else self.STATUS_FUTURE
            )

        if start > reference:
            return self.STATUS_FUTURE

        if pd.isna(end) or end > reference:
            return self.STATUS_ACTIVE

        return self.STATUS_TERMINATED

    def _rollup_status(self, statuses: pd.Series) -> str:
        """Determine overall country status.

        Args:
            statuses: Series of period statuses.

        Returns:
            Overall status.
        """
        if (statuses == self.STATUS_ACTIVE).any():
            return self.STATUS_ACTIVE
        if (statuses == self.STATUS_FUTURE).any():
            return self.STATUS_FUTURE
        if (statuses == self.STATUS_TERMINATED).any():
            return self.STATUS_TERMINATED
        return self.STATUS_UNKNOWN

    def process(
        self,
        filepath: Optional[str] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Process UN member states to extract scope.

        Args:
            filepath: Path to UN members CSV (optional).

        Returns:
            Tuple of (un_members_periods, scope_countries).
        """
        # Store original parameter to determine if URL should be used
        use_custom_filepath = filepath is not None
        if filepath is None:
            filepath = self.config.UN_MEMBERS_FILE

        logger.info("=" * 80)
        logger.info("STAGE 1: UN MEMBER STATES PROCESSING")
        logger.info("=" * 80)
        logger.info("Reference date: %s", self.config.REFERENCE_DATE)

        # Load raw data (URL with fallback to local file)
        un_members_raw = load_csv_with_fallback(
            url=self.config.UN_MEMBERS_URL if not use_custom_filepath else None,
            filepath=filepath,
            use_url=self.config.USE_URL_SOURCE,
            timeout=self.config.REQUEST_TIMEOUT
        )

        # Expand to periods
        period_rows = []
        reference_date = self.config.REFERENCE_DATE

        for _, row in un_members_raw.iterrows():
            starts = [
                self._to_naive_timestamp(x)
                for x in sorted(
                    self._parse_dates(
                        self._split_date_strings(
                            row.get(self.config.COL_START_DATE, "")
                        )
                    )
                )
            ]
            ends = [
                self._to_naive_timestamp(x)
                for x in sorted(
                    self._parse_dates(
                        self._split_date_strings(
                            row.get(self.config.COL_END_DATE, "")
                        )
                    )
                )
            ]

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
                    "_period_status": self._determine_status(
                        start, end, reference_date
                    ),
                }
                period_rows.append(period_record)

        un_members_periods = pd.DataFrame(period_rows)
        logger.info("Expanded to %d membership periods", len(un_members_periods))

        # Country rollup
        name_col = self.config.COL_MEMBER_STATE

        country_status = (
            un_members_periods.groupby(name_col, dropna=False)["_period_status"]
            .apply(self._rollup_status)
            .reset_index()
            .rename(columns={"_period_status": "country_status"})
        )

        first_joined = (
            un_members_periods.groupby(name_col, dropna=False)["_start"]
            .min()
            .reset_index()
            .rename(columns={"_start": "first_joined"})
        )

        last_left = (
            un_members_periods.groupby(name_col, dropna=False)["_end"]
            .max()
            .reset_index()
            .rename(columns={"_end": "last_left"})
        )

        countries_curated = (
            country_status
            .merge(first_joined, on=name_col, how="left")
            .merge(last_left, on=name_col, how="left")
            .sort_values(name_col, kind="stable")
        )

        # Extract scope (active members only)
        scope_countries = (
            countries_curated
            .loc[
                countries_curated["country_status"] == self.STATUS_ACTIVE,
                [name_col, "first_joined", "last_left", "country_status"]
            ]
            .sort_values(name_col, kind="stable")
            .reset_index(drop=True)
        )

        logger.info("Identified %d countries in scope (active members)", len(scope_countries))
        logger.info("✓ Stage 1 complete")

        return un_members_periods, scope_countries


# =============================================================================
# STAGE 2: ISO CODE ENRICHMENT
# =============================================================================

class ISOCodeEnricher:
    """Add ISO Alpha-2 and Alpha-3 codes."""

    # Manual mappings for edge cases
    MANUAL_MAPPINGS = {
        'Bahamas (The)': ('BS', 'BHS'),
        'Bolivia (Plurinational State of)': ('BO', 'BOL'),
        'Democratic Republic of the Congo': ('CD', 'COD'),
        'Gambia (Republic of The)': ('GM', 'GMB'),
        'Guinea Bissau': ('GW', 'GNB'),
        'Iran (Islamic Republic of)': ('IR', 'IRN'),
        "Lao People's Democratic Republic": ('LA', 'LAO'),
        'Lao People\u2019s Democratic Republic': ('LA', 'LAO'),
        'Micronesia (Federated States of)': ('FM', 'FSM'),
        'Netherlands (Kingdom of the)': ('NL', 'NLD'),
        'Republic of Korea': ('KR', 'KOR'),
        'Republic of Moldova': ('MD', 'MDA'),
        'Russian Federation': ('RU', 'RUS'),
        'Syrian Arab Republic': ('SY', 'SYR'),
        'United Kingdom of Great Britain and Northern Ireland': ('GB', 'GBR'),
        'United Republic of Tanzania': ('TZ', 'TZA'),
        'United States of America': ('US', 'USA'),
        'Venezuela (Bolivarian Republic of)': ('VE', 'VEN'),
        'Viet Nam': ('VN', 'VNM'),
    }

    def _get_iso_codes(self, country_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Look up ISO codes for a country.

        Args:
            country_name: Country name.

        Returns:
            Tuple of (alpha_2, alpha_3) or (None, None).
        """
        if pd.isna(country_name) or not country_name:
            return (None, None)

        # Check manual mappings
        if country_name in self.MANUAL_MAPPINGS:
            return self.MANUAL_MAPPINGS[country_name]

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

    def enrich(
        self,
        scope_countries: pd.DataFrame,
        country_col: str = "Member State"
    ) -> pd.DataFrame:
        """Add ISO codes to scope countries.

        Args:
            scope_countries: DataFrame with country names.
            country_col: Name of country column.

        Returns:
            scope_countries_iso with ISO codes added.
        """
        logger.info("=" * 80)
        logger.info("STAGE 2: ISO CODE ENRICHMENT")
        logger.info("=" * 80)

        # Prepare for ISO enrichment
        scope_countries_iso = scope_countries.copy()
        scope_countries_iso.rename(
            columns={country_col: 'Country'},
            inplace=True
        )

        # Add ISO codes
        scope_countries_iso[['Alpha-2 Code', 'Alpha-3 Code']] = (
            scope_countries_iso['Country'].apply(
                lambda x: pd.Series(self._get_iso_codes(x))
            )
        )

        # Rename admission date
        scope_countries_iso.rename(
            columns={'first_joined': 'Date of Admission'},
            inplace=True
        )

        # Statistics
        total = len(scope_countries_iso)
        matched = scope_countries_iso['Alpha-3 Code'].notna().sum()
        match_rate = (matched / total * 100) if total > 0 else 0

        logger.info("Total countries: %d", total)
        logger.info("Matched ISO codes: %d/%d (%.1f%%)", matched, total, match_rate)

        # Log unmatched
        unmatched = scope_countries_iso[scope_countries_iso['Alpha-3 Code'].isna()]
        if not unmatched.empty:
            logger.warning("Unmatched countries (%d):", len(unmatched))
            for country in unmatched['Country'].values:
                logger.warning("  - %s", country)
        else:
            logger.info("✓ All countries matched successfully")

        # Reorder columns
        scope_countries_iso = scope_countries_iso[[
            'Country',
            'Alpha-2 Code',
            'Alpha-3 Code',
            'Date of Admission'
        ]]

        logger.info("✓ Stage 2 complete")
        return scope_countries_iso


# =============================================================================
# STAGE 3: MERGE WITH MANUAL SCHOOL DATA
# =============================================================================

class SchoolDataMerger:
    """Merge scope with manually collected school data."""

    def __init__(self, config: Config = Config()):
        """Initialize merger.

        Args:
            config: Configuration object.
        """
        self.config = config

    def _clean_amount_column(
        self,
        schools_manual_raw: pd.DataFrame
    ) -> pd.DataFrame:
        """Clean and validate school counts.

        Args:
            schools_manual_raw: Raw manual data.

        Returns:
            schools_curated with cleaned amounts.
        """
        schools_curated = schools_manual_raw.copy()

        if 'Amount' not in schools_curated.columns:
            return schools_curated

        try:
            # Remove commas, convert to numeric
            schools_curated['Amount'] = (
                schools_curated['Amount']
                .astype(str)
                .str.replace(',', '', regex=False)
                .str.strip()
                .replace(['', 'nan', 'None'], np.nan)
            )

            schools_curated['Amount'] = pd.to_numeric(
                schools_curated['Amount'],
                errors='coerce'
            )

            # Log issues
            null_count = schools_curated['Amount'].isna().sum()
            if null_count > 0:
                logger.warning("%d rows have null/invalid amounts", null_count)

            # Validate range
            invalid = schools_curated[
                (schools_curated['Amount'].notna()) &
                ((schools_curated['Amount'] < self.config.MIN_SCHOOL_COUNT) |
                 (schools_curated['Amount'] > self.config.MAX_SCHOOL_COUNT))
            ]

            if not invalid.empty:
                logger.warning(
                    "%d rows outside valid range (%d - %d)",
                    len(invalid),
                    self.config.MIN_SCHOOL_COUNT,
                    self.config.MAX_SCHOOL_COUNT
                )

        except Exception as e:
            logger.error("Error cleaning Amount column: %s", e)
            raise

        return schools_curated

    def _standardize_quality(
        self,
        schools_curated: pd.DataFrame
    ) -> pd.DataFrame:
        """Standardize Data Quality values.

        Args:
            schools_curated: Curated school data.

        Returns:
            DataFrame with standardized quality values.
        """
        if 'Data Quality' in schools_curated.columns:
            schools_curated['Data Quality'] = (
                schools_curated['Data Quality']
                .astype(str)
                .str.strip()
                .str.title()
                .replace('Nan', np.nan)
            )
        return schools_curated

    def merge(
        self,
        scope_countries_iso: pd.DataFrame,
        manual_filepath: Optional[str] = None
    ) -> pd.DataFrame:
        """Merge scope with school data to create final dataset.

        Args:
            scope_countries_iso: Scope with ISO codes.
            manual_filepath: Path to manual data CSV (optional).

        Returns:
            UN_amount_of_schools - Final dataset.
        """
        logger.info("=" * 80)
        logger.info("STAGE 3: MERGE WITH MANUAL SCHOOL DATA")
        logger.info("=" * 80)

        if manual_filepath is None:
            manual_filepath = self.config.SCHOOLS_MANUAL_FILE

        # Load manual data
        if not Path(manual_filepath).exists():
            raise FileNotFoundError(f"File not found: {manual_filepath}")

        schools_manual_raw = pd.read_csv(manual_filepath)
        logger.info(
            "Loaded %d records from %s",
            len(schools_manual_raw),
            manual_filepath
        )

        # Standardize column name
        if 'Country Code' in schools_manual_raw.columns:
            schools_manual_raw.rename(
                columns={'Country Code': 'Alpha-2 Code'},
                inplace=True
            )

        # Clean and curate
        schools_curated = self._clean_amount_column(schools_manual_raw)
        schools_curated = self._standardize_quality(schools_curated)

        # Merge
        UN_amount_of_schools = scope_countries_iso.merge(
            schools_curated,
            on='Alpha-2 Code',
            how='left',
            suffixes=('', '_manual')
        )

        # Add metadata
        UN_amount_of_schools['created_at'] = datetime.now()
        UN_amount_of_schools['version'] = self.config.VERSION

        # Statistics
        total = len(scope_countries_iso)
        with_data = UN_amount_of_schools['Amount'].notna().sum()
        coverage = (with_data / total * 100) if total > 0 else 0

        logger.info("✓ Merge complete:")
        logger.info("  - Total countries in scope: %d", total)
        logger.info("  - Countries with school data: %d (%.1f%%)", with_data, coverage)
        logger.info("  - Final dataset size: %d rows", len(UN_amount_of_schools))

        # Log missing data
        missing = UN_amount_of_schools[UN_amount_of_schools['Amount'].isna()]
        if not missing.empty:
            logger.warning("Countries without school data (%d):", len(missing))
            for country in missing['Country'].values[:10]:
                logger.warning("  - %s", country)
            if len(missing) > 10:
                logger.warning("  ... and %d more", len(missing) - 10)

        logger.info("✓ Stage 3 complete")
        return UN_amount_of_schools


# =============================================================================
# DATA QUALITY CHECKS
# =============================================================================

def run_quality_checks(UN_amount_of_schools: pd.DataFrame) -> Dict[str, Any]:
    """Run data quality checks.

    Args:
        UN_amount_of_schools: Final dataset.

    Returns:
        Dictionary with quality metrics.
    """
    logger.info("=" * 80)
    logger.info("DATA QUALITY CHECKS")
    logger.info("=" * 80)

    metrics = {}

    # Duplicates
    dup_count = UN_amount_of_schools.duplicated(subset=['Alpha-2 Code']).sum()
    metrics['duplicates'] = dup_count
    if dup_count > 0:
        logger.warning("Found %d duplicate country codes", dup_count)
    else:
        logger.info("✓ No duplicates")

    # Missing ISO codes
    missing_iso = UN_amount_of_schools['Alpha-3 Code'].isna().sum()
    metrics['missing_iso'] = missing_iso
    if missing_iso > 0:
        logger.warning("%d countries missing ISO codes", missing_iso)
    else:
        logger.info("✓ All countries have ISO codes")

    # Missing amounts
    missing_amounts = UN_amount_of_schools['Amount'].isna().sum()
    metrics['missing_amounts'] = missing_amounts
    logger.info(
        "Countries with school data: %d/%d",
        len(UN_amount_of_schools) - missing_amounts,
        len(UN_amount_of_schools)
    )

    # Amount statistics
    if 'Amount' in UN_amount_of_schools.columns and UN_amount_of_schools['Amount'].notna().any():
        metrics['amount_stats'] = {
            'min': int(UN_amount_of_schools['Amount'].min()),
            'max': int(UN_amount_of_schools['Amount'].max()),
            'mean': float(UN_amount_of_schools['Amount'].mean()),
            'median': float(UN_amount_of_schools['Amount'].median())
        }

        logger.info("School count statistics:")
        for stat_name, stat_value in metrics['amount_stats'].items():
            logger.info("  - %s: %s", stat_name.capitalize(), f"{stat_value:,.0f}")

    # Data quality distribution
    if 'Data Quality' in UN_amount_of_schools.columns:
        quality_dist = UN_amount_of_schools['Data Quality'].value_counts()
        metrics['quality_distribution'] = quality_dist.to_dict()

        logger.info("Data quality distribution:")
        for quality, count in quality_dist.items():
            logger.info("  - %s: %d", quality, count)

    logger.info("✓ Quality checks complete")
    return metrics


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def create_dataset(
    output_filepath: Optional[str] = None,
    include_timestamp: bool = False
) -> pd.DataFrame:
    """Execute complete pipeline to create UN_amount_of_schools dataset.

    Args:
        output_filepath: Output CSV path (optional).
        include_timestamp: Add timestamp to filename.

    Returns:
        UN_amount_of_schools DataFrame.
    """
    start_time = datetime.now()

    logger.info("=" * 80)
    logger.info("UN SCHOOLS DATASET CREATION PIPELINE")
    logger.info("Started: %s", start_time)
    logger.info("=" * 80)

    try:
        # Stage 1: Process UN members to extract scope
        processor = UNMemberStatesProcessor()
        _, scope_countries = processor.process()

        # Stage 2: Enrich with ISO codes
        enricher = ISOCodeEnricher()
        scope_countries_iso = enricher.enrich(
            scope_countries,
            country_col=Config.COL_MEMBER_STATE
        )

        # Stage 3: Merge with school data
        merger = SchoolDataMerger()
        UN_amount_of_schools = merger.merge(scope_countries_iso)

        # Quality checks
        run_quality_checks(UN_amount_of_schools)

        # Save output
        output_path = Path(Config.OUTPUT_FILE if output_filepath is None else output_filepath)

        if include_timestamp:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = (
                output_path.parent /
                f"{output_path.stem}_{timestamp}{output_path.suffix}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        UN_amount_of_schools.to_csv(output_path, index=False)

        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 80)
        logger.info("✓ Pipeline completed successfully")
        logger.info("✓ Output: %s", output_path)
        logger.info("✓ Records: %d", len(UN_amount_of_schools))
        logger.info("✓ Duration: %.2f seconds", duration)
        logger.info("=" * 80)

        return UN_amount_of_schools

    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        raise


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    """Run pipeline when executed as script."""
    UN_amount_of_schools = create_dataset(include_timestamp=False)

    # Display summary
    print("\n" + "=" * 80)
    print("DATASET SUMMARY")
    print("=" * 80)
    print(f"Total countries: {len(UN_amount_of_schools)}")
    print(f"With school data: {UN_amount_of_schools['Amount'].notna().sum()}")
    print("\nFirst 5 rows:")
    print(UN_amount_of_schools.head().to_string(index=False))
    print("\nLast 5 rows:")
    print(UN_amount_of_schools.tail().to_string(index=False))
    print("=" * 80)


if __name__ == "__main__":
    main()
