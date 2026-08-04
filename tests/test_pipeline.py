import os
from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.config import get_settings
from pipeline.extract import extract_all
from pipeline.transform import daily_revenue_by_segment


def test_extract_all():
    """Test that all 5 seed files can be extracted."""
    settings = get_settings()
    source = extract_all(settings)
    assert not source.orders.empty
    assert not source.support_tickets.empty
    assert not source.product_reviews.empty
    assert not source.web_analytics.empty
    assert not source.crm_leads.empty


def test_daily_revenue_transform():
    """Test the daily revenue transformation."""
    # Create mock orders dataframe with order_id
    df = pd.DataFrame({
        'order_id': ['o1', 'o2', 'o3'],
        'order_date': [pd.Timestamp('2026-07-01'), pd.Timestamp('2026-07-01'), pd.Timestamp('2026-07-02')],
        'region': ['EU', 'EU', 'US'],
        'channel': ['web', 'mobile', 'web'],
        'net_revenue_eur': [100.0, 50.0, 200.0],
        'units': [2, 1, 4]
    })
    result = daily_revenue_by_segment(df)
    # Should have 5 rows (3 segmented + 2 overall daily rollups)
    assert len(result) == 5
    # Check aggregation for 2026-07-01 EU
    eu_july_1 = result[(result['order_date'] == pd.Timestamp('2026-07-01')) & (result['region'] == 'EU')]
    assert eu_july_1['net_revenue_eur'].iloc[0] == 150.0
    assert eu_july_1['units'].iloc[0] == 3


def test_slack_webhook():
    """Test the Slack webhook correctly handles missing URL and real requests."""
    from pipeline.notify.slack_webhook import send_slack_notification
    # Missing webhook URL -> should gracefully skip and return False
    with patch("pipeline.notify.slack_webhook.get_settings") as mock_settings:
        mock_settings.return_value.slack_webhook_url.get_secret_value.return_value = None
        assert not send_slack_notification("Test message")

    # With webhook URL -> should call requests.post
    with patch("pipeline.notify.slack_webhook.get_settings") as mock_settings:
        mock_settings.return_value.slack_webhook_url.get_secret_value.return_value = "https://hooks.slack.com/services/test"
        with patch("requests.post") as mock_post:
            assert send_slack_notification("Test message")
            mock_post.assert_called_once()


def test_dag_validation():
    """Test that the Airflow DAG parses without errors."""
    pytest.importorskip("airflow")
    from airflow.models import DagBag
    dag_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), "airflow", "dags")
    dag_bag = DagBag(dag_folder=dag_folder, include_examples=False)
    assert not dag_bag.import_errors, f"DAG import errors: {dag_bag.import_errors}"
    assert "bi_pipeline" in dag_bag.dags
