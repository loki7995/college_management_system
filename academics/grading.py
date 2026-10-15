"""Configurable examination marks calculation and grading rules.

Defaults are defined in ``ACADEMIC_MARKS_RULES`` in Django settings. Change
those values to update the validation limits, pass criteria, and grade bands.
"""

from decimal import Decimal

from django.conf import settings


def marks_rules():
    return settings.ACADEMIC_MARKS_RULES


def calculate_outcome(internal_marks, external_marks):
    rules = marks_rules()
    total = (internal_marks + external_marks).quantize(Decimal('0.01'))
    percentage = ((total / Decimal('100')) * Decimal('100')).quantize(Decimal('0.01'))
    grade = next(
        grade
        for boundary, grade in rules['grade_boundaries']
        if percentage >= Decimal(str(boundary))
    )
    passed = (
        total >= Decimal(str(rules['passing_total']))
        and external_marks >= Decimal(str(rules['passing_external_min']))
    )
    return {
        'total_marks': total,
        'percentage': percentage,
        'grade': grade,
        'result': 'PASS' if passed else 'FAIL',
    }
