DEPARTMENT_CHOICES = (
    ('Computer Science and Engineering (CSE)', 'Computer Science and Engineering (CSE)'),
    (
        'Electronics and Communication Engineering (ECE)',
        'Electronics and Communication Engineering (ECE)',
    ),
    (
        'Electrical and Electronics Engineering (EEE)',
        'Electrical and Electronics Engineering (EEE)',
    ),
    ('Mechanical Engineering (ME)', 'Mechanical Engineering (ME)'),
    ('Civil Engineering (CE)', 'Civil Engineering (CE)'),
    ('Information Technology (IT)', 'Information Technology (IT)'),
    (
        'Artificial Intelligence and Machine Learning (AI & ML)',
        'Artificial Intelligence and Machine Learning (AI & ML)',
    ),
    (
        'Artificial Intelligence and Data Science (AI & DS)',
        'Artificial Intelligence and Data Science (AI & DS)',
    ),
    (
        'Computer Science and Engineering — Data Science (CSE-DS)',
        'Computer Science and Engineering — Data Science (CSE-DS)',
    ),
    (
        'Computer Science and Engineering — Cyber Security (CSE-CS)',
        'Computer Science and Engineering — Cyber Security (CSE-CS)',
    ),
    (
        'Computer Science and Engineering — Internet of Things (CSE-IoT)',
        'Computer Science and Engineering — Internet of Things (CSE-IoT)',
    ),
    ('Chemical Engineering', 'Chemical Engineering'),
    ('Biotechnology', 'Biotechnology'),
    ('Aeronautical Engineering', 'Aeronautical Engineering'),
    ('Agricultural Engineering', 'Agricultural Engineering'),
    ('Other / Not Listed', 'Other / Not Listed'),
)


def department_choices(existing_department=''):
    choices = list(DEPARTMENT_CHOICES)
    allowed_values = {value for value, _label in DEPARTMENT_CHOICES}
    if existing_department and existing_department not in allowed_values:
        choices.append(
            (
                existing_department,
                f'{existing_department} (existing value)',
            )
        )
    return tuple(choices)
