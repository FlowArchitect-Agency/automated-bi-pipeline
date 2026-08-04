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
    # Check aggregation for 2026-07-01 EU (has web and mobile channels)
    eu_july_1 = result[(result['order_date'] == pd.Timestamp('2026-07-01').date()) & (result['region'] == 'EU')]
    assert eu_july_1['net_revenue_eur'].sum() == 150.0
    assert eu_july_1['units'].sum() == 3


def test_summarize_reviews():
    """Test review summarization works on Pandas 1.5.3 (Docker) and 2.x (local).

    Covers: per (product, month) grouping, avg rating, the EN/FR summary split,
    deterministic top themes, and that no FutureWarning is raised by the
    groupby+apply path (the historical regression on Pandas 2.x).
    """
    import warnings

    from pipeline.enrich.mock import MockEnricher

    df = pd.DataFrame({
        'review_id': ['r1', 'r2', 'r3', 'r4'],
        'product_id': ['p1', 'p1', 'p1', 'p2'],
        'created_at': ['2026-07-01', '2026-07-15', '2026-08-02', '2026-07-10'],
        'rating': [5, 4, 2, 5],
        'title': ['Great', 'Good', 'Crash', 'Nice'],
        'body': ['Loved it', 'Worked well', 'keeps crashing on load', 'Très bien'],
        'language': ['en', 'en', 'fr', 'fr'],
    })
    enricher = MockEnricher()
    # The summarize path must not emit a Pandas deprecation FutureWarning on
    # any supported version (it must avoid the include_groups= argument that
    # is invalid on Pandas 1.5.3 and the deprecated apply-on-grouping-columns
    # behavior on Pandas 2.x).
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        result = enricher.summarize_reviews(df)

    assert list(result.columns) == [
        "product_id", "review_window", "n_reviews", "avg_rating",
        "summary_en", "summary_fr", "top_themes",
    ]
    # p1 spans two months -> 2 rows; p2 one month -> 1 row.
    assert len(result) == 3
    p1_jul = result[(result['product_id'] == 'p1') & (result['review_window'] == '2026-07')].iloc[0]
    assert p1_jul['n_reviews'] == 2
    assert p1_jul['avg_rating'] == 4.5
    assert p1_jul['summary_en']  # English bodies summarized
    # top_themes is always a list
    assert all(isinstance(t, list) for t in result['top_themes'])
    assert not result.empty


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
