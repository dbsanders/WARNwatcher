"""Isolated auth abuse-limit tests; no AWS credentials or network are needed."""

import importlib.util
import io
import json
import os
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch


class FakeBotoCoreError(Exception):
    pass


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class Condition:
    def __init__(self, operation, attribute=None, value=None, children=()):
        self.operation = operation
        self.attribute = attribute
        self.value = value
        self.children = children

    def __or__(self, other):
        return Condition("or", children=(self, other))

    def allows(self, item):
        if self.operation == "or":
            return any(child.allows(item) for child in self.children)
        if self.operation == "not_exists":
            return self.attribute not in item
        if self.operation == "lt":
            return item.get(self.attribute, 0) < self.value
        raise AssertionError(self.operation)


class Attr:
    def __init__(self, name):
        self.name = name

    def not_exists(self):
        return Condition("not_exists", self.name)

    def lt(self, value):
        return Condition("lt", self.name, value)


class RateTable:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()
        self.fail = False

    def update_item(self, **kwargs):
        if self.fail:
            raise FakeClientError("InternalServerError")
        self._check_update_shape(kwargs)
        key = kwargs["Key"]["limit_key"]
        with self.lock:
            item = self.items.get(key, {})
            if not kwargs["ConditionExpression"].allows(item):
                raise FakeClientError("ConditionalCheckFailedException")
            self.items[key] = {
                "request_count": item.get("request_count", 0) + kwargs["ExpressionAttributeValues"][":one"],
                "expires_at": kwargs["ExpressionAttributeValues"][":expires_at"],
            }

    @staticmethod
    def _check_update_shape(kwargs):
        assert kwargs["UpdateExpression"] == "SET expires_at = :expires_at ADD request_count :one"
        assert isinstance(kwargs["ConditionExpression"], Condition)
        assert kwargs["ExpressionAttributeValues"][":one"] == 1


rate_table = RateTable()
users_table = Mock()
fake_dynamodb = Mock()
fake_dynamodb.Table.side_effect = lambda name: {
    "rate_limits": rate_table,
    "users": users_table,
}.get(name, Mock())
fake_boto3 = types.ModuleType("boto3")
fake_boto3.resource = Mock(return_value=fake_dynamodb)
fake_boto3.client = Mock(return_value=Mock())
fake_conditions = types.ModuleType("boto3.dynamodb.conditions")
fake_conditions.Attr = Attr
fake_conditions.Key = Mock()
fake_botocore = types.ModuleType("botocore")
fake_exceptions = types.ModuleType("botocore.exceptions")
fake_exceptions.BotoCoreError = FakeBotoCoreError
fake_exceptions.ClientError = FakeClientError

with patch.dict(sys.modules, {
    "boto3": fake_boto3,
    "boto3.dynamodb": types.ModuleType("boto3.dynamodb"),
    "boto3.dynamodb.conditions": fake_conditions,
    "botocore": fake_botocore,
    "botocore.exceptions": fake_exceptions,
}), patch.dict(os.environ, {
    "WATCHLISTS_TABLE": "watchlists",
    "NOTICES_TABLE": "notices",
    "NOTIFICATIONS_TABLE": "notifications",
    "USERS_TABLE": "users",
    "AUTH_RATE_LIMITS_TABLE": "rate_limits",
    "AUTH_TOKEN_SECRET": "test-only-secret",
    "ALERT_SENDER_EMAIL": "alerts@example.com",
    "PASSWORD_RESET_FROM_EMAIL": "reset@example.com",
    "WEB_APP_BASE_URL": "https://example.com",
}):
    module_path = Path(__file__).resolve().parents[1] / "lambda" / "watchlist_api" / "app.py"
    spec = importlib.util.spec_from_file_location("watchlist_api_rate_test", module_path)
    app = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(app)


def event(path, body, source_ip="192.0.2.1"):
    return {
        "rawPath": path,
        "body": json.dumps(body),
        "requestContext": {"http": {"method": "POST", "sourceIp": source_ip}},
    }


