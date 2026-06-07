# filter_plugins/compliance.py


def _parse_version(v):
    """Convert a dotted version string to a comparable tuple of ints.
    Unparseable strings return (0,) — fails any minimum-version check (safe default).
    """
    try:
        return tuple(int(x) for x in str(v).split('.'))
    except (ValueError, AttributeError):
        return (0,)


def check_firmware(live_entries, required_list):
    """Compare live firmware inventory against a baseline required list.

    Args:
        live_entries: list of dicts from redfish_facts.firmware.entries
        required_list: list of {name, min_version} dicts from baseline YAML

    Returns:
        list of finding dicts: {name, required, actual, status}
    """
    # Build a lookup: component name → version from live data
    live = {}
    for entry in live_entries:
        name = entry.get('Name', '')
        version = entry.get('Version', 'NOT_FOUND')
        # If duplicate names exist, keep the highest version
        if name not in live or _parse_version(version) > _parse_version(live[name]):
            live[name] = version

    findings = []
    for req in required_list:
        name = req['name']
        min_ver = req['min_version']
        actual = live.get(name, 'NOT_FOUND')
        compliant = _parse_version(actual) >= _parse_version(min_ver)
        findings.append({
            'name': name,
            'required': min_ver,
            'actual': actual,
            'status': 'PASS' if compliant else 'FAIL',
        })
    return findings


def check_bios(live_bios, required_attrs):
    """Compare live BIOS attributes against required values.

    Args:
        live_bios: dict of attribute_name → value from redfish_facts
        required_attrs: dict of attribute_name → required_value from baseline YAML

    Returns:
        list of finding dicts: {attribute, required, actual, status}
    """
    findings = []
    for attr, required_val in required_attrs.items():
        actual = live_bios.get(attr, 'NOT_FOUND')
        compliant = str(actual) == str(required_val)
        findings.append({
            'attribute': attr,
            'required': required_val,
            'actual': actual,
            'status': 'PASS' if compliant else 'FAIL',
        })
    return findings


class FilterModule:
    def filters(self):
        return {
            'check_firmware': check_firmware,
            'check_bios': check_bios,
        }
