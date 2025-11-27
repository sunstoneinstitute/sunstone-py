# Security Report: sunstone-py Library

**Date:** 2025-11-27
**Reviewed Version:** 0.1.0
**Reviewer:** Security Analysis (Automated)

---

## Executive Summary

The sunstone-py library is a Python package providing DataFrame wrappers with lineage tracking for data science workflows. The security review identified **2 Medium**, **3 Low**, and **2 Informational** findings. No Critical or High severity vulnerabilities were found.

The most significant concerns involve:
1. **Server-Side Request Forgery (SSRF)** potential in the URL fetching functionality
2. **Path traversal** risks in file operations that could write outside project boundaries

The library follows several security best practices including use of `yaml.safe_load()` for YAML parsing and subprocess argument lists (avoiding shell injection).

---

## Findings Summary

| Severity | Count | Description |
|----------|-------|-------------|
| Critical | 0 | - |
| High | 0 | - |
| Medium | 2 | SSRF in URL fetching, Path traversal in file writes |
| Low | 3 | Missing URL validation, Unbounded file writes, Log injection |
| Informational | 2 | Dependency considerations, Environment variable usage |

---

## Detailed Findings

### MEDIUM-01: Server-Side Request Forgery (SSRF) in URL Fetching

**Location:** `src/sunstone/datasets.py:360-365`

**Description:**
The `fetch_from_url()` method fetches data from URLs specified in `datasets.yaml` without validating that the URL points to a safe, external resource. An attacker who can control the `source.location.data` field in `datasets.yaml` could cause the library to make requests to internal network resources.

**Vulnerable Code:**
```python
url = dataset.source.location.data
logger.info("Fetching dataset from URL: %s", url)
response = requests.get(url, timeout=timeout)
```

**Impact:**
- Access to internal network services (cloud metadata endpoints, internal APIs)
- Port scanning of internal infrastructure
- Exfiltration of internal service responses

**Risk Assessment:**
Medium - Requires attacker control over datasets.yaml content, which is typically version-controlled. However, in multi-contributor environments or if datasets.yaml is auto-generated, this could be exploited.

**Remediation:**
1. Validate URLs against an allowlist of permitted domains
2. Block requests to private IP ranges (10.x.x.x, 172.16.x.x-172.31.x.x, 192.168.x.x, 169.254.x.x)
3. Block requests to localhost and link-local addresses
4. Consider disabling redirect following or validating redirect targets

**Example Fix:**
```python
from urllib.parse import urlparse
import ipaddress

def is_safe_url(url: str) -> bool:
    """Validate URL is safe to fetch (not internal/private)."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False
    try:
        # Resolve hostname and check if IP is private
        import socket
        ip = socket.gethostbyname(parsed.hostname)
        return not ipaddress.ip_address(ip).is_private
    except (socket.gaierror, ValueError):
        return False
```

---

### MEDIUM-02: Path Traversal in File Write Operations

**Location:** `src/sunstone/dataframe.py:369-371`, `src/sunstone/datasets.py:367-371`

**Description:**
The `to_csv()` method and `fetch_from_url()` write files to paths derived from user input without validating that the resulting path stays within the project directory. Path traversal sequences (`../`) in the location field could cause files to be written outside the intended directory.

**Vulnerable Code (dataframe.py:369-371):**
```python
absolute_path = manager.get_absolute_path(dataset.location)
absolute_path.parent.mkdir(parents=True, exist_ok=True)
self.data.to_csv(absolute_path, **kwargs)
```

**Vulnerable Code (datasets.py:367-371):**
```python
local_path.parent.mkdir(parents=True, exist_ok=True)
with open(local_path, "wb") as f:
    f.write(response.content)
```

**Impact:**
- Arbitrary file write outside project directory
- Potential code execution if writing to locations like `.bashrc`, cron directories, or SSH authorized_keys
- Configuration file overwrite

**Risk Assessment:**
Medium - Requires attacker control over location fields in datasets.yaml. The `mkdir(parents=True)` call amplifies the risk by creating directory structures.

**Remediation:**
1. Validate that resolved paths are within the project directory
2. Use `Path.resolve()` and check with `is_relative_to()` (Python 3.9+) or similar logic

**Example Fix:**
```python
def get_absolute_path(self, location: str) -> Path:
    """Get the absolute path for a dataset location (with validation)."""
    location_path = Path(location)
    if location_path.is_absolute():
        resolved = location_path.resolve()
    else:
        resolved = (self.project_path / location_path).resolve()

    # Validate path is within project directory
    try:
        resolved.relative_to(self.project_path)
    except ValueError:
        raise ValueError(f"Path '{location}' escapes project directory")

    return resolved
```

---

### LOW-01: Missing URL Scheme Validation

**Location:** `src/sunstone/datasets.py:360`

**Description:**
The URL fetching functionality does not validate the URL scheme before making requests. While `requests` library handles this gracefully, explicitly validating schemes prevents potential issues.

**Impact:**
- Potential for `file://` scheme abuse (though requests blocks this by default)
- Could be used with custom protocol handlers if installed

**Remediation:**
Explicitly validate URL scheme is `http` or `https` before fetching.

