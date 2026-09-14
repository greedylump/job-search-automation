import pytest

from jobsearch.evaluation.rules import evaluate
from jobsearch.storage.applicant_repository import ApplicantRepository


@pytest.mark.parametrize("preference,actual,expected", [
    (None, None, "keep"), ("any", "unfamiliar", "keep"),
    ("remote", " REMOTE ", "keep"), ("hybrid", "hybrid", "keep"),
    ("onsite", "onsite", "keep"), ("remote", "onsite", "reject"),
    ("hybrid", "remote", "reject"), ("onsite", "hybrid", "reject"),
    ("remote", None, "review"), ("remote", "flexible", "review"),
])
def test_remote(preference, actual, expected):
    assert evaluate({"remote_preference": preference}, {"remote_type": actual}).decision == expected


@pytest.mark.parametrize("preferred,actual,expected", [
    ([], None, "keep"), ([" Seattle,  WA "], "seattle, wa", "keep"),
    (["Seattle, WA"], "Portland, OR", "reject"),
    (["Seattle, WA"], "Seattle", "reject"),
    (["Seattle, WA"], None, "review"), (["Seattle, WA"], "Remote", "review"),
    (["Seattle, WA"], "Remote - US only", "review"),
    (["Remote"], "Remote", "review"), (["Remote"], "Seattle, WA", "review"),
    (["Seattle, WA"], "Seattle, WA / Portland, OR", "review"),
    (["Seattle, WA"], "Multiple locations", "review"),
    (["Seattle, WA", "Portland, OR"], "Portland, OR", "keep"),
])
def test_location(preferred, actual, expected):
    assert evaluate({"preferred_locations": preferred}, {"location": actual}).decision == expected


@pytest.mark.parametrize("roles,title,expected", [
    ([], None, "keep"), (["data engineer"], " Senior DATA   Engineer II ", "keep"),
    (["data engineer"], "Data Engineering Manager", "reject"),
    (["engineer"], "Bioengineer", "reject"),
    (["developer"], "Software Engineer", "reject"),
    (["Data Engineer", "Developer"], "Developer (Python)", "keep"),
    (["C++ Developer"], "Senior C++ Developer", "keep"),
    (["Engineer"], None, "review"), (["Engineer"], " ", "review"),
    ([" "], "Engineer", "review"),
])
def test_role(roles, title, expected):
    assert evaluate({"target_roles": roles}, {"title": title}).decision == expected


@pytest.mark.parametrize("changes,expected", [
    ({}, "keep"), ({"salary_min": 101}, "keep"),
    ({"salary_min": 99, "salary_max": 99}, "reject"),
    ({"salary_min": 99, "salary_max": 100}, "review"),
    ({"salary_min": 99, "salary_max": 101}, "review"),
    ({"salary_min": 100, "salary_max": 100}, "keep"),
    ({"salary_min": None}, "review"), ({"salary_max": None}, "review"),
    ({"salary_min": 201}, "review"), ({"salary_min": -1}, "review"),
    ({"salary_max": float("inf")}, "review"), ({"salary_min": float("nan")}, "review"),
    ({"salary_min": True}, "review"), ({"salary_min": "100"}, "review"),
    ({"salary_currency": "EUR"}, "review"), ({"salary_currency": None}, "review"),
    ({"salary_currency": " usd "}, "keep"), ({"salary_period": "ANNUAL"}, "keep"),
    ({"salary_period": "hourly"}, "review"), ({"salary_period": None}, "review"),
    ({"salary_period": "fortnightly"}, "review"),
])
def test_salary(changes, expected):
    preferences = {"minimum_salary": 100, "salary_currency": "USD", "salary_period": "annual"}
    job = {"salary_min": 100, "salary_max": 200, "salary_currency": "USD", "salary_period": "annual", **changes}
    assert evaluate(preferences, job).decision == expected


@pytest.mark.parametrize("changes,expected", [
    ({"minimum_salary": None}, "keep"), ({"minimum_salary": 0}, "keep"),
    ({"salary_currency": None}, "review"), ({"salary_period": None}, "review"),
    ({"salary_currency": "dollars"}, "review"), ({"minimum_salary": float("inf")}, "review"),
])
def test_salary_preferences(changes, expected):
    preferences = {"minimum_salary": 100, "salary_currency": "USD", "salary_period": "annual", **changes}
    job = {"salary_min": 100, "salary_max": 200, "salary_currency": "USD", "salary_period": "annual"}
    assert evaluate(preferences, job).decision == expected


def test_all_checks_and_reject_precedence():
    result = evaluate({"remote_preference": "remote", "preferred_locations": ["Example City"],
                       "target_roles": ["Engineer"], "minimum_salary": 100},
                      {"remote_type": "onsite", "title": "Engineer"})
    assert result.decision == "reject"
    assert [(reason["check"], reason["outcome"]) for reason in result.reasons] == [
        ("remote", "reject"), ("location", "review"), ("role", "keep"), ("salary", "review")]
    assert all(reason["message"] for reason in result.reasons)


def test_unset_preferences_impose_no_restrictions():
    assert evaluate({}, {}).decision == "keep"
    assert evaluate({"salary_currency": "USD", "salary_period": "annual"}, {}).decision == "keep"


@pytest.mark.parametrize("period", [" Hourly ", "weekly", "MONTHLY", "annual", None])
def test_period_validation_and_normalization(period):
    repo = ApplicantRepository(None)
    repo.validate_payload({"salary_period": period}, partial=True)
    assert repo._normalized({"salary_period": period})["salary_period"] == (period.strip().lower() if period else None)


@pytest.mark.parametrize("period", ["", "yearly", "fortnightly", 12, True])
def test_invalid_period(period):
    with pytest.raises(ValueError, match="salary_period"):
        ApplicantRepository(None).validate_payload({"salary_period": period}, partial=True)
