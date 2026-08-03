import pytest
import pandas as pd
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
    # Create mock orders dataframe
    df = pd.DataFrame({
        'order_date': [pd.Timestamp('2026-07-01'), pd.Timestamp('2026-07-01'), pd.Timestamp('2026-07-02')],
        'region': ['EU', 'EU', 'US'],
        'channel': ['web', 'mobile', 'web'],
        'net_revenue_eur': [100.0, 50.0, 200.0],
        'units': [2, 1, 4]
    })
    
    result = daily_revenue_by_segment(df)
    
    # Should have 2 rows (2026-07-01/EU and 2026-07-02/US)
    assert len(result) == 2
    
    # Check aggregation for 2026-07-01 EU
    eu_july_1 = result[(result['order_date'] == pd.Timestamp('2026-07-01')) & (result['region'] == 'EU')]
    assert eu_july_1['net_revenue_eur'].iloc[0] == 150.0
    assert eu_july_1['units'].iloc[0] == 3