---

### LOW-02: Unbounded Content Write from HTTP Response

**Location:** `src/sunstone/datasets.py:371-372`

**Description:**
When fetching data from URLs, the entire response content is read into memory and written to disk without size limits. This could lead to denial of service through memory exhaustion or disk space exhaustion.

**Vulnerable Code:**
```python
with open(local_path, "wb") as f:
    f.write(response.content)
```

**Impact:**
- Memory exhaustion if response is very large
- Disk space exhaustion
- Denial of service

**Remediation:**
1. Implement maximum content length check using `Content-Length` header
2. Use streaming download with chunk size limits
3. Validate against expected file sizes if known

---

### LOW-03: Log Injection Potential

**Location:** `src/sunstone/datasets.py:361, 374`

**Description:**
User-controlled data (URLs and file paths) is logged without sanitization. While using Python's logging module, injection of newlines or control characters could manipulate log output.

**Vulnerable Code:**
```python
logger.info("Fetching dataset from URL: %s", url)
logger.info("Successfully saved to %s (%d bytes)", local_path, len(response.content))
```

**Impact:**
- Log file manipulation
- Log injection attacks
- Potential SIEM/monitoring evasion

**Remediation:**
Sanitize logged values by removing or escaping newlines and control characters.

---

### INFO-01: Dependency Security Considerations

**Location:** `pyproject.toml:26-32`

**Description:**
The library depends on several external packages. Regular dependency auditing is recommended.

**Dependencies:**
- `frictionless>=5.18.1` - Data validation library
- `google-auth>=2.43.0` - Google authentication
- `pandas>=2.0.0` - Data manipulation
- `pyyaml>=6.0` - YAML parsing (uses safe_load, good)
- `requests>=2.31.0` - HTTP client

**Recommendations:**
1. Run `pip-audit` or similar tools regularly
2. Pin exact versions in production deployments
3. Monitor security advisories for dependencies
4. Consider using `dependabot` or `renovate` for automated updates

---

### INFO-02: Environment Variable Usage

**Location:** `src/sunstone/dataframe.py:71-72`

**Description:**
The library reads `SUNSTONE_DATAFRAME_STRICT` environment variable to determine strict mode behavior. This is a low-risk pattern but worth documenting.

**Code:**
```python
env_strict = os.environ.get("SUNSTONE_DATAFRAME_STRICT", "").lower()
self.strict_mode = env_strict in ("1", "true")
```

**Recommendations:**
1. Document all environment variables in README
2. Consider using a configuration file for complex settings
3. Validate environment variable values

---

## Positive Security Observations

The following security best practices were observed in the codebase:

1. **Safe YAML Parsing** (`datasets.py:48`)
   - Uses `yaml.safe_load()` instead of `yaml.load()`, preventing arbitrary code execution

2. **Safe Subprocess Usage** (`_release.py:23-28`)
   - Uses argument list format `["git", *args]` instead of shell strings, preventing shell injection

3. **Explicit File Encoding** (`validation.py:108`)
   - Specifies `encoding="utf-8"` when reading files, preventing encoding-related issues

4. **Type Hints Throughout**
   - Comprehensive type annotations help prevent type confusion issues

5. **No Dynamic Code Execution**
   - No use of `eval()`, `exec()`, or similar dangerous functions

6. **HTTP Timeout Configured** (`datasets.py:364`)
   - Uses timeout parameter to prevent hanging requests

---

## Recommendations

### Immediate Actions (Before Production)

1. **Implement URL validation** to prevent SSRF attacks
2. **Implement path validation** to prevent directory traversal
3. **Add content size limits** for URL fetching

### Short-term Improvements

4. Set up automated dependency vulnerability scanning
5. Add input validation for all user-provided strings (slugs, names)
6. Implement logging sanitization

### Long-term Considerations

7. Consider adding integrity checks (checksums) for downloaded files
8. Add rate limiting for URL fetching
9. Implement proper secret management if credentials are needed
10. Add security-focused unit tests

---

## Testing Recommendations

Consider adding the following security-focused tests:

```python
def test_path_traversal_blocked():
    """Ensure path traversal attempts are blocked."""
    with pytest.raises(ValueError):
        manager.get_absolute_path("../../../etc/passwd")

def test_ssrf_internal_ip_blocked():
    """Ensure internal IPs cannot be fetched."""
    dataset.source.location.data = "http://169.254.169.254/metadata"
    with pytest.raises(ValueError):
        manager.fetch_from_url(dataset)

def test_url_scheme_validation():
    """Ensure only http/https schemes are allowed."""
    dataset.source.location.data = "file:///etc/passwd"
    with pytest.raises(ValueError):
        manager.fetch_from_url(dataset)
```

---

## Conclusion

The sunstone-py library has a solid security foundation with several best practices in place. The identified issues are primarily related to input validation and could be exploited in multi-contributor environments where datasets.yaml content is not fully trusted. Implementing the recommended remediations will significantly improve the security posture of the library.

**Overall Risk Rating:** Low-Medium (suitable for internal/controlled environments; additional hardening recommended for production use with untrusted input)
