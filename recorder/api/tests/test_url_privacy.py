import pytest

from core.url_privacy import sanitize_url

KEEP = [
    # SAP Fiori: app and object live in the fragment
    "https://erp.acme.com/sap/bc/ui2/flp#PurchaseOrder-manage&/C_PurchaseOrderTP('4500012345')",
    "https://erp.acme.com/sap/bc/ui2/flp?sap-client=100&sap-language=EN#Supplier-displayFactSheet",
    # Search terms, filters, paging, tabs, record ids, UUIDs
    "https://www.google.com/search?q=overdue+invoices+q3",
    "https://app.example.com/invoices?status=overdue&sort=-amount&page=3",
    "https://wd5.myworkday.com/acme/d/task/2998$10079.htmld#TABINDEX=1",
    "https://app.example.com/#/orders/4500012345?tab=items",
    "https://chatgpt.com/c/6ac7351a-6660-83ec-88f7-74040310d5a2",
    "https://app.example.com/report?author=smith&country_code=IN",
]


@pytest.mark.parametrize("url", KEEP)
def test_useful_state_is_kept(url):
    assert sanitize_url(url) == url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://app.example.com/callback#access_token=ya29.a0AfH6SM&token_type=Bearer&expires_in=3599",
         "https://app.example.com/callback#access_token=[SECRET]&token_type=Bearer&expires_in=3599"),
        ("https://app.example.com/oauth?code=4/0AY0e-g7abc&state=xyz",
         "https://app.example.com/oauth?code=[SECRET]&state=xyz"),
        ("https://app.example.com/home?sessionid=8f2a9c&lang=en",
         "https://app.example.com/home?sessionid=[SECRET]&lang=en"),
        ("https://s3.amazonaws.com/b/report.pdf?X-Amz-Credential=AKIA123&X-Amz-Signature=abc123&X-Amz-Expires=300",
         "https://s3.amazonaws.com/b/report.pdf?X-Amz-Credential=[SECRET]&X-Amz-Signature=[SECRET]&X-Amz-Expires=300"),
        ("https://maps.example.com/api?key=AIzaSyD123&zoom=4",
         "https://maps.example.com/api?key=[SECRET]&zoom=4"),
        ("https://app.example.com/users?email=jane.doe@acme.com&role=admin",
         "https://app.example.com/users?email=[EMAIL_ADDRESS]&role=admin"),
        ("https://app.example.com/profile/jane.doe%40acme.com/settings",
         "https://app.example.com/profile/[EMAIL_ADDRESS]/settings"),
        ("https://user:hunter2@intranet.acme.com/wiki",
         "https://intranet.acme.com/wiki"),
    ],
)
def test_secrets_and_personal_data_are_redacted(url, expected):
    assert sanitize_url(url) == expected


def test_jwt_and_long_secrets_anywhere_are_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    assert jwt not in sanitize_url(f"https://app.example.com/#/view?state={jwt}")
    secret = "A" * 30 + "b9F2kQ7xZ1" * 3
    assert secret not in sanitize_url(f"https://app.example.com/download/{secret}")


def test_empty_and_invalid():
    assert sanitize_url(None) is None
    assert sanitize_url("") is None
