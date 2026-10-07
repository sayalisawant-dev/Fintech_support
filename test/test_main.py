"""
Unit tests for the Banking Support AgentCore Demo.
Covers: Lambda handlers (customer, order, refund), JWT decoding, MCP client, model loading.
No live AWS connection required — all external dependencies are mocked.
"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "mcp" / "lambda"))


# ===========================================================================
# CUSTOMER LAMBDA TESTS
# ===========================================================================

from customer_handler import get_customer, list_customers, CUSTOMERS


class TestGetCustomer:
    def test_returns_customer_for_valid_id(self):
        result = get_customer({"customer_id": "CUST-001"})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["name"] == "John Doe"
        assert body["email"] == "john@example.com"

    def test_returns_customer_for_second_id(self):
        result = get_customer({"customer_id": "CUST-002"})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["name"] == "Jane Smith"
        assert body["email"] == "jane@example.com"

    def test_returns_404_for_unknown_id(self):
        result = get_customer({"customer_id": "CUST-999"})
        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "CUSTOMER_NOT_FOUND"

    def test_returns_400_when_no_id(self):
        result = get_customer({})
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "MISSING_PARAMETER"

    def test_response_has_member_since(self):
        result = get_customer({"customer_id": "CUST-001"})
        body = json.loads(result["body"])
        assert "member_since" in body


class TestListCustomers:
    def test_returns_all_customers(self):
        result = list_customers({})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["count"] == len(CUSTOMERS)

    def test_filters_by_name(self):
        result = list_customers({"name": "john"})
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["customers"][0]["name"] == "John Doe"

    def test_filter_is_case_insensitive(self):
        result = list_customers({"name": "JANE"})
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["customers"][0]["email"] == "jane@example.com"

    def test_no_match_returns_empty(self):
        result = list_customers({"name": "nonexistent"})
        body = json.loads(result["body"])
        assert body["count"] == 0
        assert body["customers"] == []

    def test_response_has_count_key(self):
        result = list_customers({})
        body = json.loads(result["body"])
        assert "count" in body
        assert "customers" in body


# ===========================================================================
# ORDER LAMBDA TESTS
# ===========================================================================

from order_handler import get_order, list_orders, process_refund, ORDERS


class TestGetOrder:
    def test_returns_order_for_valid_id(self):
        result = get_order({"order_id": "ORD-12420"})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["order_id"] == "ORD-12420"
        assert body["total"] == 29.99

    def test_returns_404_for_unknown_order(self):
        result = get_order({"order_id": "ORD-00000"})
        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "ORDER_NOT_FOUND"

    def test_returns_400_when_no_id(self):
        result = get_order({})
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "MISSING_PARAMETER"

    def test_order_has_items(self):
        result = get_order({"order_id": "ORD-12345"})
        body = json.loads(result["body"])
        assert len(body["items"]) > 0
        assert "name" in body["items"][0]
        assert "price" in body["items"][0]


class TestListOrders:
    def test_returns_orders_for_cust001(self):
        result = list_orders({"customer_id": "CUST-001"})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert len(body["orders"]) > 0
        for order in body["orders"]:
            assert order["order_id"] in ORDERS
            assert ORDERS[order["order_id"]]["customer_id"] == "CUST-001"

    def test_returns_orders_for_cust002(self):
        result = list_orders({"customer_id": "CUST-002"})
        body = json.loads(result["body"])
        assert len(body["orders"]) > 0

    def test_returns_400_when_no_customer_id(self):
        result = list_orders({})
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "MISSING_PARAMETER"

    def test_returns_404_for_unknown_customer(self):
        result = list_orders({"customer_id": "CUST-999"})
        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "CUSTOMER_NOT_FOUND"

    def test_orders_sorted_by_date_descending(self):
        result = list_orders({"customer_id": "CUST-001"})
        body = json.loads(result["body"])
        dates = [o["order_date"] for o in body["orders"]]
        assert dates == sorted(dates, reverse=True)

    def test_limit_is_respected(self):
        result = list_orders({"customer_id": "CUST-001", "limit": 2})
        body = json.loads(result["body"])
        assert len(body["orders"]) <= 2


class TestProcessRefund:
    def test_successful_small_refund(self):
        result = process_refund({
            "order_id": "ORD-12420",
            "amount": 29.99,
            "reason": "Phone case was damaged"
        })
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["success"] is True
        assert body["amount"] == 29.99
        assert body["status"] == "processed"
        assert body["refund_id"].startswith("REF-")

    def test_successful_partial_refund(self):
        result = process_refund({
            "order_id": "ORD-12430",
            "amount": 50.00,
            "reason": "Partial damage"
        })
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["success"] is True

    def test_refund_exceeds_order_total(self):
        result = process_refund({
            "order_id": "ORD-12420",  # total = $29.99
            "amount": 100.00,
            "reason": "Overage test"
        })
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "AMOUNT_EXCEEDS_ORDER"

    def test_negative_refund_amount(self):
        result = process_refund({
            "order_id": "ORD-12420",
            "amount": -10.00,
            "reason": "Negative test"
        })
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "INVALID_AMOUNT"

    def test_missing_order_id(self):
        result = process_refund({"amount": 10.00, "reason": "test"})
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "MISSING_PARAMETER"

    def test_missing_amount(self):
        result = process_refund({"order_id": "ORD-12420", "reason": "test"})
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "MISSING_PARAMETER"

    def test_missing_reason(self):
        result = process_refund({"order_id": "ORD-12420", "amount": 10.00})
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error_code"] == "MISSING_PARAMETER"

    def test_refund_for_unknown_order(self):
        result = process_refund({
            "order_id": "ORD-00000",
            "amount": 10.00,
            "reason": "test"
        })
        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error_code"] == "ORDER_NOT_FOUND"

    def test_refund_message_contains_amount(self):
        result = process_refund({
            "order_id": "ORD-12420",
            "amount": 15.00,
            "reason": "Wrong item"
        })
        body = json.loads(result["body"])
        assert "15.00" in body["message"]
        assert "3-5 business days" in body["message"]


# ===========================================================================
# JWT DECODING TESTS (src/main.py _decode_jwt)
# Extracted and tested directly to avoid the strands_tools/termios import
# issue on Windows (termios is Linux-only).
# ===========================================================================

import base64
import jwt as pyjwt


def _decode_jwt(token: str):
    """Mirror of main._decode_jwt — extracted for Windows-safe testing."""
    try:
        return pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.exceptions.DecodeError:
        return {}


def _get_bearer_token(context):
    """Mirror of main._get_bearer_token — extracted for Windows-safe testing."""
    auth = (getattr(context, "request_headers", None) or {}).get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


class TestDecodeJwt:
    def _make_jwt(self, payload: dict) -> str:
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        return f"{header}.{body}."

    def test_decodes_email_claim(self):
        token = self._make_jwt({"email": "john@example.com", "sub": "user-123"})
        claims = _decode_jwt(token)
        assert claims["email"] == "john@example.com"

    def test_decodes_groups_claim(self):
        token = self._make_jwt({"cognito:groups": ["standard"]})
        claims = _decode_jwt(token)
        assert claims["cognito:groups"] == ["standard"]

    def test_returns_empty_dict_for_invalid_token(self):
        assert _decode_jwt("not.a.valid.jwt") == {}

    def test_returns_empty_dict_for_empty_string(self):
        assert _decode_jwt("") == {}


# ===========================================================================
# BEARER TOKEN EXTRACTION TESTS
# ===========================================================================

class TestGetBearerToken:
    def test_extracts_token_from_authorization_header(self):
        context = MagicMock()
        context.request_headers = {"Authorization": "Bearer mytoken123"}
        assert _get_bearer_token(context) == "mytoken123"

    def test_returns_none_when_no_authorization_header(self):
        context = MagicMock()
        context.request_headers = {}
        assert _get_bearer_token(context) is None

    def test_returns_none_when_request_headers_is_none(self):
        context = MagicMock()
        context.request_headers = None
        assert _get_bearer_token(context) is None

    def test_returns_none_for_non_bearer_scheme(self):
        context = MagicMock()
        context.request_headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        assert _get_bearer_token(context) is None


# ===========================================================================
# MCP CLIENT TESTS (src/mcp_client/client.py)
# ===========================================================================

class TestMcpClient:
    def test_local_dev_mode_returns_null_client(self):
        os.environ["LOCAL_DEV"] = "1"
        try:
            from mcp_client.client import get_streamable_http_mcp_client
            client = get_streamable_http_mcp_client()
            with client as c:
                tools = c.list_tools_sync()
            assert tools == []
        finally:
            del os.environ["LOCAL_DEV"]

    def test_raises_when_no_gateway_url(self):
        os.environ.pop("GATEWAY_URL", None)
        os.environ.pop("LOCAL_DEV", None)
        from mcp_client.client import get_streamable_http_mcp_client
        with pytest.raises(RuntimeError, match="GATEWAY_URL"):
            get_streamable_http_mcp_client(user_token="sometoken")

    def test_raises_when_no_user_token(self):
        os.environ["GATEWAY_URL"] = "https://example.com/mcp"
        try:
            from mcp_client.client import get_streamable_http_mcp_client
            with pytest.raises(RuntimeError, match="User token"):
                get_streamable_http_mcp_client(user_token=None)
        finally:
            del os.environ["GATEWAY_URL"]


# ===========================================================================
# MODEL LOADING TESTS (src/model/load.py)
# ===========================================================================

class TestModelLoad:
    def test_load_model_uses_deepseek(self):
        with patch("model.load.BedrockModel") as mock_model_class:
            mock_model_class.return_value = MagicMock()
            from model.load import load_model, MODEL_ID
            assert MODEL_ID == "deepseek.deepseek-v3-2"
            load_model()
            mock_model_class.assert_called_once_with(model_id="deepseek.deepseek-v3-2")

    def test_load_model_returns_bedrock_model_instance(self):
        with patch("model.load.BedrockModel") as mock_model_class:
            fake_model = MagicMock()
            mock_model_class.return_value = fake_model
            from model.load import load_model
            result = load_model()
            assert result is fake_model


# ===========================================================================
# LAMBDA HANDLER ROUTING TESTS
# ===========================================================================

class TestCustomerLambdaRouting:
    def _make_context(self, tool_name):
        ctx = MagicMock()
        ctx.client_context.custom = {"bedrockAgentCoreToolName": f"CustomerTarget___{tool_name}"}
        return ctx

    def test_routes_get_customer(self):
        from customer_handler import lambda_handler
        event = {"customer_id": "CUST-001"}
        result = lambda_handler(event, self._make_context("get_customer"))
        assert result["statusCode"] == 200

    def test_routes_list_customers(self):
        from customer_handler import lambda_handler
        result = lambda_handler({}, self._make_context("list_customers"))
        assert result["statusCode"] == 200

    def test_returns_400_for_unknown_tool(self):
        from customer_handler import lambda_handler
        result = lambda_handler({}, self._make_context("delete_everything"))
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "Unknown tool" in body["error"]

    def test_returns_400_when_tool_name_missing(self):
        from customer_handler import lambda_handler
        ctx = MagicMock()
        ctx.client_context.custom = {"bedrockAgentCoreToolName": "no_separator_here"}
        result = lambda_handler({}, ctx)
        assert result["statusCode"] == 400


class TestOrderLambdaRouting:
    def _make_context(self, tool_name):
        ctx = MagicMock()
        ctx.client_context.custom = {"bedrockAgentCoreToolName": f"OrderTarget___{tool_name}"}
        return ctx

    def test_routes_get_order(self):
        from order_handler import lambda_handler
        result = lambda_handler({"order_id": "ORD-12345"}, self._make_context("get_order"))
        assert result["statusCode"] == 200

    def test_routes_list_orders(self):
        from order_handler import lambda_handler
        result = lambda_handler({"customer_id": "CUST-001"}, self._make_context("list_orders"))
        assert result["statusCode"] == 200

    def test_routes_process_refund(self):
        from order_handler import lambda_handler
        event = {"order_id": "ORD-12400", "amount": 10.00, "reason": "test"}
        result = lambda_handler(event, self._make_context("process_refund"))
        assert result["statusCode"] == 200

    def test_returns_400_for_unknown_tool(self):
        from order_handler import lambda_handler
        result = lambda_handler({}, self._make_context("hack_system"))
        assert result["statusCode"] == 400
