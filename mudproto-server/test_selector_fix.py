#!/usr/bin/env python3
"""Test script to validate equipment selector fix."""

import sys
sys.path.insert(0, '.')

from equipment import _parse_selector

# Test cases for equipment selector fixing
test_cases = [
    ("arcanist.robe", ["arcanist", "robe"]),
    ("training.dagger", ["training", "dagger"]),
    ("patrol.token", ["patrol", "token"]),
    ("robe", ["robe"]),
    ("leather.armor", ["leather", "armor"]),
]

print("Testing equipment selector parsing:")
print("-" * 50)

all_pass = True
for selector, expected in test_cases:
    index, keywords, error = _parse_selector(selector)
    passed = keywords == expected and error is None
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"{status}: _parse_selector('{selector}')")
    print(f"  Expected keywords: {expected}")
    print(f"  Got keywords:      {keywords}")
    if error:
        print(f"  Error: {error}")
    if not passed:
        all_pass = False
    print()

print("-" * 50)
if all_pass:
    print("All tests PASSED!")
else:
    print("Some tests FAILED!")
    sys.exit(1)
