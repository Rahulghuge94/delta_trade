import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import json
import asyncio

from delta_paper_trader.delta_ws import DeltaPublicStream
from delta_paper_trader.models import Quote


@pytest.fixture
def delta_stream():
    """Create a DeltaPublicStream instance for testing."""
    return DeltaPublicStream(
        symbols=["BTCUSD", "ETHUSD"],
        url="wss://public-socket.india.delta.exchange",
        channel="ob_l1",
        heartbeat_timeout=40.0,
    )


class TestDeltaPublicStreamInit:
    def test_initialization_default_values(self):
        """Test DeltaPublicStream initializes with default values."""
        stream = DeltaPublicStream(symbols=["BTCUSD"])
        assert stream.symbols == ["BTCUSD"]
        assert stream.url == "wss://public-socket.india.delta.exchange"
        assert stream.channel == "ob_l1"
        assert stream.heartbeat_timeout == 40.0

    def test_initialization_custom_values(self):
        """Test DeltaPublicStream initializes with custom values."""
        stream = DeltaPublicStream(
            symbols=["BTCUSD", "ETHUSD"],
            url="wss://custom.url",
            channel="custom_channel",
            heartbeat_timeout=60.0,
        )
        assert stream.symbols == ["BTCUSD", "ETHUSD"]
        assert stream.url == "wss://custom.url"
        assert stream.channel == "custom_channel"
        assert stream.heartbeat_timeout == 60.0

    def test_initialization_multiple_symbols(self):
        """Test DeltaPublicStream with multiple symbols."""
        symbols = ["BTCUSD", "ETHUSD", "SOLANASUSD"]
        stream = DeltaPublicStream(symbols=symbols)
        assert stream.symbols == symbols


class TestParseQuote:
    def test_parse_ob_l1_valid_message(self, delta_stream):
        """Test parsing valid ob_l1 message."""
        message = {
            "type": "ob_l1",
            "sy": "BTCUSD",
            "bp": "45000.50",
            "ap": "45001.00",
            "bs": "1.5",
            "as": "2.0",
            "ts": 1234567890000,
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is not None
        assert quote.symbol == "BTCUSD"
        assert quote.bid == Decimal("45000.50")
        assert quote.ask == Decimal("45001.00")
        assert quote.bid_size == Decimal("1.5")
        assert quote.ask_size == Decimal("2.0")
        assert quote.timestamp_us == 1234567890000

    def test_parse_ob_l1_missing_bid_size_ask_size(self, delta_stream):
        """Test parsing ob_l1 message with missing bid/ask sizes."""
        message = {
            "type": "ob_l1",
            "sy": "BTCUSD",
            "bp": "45000.50",
            "ap": "45001.00",
            "ts": 1234567890000,
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is not None
        assert quote.bid_size == Decimal("0")
        assert quote.ask_size == Decimal("0")

    def test_parse_ob_l1_with_lts_fallback(self, delta_stream):
        """Test parsing ob_l1 using lts (last timestamp) when ts missing."""
        message = {
            "type": "ob_l1",
            "sy": "BTCUSD",
            "bp": "45000.50",
            "ap": "45001.00",
            "lts": 9876543210000,
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is not None
        assert quote.timestamp_us == 9876543210000

    def test_parse_ob_l1_missing_required_fields(self, delta_stream):
        """Test parsing ob_l1 with missing required fields."""
        message = {
            "type": "ob_l1",
            "sy": "BTCUSD",
            "bp": "45000.50",
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is None

    def test_parse_ob_l1_invalid_decimal(self, delta_stream):
        """Test parsing ob_l1 with invalid decimal values."""
        message = {
            "type": "ob_l1",
            "sy": "BTCUSD",
            "bp": "invalid",
            "ap": "45001.00",
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is None

    def test_parse_ticker_valid_message(self, delta_stream):
        """Test parsing valid ticker message."""
        message = {
            "type": "ticker",
            "sy": "BTCUSD",
            "ts": 1234567890000,
            "d": [
                {
                    "s": "BTCUSD",
                    "q": ["45001.00", "2.0", "45000.50", "1.5"],
                }
            ],
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is not None
        assert quote.symbol == "BTCUSD"
        assert quote.ask == Decimal("45001.00")
        assert quote.ask_size == Decimal("2.0")
        assert quote.bid == Decimal("45000.50")
        assert quote.bid_size == Decimal("1.5")
        assert quote.timestamp_us == 1234567890000

    def test_parse_ticker_empty_rows(self, delta_stream):
        """Test parsing ticker message with empty rows."""
        message = {
            "type": "ticker",
            "sy": "BTCUSD",
            "d": [],
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is None

    def test_parse_ticker_missing_d_field(self, delta_stream):
        """Test parsing ticker message with missing 'd' field."""
        message = {
            "type": "ticker",
            "sy": "BTCUSD",
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is None

    def test_parse_ticker_insufficient_quote_values(self, delta_stream):
        """Test parsing ticker with insufficient quote values."""
        message = {
            "type": "ticker",
            "sy": "BTCUSD",
            "d": [
                {
                    "s": "BTCUSD",
                    "q": ["45001.00", "2.0"],
                }
            ],
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is None

    def test_parse_ticker_uses_message_sy_fallback(self, delta_stream):
        """Test parsing ticker uses message 'sy' when row 's' is missing."""
        message = {
            "type": "ticker",
            "sy": "BTCUSD",
            "d": [
                {
                    "q": ["45001.00", "2.0", "45000.50", "1.5"],
                }
            ],
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is not None
        assert quote.symbol == "BTCUSD"

    def test_parse_unknown_message_type(self, delta_stream):
        """Test parsing message with unknown type."""
        message = {
            "type": "unknown_type",
            "data": "some data",
        }
        quote = delta_stream._parse_quote(message)
        
        assert quote is None


class TestSubscribe:
    def test_subscribe_signature(self, delta_stream):
        """Test that _subscribe method exists and is callable."""
        assert hasattr(delta_stream, '_subscribe')
        assert callable(delta_stream._subscribe)


class TestReadQuotes:
    def test_read_quotes_exists(self, delta_stream):
        """Test that _read_quotes method exists and is callable."""
        assert hasattr(delta_stream, '_read_quotes')
        assert callable(delta_stream._read_quotes)
