from datetime import timedelta
import io

import pytest

from app import create_app, timeutil, validators_tutor as vt
from app.services import file_service, payment_service, request_service as rs, subject_service
from app.services import tutor_service, user_service
from app.routes import tutor as tutor_routes
from config import Config


class PaymentConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-not-a-real-secret"
    WTF_CSRF_ENABLED = False


def test_tutor_rates_require_a_valid_price_for_each_duration():
    rates, errors = vt.validate_subject_rates(
        {"rate_30_4": "150", "rate_60_4": "300", "rate_90_4": "400", "rate_120_4": "600"},
        [4],
    )

    assert errors == []
    assert rates == {4: {30: 150, 60: 300, 90: 400, 120: 600}}


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "100001", "invalid"])
def test_tutor_rates_reject_nonpositive_or_invalid_prices(value):
    _rates, errors = vt.validate_subject_rates(
        {"rate_30_4": value, "rate_60_4": "300", "rate_90_4": "400", "rate_120_4": "600"},
        [4],
    )

    assert len(errors) == 1


def test_tutor_payment_details_are_validated():
    details, errors = vt.validate_payment_details({
        "payment_method": "gcash",
        "payment_account_name": "Tutor Name",
        "payment_account_number": "09171234567",
    })

    assert errors == []
    assert details == {
        "method": "gcash",
        "account_name": "Tutor Name",
        "account_number": "09171234567",
    }


def test_payment_proof_rejects_non_image_and_non_pdf():
    with pytest.raises(file_service.FileError):
        payment_service.validate_proof("receipt.txt", b"receipt")


def test_accept_action_is_hidden_until_payment_is_verified():
    unpaid = {"status": "pending", "payment_amount": 300, "payment_status": "submitted"}
    paid = {"status": "pending", "payment_amount": 300, "payment_status": "verified"}

    assert "accept" not in rs.available_actions(unpaid, "tutor")
    assert "accept" in rs.available_actions(paid, "tutor")


def test_tutor_can_review_submitted_payment(monkeypatch):
    app = create_app(PaymentConfig)
    user = {"id": 8, "full_name": "Tutor", "email": "tutor@example.test",
            "role": "tutor", "is_active": 1}
    calls = []
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    monkeypatch.setattr(rs, "update_payment_status",
                        lambda request_id, tutor_id, status:
                        calls.append((request_id, tutor_id, status)) or (True, "Payment proof verified."))

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 8
    response = client.post("/requests/12/payment/verify")

    assert response.status_code == 302
    assert calls == [(12, 8, "verified")]


