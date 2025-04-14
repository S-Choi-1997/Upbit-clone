from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import pyupbit
import pandas as pd
from datetime import datetime, timedelta
import threading
import time
from models import db, User, Holding, TradeHistory, Order

app = Flask(__name__)

# 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trading.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'your-secret-key'  # 실제 배포 시 환경 변수로 관리
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# 초기화
db.init_app(app)
jwt = JWTManager(app)

# 지원 코인 목록
tickers = pyupbit.get_tickers(fiat="KRW")  # 원화 마켓 모든 코인

# 데이터베이스 생성
with app.app_context():
    db.create_all()

# 사용자 관리
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "Username already exists"}), 400
    
    hashed_password = generate_password_hash(password)
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({"status": "success", "message": "User registered"}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    
    access_token = create_access_token(identity=user.id)
    return jsonify({"status": "success", "access_token": access_token}), 200

# 코인 데이터
@app.route('/api/tickers', methods=['GET'])
def get_tickers():
    prices = {ticker: pyupbit.get_current_price(ticker) for ticker in tickers}
    return jsonify(prices)

@app.route('/api/ohlcv/<ticker>', methods=['GET'])
def get_ohlcv(ticker):
    interval = request.args.get('interval', 'minute1')
    count = int(request.args.get('count', 100))
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
    return jsonify(df.to_dict('records'))

# 자산 조회
@app.route('/api/account', methods=['GET'])
@jwt_required()
def get_account():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    holdings = Holding.query.filter_by(user_id=user_id).all()
    holdings_dict = {h.ticker: {"amount": h.amount, "avg_price": h.avg_price} for h in holdings}
    
    # 총 자산 계산
    total_value = user.balance
    for ticker, info in holdings_dict.items():
        current_price = pyupbit.get_current_price(ticker)
        total_value += info["amount"] * current_price
    
    return jsonify({
        "balance": user.balance,
        "holdings": holdings_dict,
        "total_value": total_value
    })

# 시장가 매수
@app.route('/api/buy', methods=['POST'])
@jwt_required()
def buy():
    user_id = get_jwt_identity()
    data = request.json
    ticker = data['ticker']
    amount = float(data['amount'])  # 현금 금액
    
    user = User.query.get(user_id)
    if amount > user.balance:
        return jsonify({"status": "error", "message": "Insufficient balance"}), 400
    
    current_price = pyupbit.get_current_price(ticker)
    coin_amount = amount / current_price
    
    # 계좌 업데이트
    user.balance -= amount
    holding = Holding.query.filter_by(user_id=user_id, ticker=ticker).first()
    if holding:
        prev_amount = holding.amount
        prev_avg_price = holding.avg_price
        new_amount = prev_amount + coin_amount
        new_avg_price = ((prev_amount * prev_avg_price) + amount) / new_amount
        holding.amount = new_amount
        holding.avg_price = new_avg_price
    else:
        new_holding = Holding(user_id=user_id, ticker=ticker, amount=coin_amount, avg_price=current_price)
        db.session.add(new_holding)
    
    # 거래 기록
    trade = TradeHistory(user_id=user_id, ticker=ticker, type='buy', amount=coin_amount, price=current_price)
    db.session.add(trade)
    db.session.commit()
    
    return jsonify({"status": "success", "message": "Buy order executed"})

# 시장가 매도
@app.route('/api/sell', methods=['POST'])
@jwt_required()
def sell():
    user_id = get_jwt_identity()
    data = request.json
    ticker = data['ticker']
    coin_amount = float(data['coin_amount'])
    
    holding = Holding.query.filter_by(user_id=user_id, ticker=ticker).first()
    if not holding or coin_amount > holding.amount:
        return jsonify({"status": "error", "message": "Insufficient holdings"}), 400
    
    current_price = pyupbit.get_current_price(ticker)
    amount = coin_amount * current_price
    
    # 계좌 업데이트
    user = User.query.get(user_id)
    user.balance += amount
    holding.amount -= coin_amount
    if holding.amount <= 0:
        db.session.delete(holding)
    
    # 거래 기록
    trade = TradeHistory(user_id=user_id, ticker=ticker, type='sell', amount=coin_amount, price=current_price)
    db.session.add(trade)
    db.session.commit()
    
    return jsonify({"status": "success", "message": "Sell order executed"})

# 예약 주문 생성
@app.route('/api/order', methods=['POST'])
@jwt_required()
def create_order():
    user_id = get_jwt_identity()
    data = request.json
    ticker = data['ticker']
    order_type = data['type']  # buy/sell
    amount = float(data['amount'])  # 코인 수량(buy는 현금 금액)
    price = float(data['price'])  # 지정 가격
    
    user = User.query.get(user_id)
    if order_type == 'buy' and amount > user.balance:
        return jsonify({"status": "error", "message": "Insufficient balance"}), 400
    if order_type == 'sell':
        holding = Holding.query.filter_by(user_id=user_id, ticker=ticker).first()
        if not holding or amount > holding.amount:
            return jsonify({"status": "error", "message": "Insufficient holdings"}), 400
    
    order = Order(user_id=user_id, ticker=ticker, type=order_type, amount=amount, price=price)
    db.session.add(order)
    db.session.commit()
    
    return jsonify({"status": "success", "message": "Order created", "order_id": order.id})

# 예약 주문 조회
@app.route('/api/orders', methods=['GET'])
@jwt_required()
def get_orders():
    user_id = get_jwt_identity()
    orders = Order.query.filter_by(user_id=user_id).all()
    return jsonify([{
        "id": o.id,
        "ticker": o.ticker,
        "type": o.type,
        "amount": o.amount,
        "price": o.price,
        "status": o.status,
        "created_at": o.created_at.isoformat()
    } for o in orders])

# 예약 주문 취소
@app.route('/api/order/<int:order_id>', methods=['DELETE'])
@jwt_required()
def cancel_order(order_id):
    user_id = get_jwt_identity()
    order = Order.query.filter_by(id=order_id, user_id=user_id).first()
    if not order or order.status != 'pending':
        return jsonify({"status": "error", "message": "Invalid order"}), 400
    
    order.status = 'canceled'
    db.session.commit()
    return jsonify({"status": "success", "message": "Order canceled"})

# 거래 내역
@app.route('/api/history', methods=['GET'])
@jwt_required()
def get_history():
    user_id = get_jwt_identity()
    history = TradeHistory.query.filter_by(user_id=user_id).all()
    return jsonify([{
        "ticker": h.ticker,
        "type": h.type,
        "amount": h.amount,
        "price": h.price,
        "timestamp": h.timestamp.isoformat()
    } for h in history])

# 예약 주문 처리 (백그라운드)
def process_orders():
    while True:
        with app.app_context():
            orders = Order.query.filter_by(status='pending').all()
            for order in orders:
                current_price = pyupbit.get_current_price(order.ticker)
                user = User.query.get(order.user_id)
                
                if order.type == 'buy' and current_price <= order.price:
                    # 예약 매수 실행
                    coin_amount = order.amount / current_price
                    if order.amount <= user.balance:
                        user.balance -= order.amount
                        holding = Holding.query.filter_by(user_id=order.user_id, ticker=order.ticker).first()
                        if holding:
                            prev_amount = holding.amount
                            prev_avg_price = holding.avg_price
                            new_amount = prev_amount + coin_amount
                            new_avg_price = ((prev_amount * prev_avg_price) + order.amount) / new_amount
                            holding.amount = new_amount
                            holding.avg_price = new_avg_price
                        else:
                            holding = Holding(user_id=order.user_id, ticker=order.ticker, amount=coin_amount, avg_price=current_price)
                            db.session.add(holding)
                        trade = TradeHistory(user_id=order.user_id, ticker=order.ticker, type='buy', amount=coin_amount, price=current_price)
                        db.session.add(trade)
                        order.status = 'filled'
                
                elif order.type == 'sell' and current_price >= order.price:
                    # 예약 매도 실행
                    holding = Holding.query.filter_by(user_id=order.user_id, ticker=order.ticker).first()
                    if holding and order.amount <= holding.amount:
                        user.balance += order.amount * current_price
                        holding.amount -= order.amount
                        if holding.amount <= 0:
                            db.session.delete(holding)
                        trade = TradeHistory(user_id=order.user_id, ticker=order.ticker, type='sell', amount=order.amount, price=current_price)
                        db.session.add(trade)
                        order.status = 'filled'
                
                db.session.commit()
        
        time.sleep(10)  # 10초마다 체크

# 백그라운드 스레드 시작
threading.Thread(target=process_orders, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True)