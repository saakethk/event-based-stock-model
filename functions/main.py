
# DEPENDENCIES
import model_helper
import model_types
import os
from firebase_functions import https_fn, scheduler_fn, tasks_fn
from firebase_admin import firestore
from firebase_functions.options import RetryConfig, RateLimits
import time

# GET FUTURE EARNINGS DATES
def get_earnings() -> list:

    # Sorts response
    def sort_earnings(earning: model_types.EarningsObject):
        return earning.buy_time, earning.rev

    # Gets response
    success, response = model_helper.get_data_finnhub(
        url="api/v1/calendar/earnings",
        params={
            "token": os.getenv("STOCKS_API_KEY"),
            "from": model_helper.get_timestamp(with_time=False),
            "to": model_helper.get_timestamp(with_time=False, delta=-72)
        }
    )

    # Error logging
    if not success:
        model_helper.log(f"EARNING API CALL FAILED: {response}")
    
    # Process response
    res_obj = response["earningsCalendar"]
    earnings = []
    for earning_obj in res_obj:
        earnings_obj_p = model_types.EarningsObject(
            symbol=earning_obj["symbol"],
            date=earning_obj["date"],
            time=earning_obj["hour"],
            rev=earning_obj["revenueEstimate"],
            eps_est=earning_obj["epsEstimate"]
        )
        if earnings_obj_p.elgible:
            earnings.append(
                earnings_obj_p
            )
    earnings.sort(key=sort_earnings)
    return earnings
    
# GET FUTURE IPO DATES
def get_future_ipos() -> list:

    # Sorts response
    def sort_ipos(ipo: model_types.IpoObject):
        return ipo.date, ipo.expected_price

    # Gets response
    success, response = model_helper.get_data_finnhub(
        url="/api/v1/calendar/ipo",
        params={
            "token": os.getenv("STOCKS_API_KEY"),
            "from": model_helper.get_timestamp(with_time=False),
            "to": model_helper.get_timestamp(with_time=False, delta=-72)
        }
    )

    # Error logging
    if not success:
        model_helper.log(f"IPO API CALL FAILED: {response}")
    
    # Process response
    res_obj = response["ipoCalendar"]
    ipos = []
    for ipo_obj in res_obj:
        ipo_obj_p = model_types.IpoObject(
            symbol=ipo_obj["symbol"],
            name=ipo_obj["name"],
            date=ipo_obj["date"],
            expected_price=ipo_obj["price"]
        )
        ipos.append(
            ipo_obj_p
        )
    ipos.sort(key=sort_ipos)
    return ipos

# ANALYZE AND CHOOSE WHICH ORDERS TO PLACE
def formulate_orders():

    # Sorts response
    def sort_orders(order: model_types.Order):
        return order.execute_time

    # Gets data
    active_orders = model_helper.get_database_collection(
        collection="actions",
        field="status",
        value="executed",
        key="symbol"
    )
    ipos = get_future_ipos()
    ipos = ipos[:5] if len(ipos) > 5 else ipos
    earnings = get_earnings()
    earnings = earnings[:5] if len(earnings) > 5 else earnings

    # Creates orders
    orders = []
    for ipo in ipos:
        if ipo.symbol not in active_orders:
            order = model_types.Order(
                symbol=ipo.symbol,
                object=ipo
            )
            if order.elgible:
                orders.append(order)
    for earning in earnings:
        if earning.symbol not in active_orders:
            order = model_types.Order(
                symbol=earning.symbol,
                object=earning
            )
            if order.elgible:
                orders.append(order)

    # Process orders
    orders.sort(key=sort_orders)
    return orders

# CREATE ALPACA ORDER WHEN TASK QUEUED
@tasks_fn.on_task_dispatched(retry_config=RetryConfig(max_attempts=5, min_backoff_seconds=60),
                             rate_limits=RateLimits(max_concurrent_dispatches=10))
def createstockorder(req: tasks_fn.CallableRequest):

    # Gets request data
    id = req.data["id"]
    symbol = req.data["symbol"]
    amount = req.data["amount"]
    upper = req.data["upper"]
    lower = req.data["lower"]
    lower_safety = req.data["lower_safety"]
    action_object = model_helper.get_database(
        collection="actions",
        document=id
    )

    # Create Alpaca order
    success, stock_order_res = model_helper.post_data_alpaca(
        url="v2/orders", 
        payload={
            "side": "buy",
            "symbol": symbol,
            "type": "market",
            "notional": amount,
            "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {
                "limit_price": upper
            },
            "stop_loss": {
                "stop_price": lower,
                "limit_price": lower_safety
            }
        }
    )

    # Error Logging
    if not success:
        model_helper.log(f"STOCK ORDER FAILED: {stock_order_res}")

    # Updates firestore document
    assoc_action = {
        "type": "order",
        "action": "bracket_order",
        "alpaca_order_id": stock_order_res["id"],
        "timestamp": firestore.SERVER_TIMESTAMP
    }
    action_object["associated_action"] = assoc_action
    action_object["status"] = "executed"
    model_helper.set_database(
        collection="actions",
        document=id
    )

# CREATE TASK QUEUE ORDER AND FIRESTORE ENTRY
@scheduler_fn.on_schedule(schedule="0 0 * * *")
def schedule_orders(req: https_fn.Request) -> https_fn.Response:

    # Creates orders after retrieving data
    orders = formulate_orders()

    # Get additional info about orders and schedules them
    for order in orders:

        # Analyzes stock via AI
        order.analyzeAI()
        order.updateDatabase()
        order.scheduleTask()
        time.sleep(1)
        order.updateDatabase()
        model_helper.log(str(order))
