"""Allowed rotation placements; shared API metadata for the registration form."""
ROTATION_SITES = {
    'anesthesia': [['', '院内']],
    'outpatient': [['', '院内']],
    'psychiatry': [['', '院内'], ['shin_abuyama', '新阿武山病院']],
    'community': [['takatsuki_nearby', '高槻病院近傍'], ['remote', 'へき地']],
}

def normalize_legacy_rotation(kind, hospital):
    if kind == 'remote':
        return 'community', 'remote'
    if kind == 'community' and hospital == '':
        return 'community', 'takatsuki_nearby'
    return kind, hospital
