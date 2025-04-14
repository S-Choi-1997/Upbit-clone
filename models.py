from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)  # 해시된 비밀번호
    balance = db.Column(db.Float, default=1000000.0)  # 초기 자금 100만 원
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Holding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker = db.Column(db.String(20), nullable=False)  # 예: KRW-BTC
    amount = db.Column(db.Float, nullable=False)  # 코인 수량
    avg_price = db.Column(db.Float, nullable=False)  # 평균 매수가

class TradeHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # buy/sell
    amount = db.Column(db.Float, nullable=False)  # 코인 수량
    price = db.Column(db.Float, nullable=False)  # 거래 가격
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ticker = db.Column(db.String(20), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # buy/sell
    amount = db.Column(db.Float, nullable=False)  # 주문 수량
    price = db.Column(db.Float, nullable=False)  # 지정 가격
    status = db.Column(db.String(20), default='pending')  # pending/filled/canceled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)