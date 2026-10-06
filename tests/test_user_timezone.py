from datetime import datetime, timezone

from app.domain.user_timezone import timezone_from_browser_offset


def test_browser_offset_turns_a_utc_night_measurement_into_the_users_local_date() -> None:
    measured_at = datetime(2026, 10, 6, 0, 10, tzinfo=timezone.utc)

    # Colombia: getTimezoneOffset() = 300 -> UTC-5 -> todavía es 5 de octubre.
    assert measured_at.astimezone(timezone_from_browser_offset(300)).date().isoformat() == "2026-10-05"
    # Al este de UTC (p. ej. España en verano, -120) la fecha no retrocede.
    assert measured_at.astimezone(timezone_from_browser_offset(-120)).date().isoformat() == "2026-10-06"
