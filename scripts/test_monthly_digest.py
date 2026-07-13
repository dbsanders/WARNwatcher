import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class FakeClientError(Exception):
    def __init__(self, response, operation_name):
        super().__init__(response)
        self.response = response


fake_table = Mock()
fake_ses = Mock()
fake_dynamodb = Mock()
fake_dynamodb.Table.return_value = fake_table
fake_boto3 = types.ModuleType("boto3")
fake_boto3.resource = Mock(return_value=fake_dynamodb)
fake_boto3.client = Mock(return_value=fake_ses)
fake_botocore = types.ModuleType("botocore")
fake_exceptions = types.ModuleType("botocore.exceptions")
fake_exceptions.ClientError = FakeClientError
sys.modules["boto3"] = fake_boto3
sys.modules["botocore"] = fake_botocore
sys.modules["botocore.exceptions"] = fake_exceptions
os.environ["WATCHLISTS_TABLE"] = "watchlists"
os.environ["ALERT_SENDER_EMAIL"] = "alerts@example.com"

module_path = Path(__file__).resolve().parents[1] / "lambda" / "monthly_digest" / "app.py"
spec = importlib.util.spec_from_file_location("monthly_digest_app", module_path)
app = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(app)


class MonthlyDigestTests(unittest.TestCase):
    def setUp(self):
        fake_table.reset_mock(side_effect=True)
        fake_ses.reset_mock(side_effect=True)

    def test_loads_all_pages_and_only_enabled_subscriptions(self):
        fake_table.scan.side_effect = [
            {
                "Items": [
                    {"company": "Acme"},
                    {"company": "Disabled", "is_enabled": False},
                ],
                "LastEvaluatedKey": {"user_id": "1", "watch_id": "2"},
            },
            {"Items": [{"company": "Northwind", "is_enabled": True}]},
        ]

        items = app.load_enabled_subscriptions()

        self.assertEqual(["Acme", "Northwind"], [item["company"] for item in items])
        fake_table.scan.assert_called_with(
            ExclusiveStartKey={"user_id": "1", "watch_id": "2"}
        )

    def test_groups_by_normalized_email_and_deduplicates_companies(self):
        grouped = app.group_companies_by_email(
            [
                {"email": " Person@Example.com ", "company": "Zeta"},
                {"email": "person@example.com", "company": "acme"},
                {"email": "person@example.com", "company": "ACME"},
                {"email": "legacy@example.com", "patterns": [r"Legacy\ Corp"]},
                {"email": "", "company": "Ignored"},
            ]
        )

        self.assertEqual(["acme", "Zeta"], grouped["person@example.com"])
        self.assertEqual(["Legacy Corp"], grouped["legacy@example.com"])

    def test_handler_sends_one_summary_per_subscriber(self):
        with patch.object(
            app,
            "load_enabled_subscriptions",
            return_value=[
                {"email": "one@example.com", "company": "Acme"},
                {"email": "one@example.com", "company": "Northwind"},
                {"email": "two@example.com", "company": "Zeta"},
            ],
        ):
            result = app.handler({}, None)

        self.assertEqual(2, result["sent_count"])
        self.assertEqual(2, fake_ses.send_email.call_count)
        first_message = fake_ses.send_email.call_args_list[0].kwargs["Message"]
        self.assertIn("- Acme", first_message["Body"]["Text"]["Data"])
        self.assertIn("- Northwind", first_message["Body"]["Text"]["Data"])


if __name__ == "__main__":
    unittest.main()
