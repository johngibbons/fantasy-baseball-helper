import pytest
from backend.analysis.trades import TradePlayerInfo


class TestTradePlayerInfoWeights:
    def test_has_weight_fields(self):
        p = TradePlayerInfo(
            mlb_id=1, name="Test", position="SS",
            total_zscore=3.0, weight=1.0, incoming_weight=0.25,
        )
        assert p.weight == 1.0
        assert p.incoming_weight == 0.25

    def test_weight_fields_default_to_1(self):
        p = TradePlayerInfo(
            mlb_id=1, name="Test", position="SS", total_zscore=3.0,
        )
        assert p.weight == 1.0
        assert p.incoming_weight == 1.0