class AuthRateLimitTests(unittest.TestCase):
    def setUp(self):
        rate_table.items.clear()
        rate_table.fail = False
        users_table.reset_mock(side_effect=True)
        users_table.get_item.return_value = {}
        self.clock = patch.object(app.time, "time", return_value=3600)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_shared_source_budget_covers_malformed_requests_across_routes(self):
        malformed = event("/login", {})
        malformed["body"] = "[1, 2]"
        for _ in range(30):
            self.assertEqual(400, app.handler(malformed, None)["statusCode"])

        output = io.StringIO()
        with redirect_stdout(output):
            blocked = app.handler(event("/reset-password", {"token": "invalid", "password": "newpassword"}), None)
        self.assertEqual(429, blocked["statusCode"])
        self.assertEqual("300", blocked["headers"]["Retry-After"])
        self.assertEqual(
            {"event": "rate_limit_exceeded", "route": "reset-password", "dimension": "source"},
            json.loads(output.getvalue()),
        )
        self.assertNotIn("192.0.2.1", str(rate_table.items))

    def test_login_budget_follows_account_across_source_addresses(self):
        users_table.get_item.return_value = {}
        for index in range(10):
            result = app.handler(event("/login", {"email": "Person@example.com", "password": "wrong"}, f"192.0.2.{index + 1}"), None)
            self.assertEqual(401, result["statusCode"])
        with redirect_stdout(io.StringIO()):
            blocked = app.handler(event("/login", {"email": "person@example.com", "password": "wrong"}, "198.51.100.1"), None)
        self.assertEqual(429, blocked["statusCode"])
        self.assertEqual("900", blocked["headers"]["Retry-After"])
        self.assertNotIn("person@example.com", str(rate_table.items))
        self.assertEqual(10, users_table.get_item.call_count)

    def test_conditional_counter_allows_exactly_limit_under_concurrency(self):
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(
                lambda _: app.consume_auth_budget("login_account", "person@example.com", 10, 900)[0],
                range(40),
            ))
        self.assertEqual(10, results.count("allowed"))
        self.assertEqual(30, results.count("limited"))
        self.assertEqual([10], [item["request_count"] for item in rate_table.items.values()])

    def test_forgot_and_resend_share_account_email_budget_without_enumeration(self):
        users_table.get_item.return_value = {"Item": {"email_verified": True}}
        with patch.object(app, "send_password_reset_email") as send_email:
            for _ in range(3):
                result = app.handler(event("/forgot-password", {"email": "person@example.com"}), None)
                self.assertEqual(200, result["statusCode"])
            with redirect_stdout(io.StringIO()):
                blocked = app.handler(event("/resend-verification", {"email": "person@example.com"}), None)
        self.assertEqual(200, blocked["statusCode"])
        self.assertIn("if that unverified account exists", blocked["body"])
        self.assertEqual(3, send_email.call_count)
        self.assertEqual(3, users_table.get_item.call_count)

    def test_email_source_budget_is_shared_across_email_routes(self):
        request = event("/signup", {"email": "person@example.com", "password": "password123"})
        for index in range(10):
            route = ("signup", "forgot-password", "resend-verification")[index % 3]
            self.assertIsNone(app.enforce_auth_budget(request, route, "source"))
        with redirect_stdout(io.StringIO()):
            blocked = app.enforce_auth_budget(request, "forgot-password", "source")
        self.assertEqual(429, blocked["statusCode"])
        self.assertEqual("3600", blocked["headers"]["Retry-After"])

    def test_missing_source_and_counter_errors_fail_closed(self):
        missing = event("/login", {"email": "person@example.com", "password": "password123"})
        del missing["requestContext"]["http"]["sourceIp"]
        missing["headers"] = {"X-Forwarded-For": "203.0.113.99"}
        with redirect_stdout(io.StringIO()):
            result = app.handler(missing, None)
        self.assertEqual(503, result["statusCode"])
        self.assertEqual({}, rate_table.items)

        rate_table.fail = True
        with redirect_stdout(io.StringIO()):
            result = app.handler(event("/login", {"email": "person@example.com", "password": "password123"}), None)
        self.assertEqual(503, result["statusCode"])
        users_table.get_item.assert_not_called()

    def test_reset_token_account_budget_runs_after_signature_validation(self):
        token = app.issue_password_reset_token("email#person@example.com", "person@example.com")
        request = event("/reset-password", {"token": token, "password": "newpassword"})
        with patch.object(app, "hash_password", return_value="password-hash"):
            for index in range(10):
                request["requestContext"]["http"]["sourceIp"] = f"192.0.2.{index + 1}"
                self.assertEqual(200, app.handler(request, None)["statusCode"])
            request["requestContext"]["http"]["sourceIp"] = "198.51.100.1"
            with redirect_stdout(io.StringIO()):
                blocked = app.handler(request, None)
        self.assertEqual(429, blocked["statusCode"])
        self.assertEqual(10, users_table.update_item.call_count)

    def test_transport_error_fails_closed(self):
        with patch.object(rate_table, "update_item", side_effect=FakeBotoCoreError()):
            with redirect_stdout(io.StringIO()) as output:
                result = app.handler(event("/login", {"email": "person@example.com", "password": "password123"}), None)
        self.assertEqual(503, result["statusCode"])
        self.assertEqual("rate_limit_error", json.loads(output.getvalue())["event"])
        users_table.get_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
