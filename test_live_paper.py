import unittest
from unittest.mock import patch, MagicMock
import sqlite3
from live_paper import simulate_order, get_realtime_price, save_trade, get_open_position

class TestLivePaper(unittest.TestCase):
    def setUp(self):
        # Mock Kraken API and database connections
        self.pair = "XXBTZUSD"
        self.volume = 0.0001
        self.price = 85000.0

    @patch('live_paper.query_private_throttled')
    def test_simulate_order_success(self, mock_query):
        # Simulate successful order validation
        mock_query.return_value = {'result': {'descr': f'buy {self.volume} {self.pair} @ limit'}, 'error': []}
        result = simulate_order('buy', self.pair, self.volume, price=self.price, validate=True)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'filled')
        self.assertEqual(result['filled_volume'], self.volume)
        self.assertEqual(result['remaining_volume'], 0.0)

    @patch('live_paper.query_private_throttled')
    def test_simulate_order_api_error(self, mock_query):
        # Simulate API error
        mock_query.return_value = {'error': ['EGeneral:Invalid arguments']}
        result = simulate_order('buy', self.pair, self.volume, price=self.price, validate=True)
        self.assertIsNone(result)

    @patch('live_paper.query_public_throttled')
    def test_get_realtime_price_success(self, mock_query):
        # Simulate successful price fetch
        mock_query.return_value = {'result': {self.pair: {'c': ['85000.0']}}, 'error': []}
        price = get_realtime_price(self.pair)
        self.assertEqual(price, 85000.0)

    @patch('live_paper.query_public_throttled')
    def test_get_realtime_price_api_error(self, mock_query):
        # Simulate API error
        mock_query.return_value = {'error': ['EGeneral:Invalid pair']}
        price = get_realtime_price(self.pair)
        self.assertIsNone(price)

    @patch('live_paper.sqlite3.connect')
    def test_save_trade_success(self, mock_connect):
        # Simulate successful database save
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Ensure context manager returns our mock_conn
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        save_trade('buy', self.price, self.volume, 0, 10000.0, fee=0.0026, source='auto')
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()

    @patch('live_paper.sqlite3.connect')
    def test_get_open_position_no_position(self, mock_connect):
        # Simulate no open position
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [None]
        position = get_open_position()
        self.assertIsNone(position)

    @patch('live_paper.sqlite3.connect')
    def test_get_open_position_open_buy(self, mock_connect):
        # Simulate open buy position
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (1, '2023-10-01T00:00:00', self.price, self.volume, 10000.0, 'auto'),
            None  # No sell after buy
        ]
        position = get_open_position()
        self.assertIsNotNone(position)
        self.assertEqual(position['entry_price'], self.price)
        self.assertEqual(position['volume'], self.volume)
        self.assertEqual(position['source'], 'auto')

    @patch('live_paper.get_min_volume', return_value=0.001)
    def test_simulate_order_below_min_volume(self, mock_min_vol):
        # Simulate order volume below minimum allowed
        result = simulate_order('buy', self.pair, self.volume, price=self.price, validate=True)
        self.assertIsNone(result)

    def test_simulate_order_without_api_keys(self):
        # Simulate no Kraken API keys configured
        import live_paper
        live_paper.k.key = ''
        live_paper.k.secret = ''
        result = simulate_order('buy', self.pair, self.volume, price=self.price, validate=True)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'filled')
        self.assertEqual(result['filled_volume'], self.volume)
        self.assertIn('fee', result)

    @patch('live_paper.sqlite3.connect')
    def test_get_open_position_closed_position(self, mock_connect):
        # Simulate a buy followed by a sell -> no open position
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (1, '2023-10-01T00:00:00', self.price, self.volume, 10000.0, 'auto'),
            (2,)  # Sell exists after buy
        ]
        position = get_open_position()
        self.assertIsNone(position)

    @patch('live_paper.sqlite3.connect')
    def test_get_open_position_malformed_data(self, mock_connect):
        # Simulate fetchone returning malformed tuple (too few fields)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (1, 'time', self.price)  # malformed, only 3 elements
        ]
        # Expect unpacking mismatch to raise ValueError
        with self.assertRaises(ValueError):
            get_open_position()

if __name__ == '__main__':
    unittest.main()