def test_payment_review_requires_tutor_role(monkeypatch):
    app = create_app(PaymentConfig)
    user = {"id": 8, "full_name": "Student", "email": "student@example.test",
            "role": "student", "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 8

    assert client.post("/requests/12/payment/reject").status_code == 403


def test_student_reviews_price_and_submits_payment_proof(monkeypatch):
    app = create_app(PaymentConfig)
    user = {"id": 9, "full_name": "Student", "email": "student@example.test",
            "role": "student", "is_active": 1}
    tutor = {
        "id": 3, "full_name": "Tutor", "availability": [], "tutoring_format": "both",
        "payment_method": "gcash", "payment_account_name": "Tutor Account",
        "payment_account_number": "09171234567",
    }
    options = [{"id": 4, "name": "Algebra", "rate_30": 150, "rate_60": 300,
                "rate_90": 450, "rate_120": 600}]
    calls = []
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    monkeypatch.setattr(tutor_service, "get_public_tutor", lambda _id: tutor)
    monkeypatch.setattr(rs, "tutor_subject_options", lambda _id: options)
    monkeypatch.setattr(payment_service, "validate_proof", lambda _name, _data: "png")
    monkeypatch.setattr(
        rs, "create_request",
        lambda _student_id, _tutor_id, data, **kwargs:
        calls.append((data, kwargs)) or (18, None),
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 9

    start = timeutil.to_local(timeutil.utcnow()) + timedelta(days=3)
    booking = {
        "subject_id": "4", "topic": "Linear equations", "description": "",
        "format": "online", "date": start.strftime("%Y-%m-%d"),
        "time": "10:00", "duration": "30",
    }
    review = client.post("/student/tutors/3/request", data={"step": "review", **booking})
    assert review.status_code == 200 and "₱150" in review.get_data(as_text=True)
    assert "09171234567" in review.get_data(as_text=True)
    assert calls[-1][1]["dry_run"] is True

    confirmation = {
        **booking, "step": "confirm", "expected_payment_amount": "150",
        "expected_payment_method": "gcash", "expected_account_name": "Tutor Account",
        "expected_account_number": "09171234567",
        "payment_proof": (io.BytesIO(b"proof"), "receipt.png"),
    }
    response = client.post("/student/tutors/3/request", data=confirmation,
                           content_type="multipart/form-data")

    assert response.status_code == 302
    assert calls[-1][1]["dry_run"] is False
    assert calls[-1][1]["proof_kind"] == "png"
    assert calls[-1][1]["proof_data"] == b"proof"


def test_tutor_rate_inputs_are_one_per_duration_and_blank_when_unset(monkeypatch):
    app = create_app(PaymentConfig)
    user = {"id": 8, "full_name": "Tutor", "email": "tutor@example.test",
            "role": "tutor", "is_active": 1}
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    monkeypatch.setattr(tutor_routes.subject_service, "list_subjects",
                        lambda: [{"id": 4, "name": "Algebra", "category": "Math"}])
    monkeypatch.setattr(tutor_service, "get_format", lambda _id: "both")
    monkeypatch.setattr(tutor_service, "get_tutor_subjects", lambda _id: [{
        "subject_id": 4, "name": "Algebra", "topics": "",
        "rate_30": 0, "rate_60": 0, "rate_90": 0, "rate_120": 0,
    }])
    monkeypatch.setattr(user_service, "get_profile", lambda *_args: {
        "payment_method": "gcash", "payment_account_name": "Tutor",
        "payment_account_number": "09171234567",
    })
    monkeypatch.setattr(subject_service, "tutor_subject_requests", lambda _id: [])
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 8

    html = client.get("/tutor/subjects").get_data(as_text=True)

    assert html.count('class="rate-row"') == 8
    for duration in (30, 60, 90, 120):
        assert f"{duration} minutes (₱)" in html
        assert f'id="rate_{duration}_4"' in html
        assert f'name="rate_{duration}_4"' in html
        assert f'id="new_rate_{duration}"' in html
    assert 'id="rate_30_4" name="rate_30_4"\n                       type="number" min="1" max="100000" step="1"\n                       value=""' in html


def test_new_subject_request_requires_name_and_four_rates():
    data, errors = vt.validate_new_subject_request({
        "subject_name": "Robotics",
        "subject_category": "Engineering",
        "subject_topics": "Sensors",
        "new_rate_30": "150",
        "new_rate_60": "300",
        "new_rate_90": "450",
        "new_rate_120": "600",
    })

    assert errors == []
    assert data == {
        "name": "Robotics",
        "category": "Engineering",
        "topics": "Sensors",
        "rates": {30: 150, 60: 300, 90: 450, 120: 600},
    }


def test_tutor_can_submit_a_subject_request_for_review(monkeypatch):
    app = create_app(PaymentConfig)
    user = {"id": 8, "full_name": "Tutor", "email": "tutor@example.test",
            "role": "tutor", "is_active": 1}
    calls = []
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    monkeypatch.setattr(subject_service, "create_tutor_subject_request",
                        lambda tutor_id, data: calls.append((tutor_id, data)) or 27)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 8

    response = client.post("/tutor/subjects/request", data={
        "subject_name": "Robotics", "subject_category": "Engineering",
        "subject_topics": "Sensors", "new_rate_30": "150",
        "new_rate_60": "300", "new_rate_90": "450", "new_rate_120": "600",
    })

    assert response.status_code == 302
    assert calls == [(8, {
        "name": "Robotics", "category": "Engineering", "topics": "Sensors",
        "rates": {30: 150, 60: 300, 90: 450, 120: 600},
    })]


def test_only_admin_can_approve_a_subject_request(monkeypatch):
    app = create_app(PaymentConfig)
    user = {"id": 2, "full_name": "Admin", "email": "admin@example.test",
            "role": "admin", "is_active": 1}
    calls = []
    monkeypatch.setattr(user_service, "get_user_by_id", lambda _id: user)
    monkeypatch.setattr(subject_service, "review_subject_request",
                        lambda request_id, admin_id, decision:
                        calls.append((request_id, admin_id, decision)) or True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 2

    response = client.post("/admin/subject-requests/27/approve")

    assert response.status_code == 302
    assert calls == [(27, 2, "approved")]
