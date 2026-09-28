import sys
sys.path.insert(0, '.')

from core.db_manager import db_session
from database.models import User, Subscriber, FinancialTransaction, Network, Router, SaasPackage
from database.central_models import GlobalSetting, NetworkClient
from modules.app_routes import (
    get_app_settings, get_network_client, calculate_app_commission,
    app_security_middleware
)
from flask import Flask

app = Flask(__name__)
app.config['SECRET_KEY'] = 'test'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sakr_connect.db'

print('=== SAKR CONNECT PAY - SYSTEM TEST ===')
print()

# 1. App Settings
print('1. APP SETTINGS')
settings = get_app_settings()
for k, v in settings.items():
    print('   {}: {}'.format(k, v))
print()

# 2. Commission Calculation
print('2. COMMISSION CALCULATION')
class MockClient:
    commission_mode = 'global'
    custom_commission_rate = 0

client = MockClient()
for amount in [10, 50, 100, 500, 1000]:
    comm = calculate_app_commission(amount, client)
    print('   Amount: {} EGP -> Commission: {} EGP ({:.1f}%)'.format(amount, comm, comm/amount*100))

# Custom
class MockClientCustom:
    commission_mode = 'custom'
    custom_commission_rate = 5.0
client_custom = MockClientCustom()
comm = calculate_app_commission(100, client_custom)
print('   Custom 5% on 100 EGP: {} EGP'.format(comm))

# Disabled
class MockClientDisabled:
    commission_mode = 'disabled'
client_disabled = MockClientDisabled()
comm = calculate_app_commission(100, client_disabled)
print('   Disabled on 100 EGP: {} EGP'.format(comm))
print()

# 3. Network Client
print('3. NETWORK CLIENT')
nc = get_network_client(1)
if nc:
    print('   NetworkClient 1: {} (type: {}, status: {})'.format(nc.client_name, nc.client_type, nc.status))
    print('   app_visible: {}, commission_mode: {}'.format(nc.app_visible, nc.commission_mode))
    print('   current_balance: {}, accumulated_commission: {}'.format(getattr(nc, 'current_balance', 'N/A'), nc.accumulated_commission))
else:
    print('   No NetworkClient with id=1')
print()

# 4. Database Columns
print('4. DATABASE SCHEMA CHECK')
from sqlalchemy import inspect, text
inspector = inspect(db_session.bind)
columns = [c['name'] for c in inspector.get_columns('network_clients')]
required = ['app_visible', 'commission_mode', 'custom_commission_rate', 'current_balance', 'accumulated_commission']
for col in required:
    status = 'OK' if col in columns else 'MISSING'
    print('   network_clients.{}: {}'.format(col, status))

# FinancialTransaction types
result = db_session.execute(text('SELECT DISTINCT transaction_type FROM financial_transactions')).fetchall()
types = [r[0] for r in result]
print('   FinancialTransaction types: {}'.format(types))
has_app_commission = 'app_commission' in types
print('   app_commission type exists: {}'.format(has_app_commission))
print()

# 5. API Endpoints (no auth - should return 401)
print('5. API ENDPOINTS (UNAUTHENTICATED)')
from modules.app_routes import app_bp
app.register_blueprint(app_bp)
with app.test_client() as c:
    resp = c.get('/api/app/network-info/1')
    ok = 'OK' if resp.status_code == 401 else 'FAIL'
    print('   /api/app/network-info/1 (no auth): {} ({})'.format(resp.status_code, ok))
    
    resp = c.post('/api/app/auth', json={'username': 'nonexistent', 'password': 'test'})
    ok = 'OK' if resp.status_code == 401 else 'FAIL'
    print('   /api/app/auth (invalid): {} ({})'.format(resp.status_code, ok))
    
    resp = c.post('/api/app/webhook', json={'sms_text': 'test', 'sender': 'vodafone'})
    ok = 'OK' if resp.status_code == 401 else 'FAIL'
    print('   /api/app/webhook (no auth): {} ({})'.format(resp.status_code, ok))
    
    # Test with token
    resp = c.get('/api/app/network-info/1', headers={'Authorization': 'Bearer test'})
    print('   /api/app/network-info/1 (with token): {}'.format(resp.status_code))

print()
print('=== TEST COMPLETE ===')