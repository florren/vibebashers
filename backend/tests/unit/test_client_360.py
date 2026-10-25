"""T-091: контакты в карточке клиента маскируются."""

from app.api.clients import _mask_contacts


def test_mask_contacts_hides_phone_and_email() -> None:
    assert _mask_contacts({"phone": "+7 900 000-00-01", "email": "a@example.ru", "city": "Самара"}) == {
        "phone": "***",
        "email": "***",
        "city": "Самара",
    }
