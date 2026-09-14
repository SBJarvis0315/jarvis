from datetime import date

from monthlyreport.period import Period, parse_period, resolve, target_period


def test_routine_on_first_of_month_targets_previous_month():
    period = target_period(date(2026, 10, 1))
    assert (period.year, period.month) == (2026, 9)
    assert period.planner_option == "2026.9"
    assert period.report_prefix == "26.09"
    assert period.snapshot == date(2026, 9, 30)
    assert period.file_tag == "2026-09"


def test_january_run_wraps_to_previous_year():
    period = target_period(date(2027, 1, 1))
    assert (period.year, period.month) == (2026, 12)
    assert period.planner_option == "2026.12"
    assert period.previous.planner_option == "2026.11"


def test_snapshot_is_last_day_including_leap_february():
    assert Period(2028, 2).snapshot == date(2028, 2, 29)
    assert Period(2026, 2).snapshot == date(2026, 2, 28)


def test_report_name_matches_team_convention():
    assert Period(2026, 7).report_name("참포도나무병원") == "26.07 참포도나무병원 리포트"


def test_parse_accepts_the_shapes_people_type():
    for text in ("2026-09", "2026.9", "26.09", " 2026 / 9 "):
        assert parse_period(text) == Period(2026, 9)


def test_explicit_month_overrides_run_date():
    assert resolve("2026-08", run_on=date(2026, 10, 1)) == Period(2026, 8)
