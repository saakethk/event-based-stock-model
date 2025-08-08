
# DEPENDENCIES
import model_helper
import model_types
import os
from firebase_functions import https_fn, scheduler_fn
from firebase_admin import firestore
import time
from datetime import datetime

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
def formulate_orders() -> list:

    # Sorts response
    def sort_orders(order: model_types.Order):
        return order.execute_time, order.price

    # Gets data
    ids, active_orders = model_helper.get_database_collection(
        collection="actions",
        field="status",
        operator="==",
        value="scheduled",
        key="symbol"
    )
    ipos = get_future_ipos()
    limit = 50
    ipos = ipos[:limit] if len(ipos) > limit else ipos
    earnings = get_earnings()
    earnings = earnings[:limit] if len(earnings) > limit else earnings

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
@https_fn.on_request()
def createstockorder(req: https_fn.Request) -> https_fn.Response:

    # Gets request data
    data = req.get_json()
    api_key = data["data"]["key"]
    if api_key == os.getenv("NOUS_API_KEY"):
        id = data["data"]["id"]
        symbol = data["data"]["symbol"]
        amount = data["data"]["amount"]
        upper = float(data["data"]["upper"])
        lower = float(data["data"]["lower"])
        lower_safety = data["data"]["lower_safety"]
        action_object = model_helper.get_database(
            collection="actions",
            document=id
        )

        # Get current stock price
        success, stock_price = model_helper.get_data_alpaca(
            url=f"/v2/stocks/{symbol}/snapshot",
            market=True
        )
        if not success or "dailyBar" not in stock_price:
            model_helper.log(f"FAILED TO GET STOCK PRICE: {stock_price}")
            return https_fn.Response(f"FAILED TO GET STOCK PRICE: {stock_price}", status=400)
        else:
            curr_stock_price = float(stock_price["dailyBar"]["vw"])

            # Create Alpaca order
            success, stock_order_res = model_helper.post_data_alpaca(
                url="v2/orders", 
                payload={
                    "type": "market",
                    "time_in_force": "day",
                    "take_profit": { 
                        "limit_price": round(curr_stock_price * upper, 2) 
                    },
                    "stop_loss": {
                        "stop_price": round(curr_stock_price * lower, 2),
                        "limit_price": round(curr_stock_price * lower_safety, 2)
                    },
                    "symbol": symbol,
                    "order_class": "bracket",
                    "side": "buy",
                    "qty": amount
                }
            )

            # Error Logging
            if not success:
                model_helper.log(f"STOCK ORDER FAILED: {stock_order_res}")
                return https_fn.Response(f"STOCK ORDER FAILED: {stock_order_res}", status=400)

            # Updates firestore document
            assoc_action = {
                "type": "order",
                "action": "bracket_order",
                "alpaca_order_id": stock_order_res["id"],
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            action_object["exec_spread"] = {
                "upper": round(curr_stock_price * upper, 2),
                "exec_price": round(curr_stock_price * lower, 2),
                "lower": round(curr_stock_price * lower_safety, 2)
            }
            action_object["associated_action"] = assoc_action
            action_object["status"] = "executed"
            model_helper.set_database(
                collection="actions",
                document=id,
                data=action_object
            )
            return https_fn.Response("STOCK ORDER SUCCEEDED", status=200)
    else:
        model_helper.log(f"INVALID API KEY")
        return https_fn.Response(f"INVALID API KEY", status=400)

# CHECK ORDER STATUS
@scheduler_fn.on_schedule(schedule="0 * * * *")
def check_orders(req: https_fn.Request) -> https_fn.Response:

    # Gets executed orders
    ids, executed_orders = model_helper.get_database_collection(
        collection="actions",
        field="status",
        operator="==",
        value="executed",
        key="associated_action"
    )

    for id, order in zip(ids, executed_orders):
        
        # Gets order info
        alpaca_order_id = order['alpaca_order_id']
        success, order_info = model_helper.get_data_alpaca(
            url=f"v2/orders/{alpaca_order_id}?nested=true"
        )
        if success:

            # Gets legs of order
            buy_fill_price, buy_quantity = float(order_info["filled_avg_price"]), float(order_info["filled_qty"])
            symbol = order_info["symbol"]
            legs = order_info["legs"]
            buy_time = datetime.strptime(
                order_info["created_at"][:-4], 
                "%Y-%m-%dT%H:%M:%S.%f"
            )
            for order_leg in legs:
                if order_leg["status"] == "filled":

                    # Calculates profit or loss on trade
                    sell_fill_price, sell_quantity = float(order_leg["filled_avg_price"]), float(order_leg["filled_qty"])
                    pl_abs = (sell_fill_price * sell_quantity) - (buy_fill_price * buy_quantity)
                    pl_rel = (pl_abs / (buy_fill_price * buy_quantity)) * 100
                    sell_time = datetime.strptime(
                        order_leg["updated_at"][:-4], 
                        "%Y-%m-%dT%H:%M:%S.%f"
                    )

                    # Posts tweet
                    if pl_rel > 0:
                        tweet_content = f"I just sold the {symbol} stock I bought on {buy_time} for a percent gain of {round(pl_rel, 2)}%. Do you guys approve of this?"
                    else:
                        tweet_content = f"I just sold the {symbol} stock I bought on {buy_time} for a percent loss of {round(pl_rel, 2)}%. Do you guys approve of this?"
                    success, tweet_id = model_helper.create_tweet(
                        payload={
                            "text": tweet_content,
                            "poll": {
                                "options": ["Yeah, Absolutely.", "You should've held.", "I'm not sure."],
                                "duration_minutes": 60 * 24 * 7
                            }
                        }
                    )

                    # Updates database
                    order["execution_info"] = {
                        "buy_fill_price": buy_fill_price,
                        "buy_quantity": buy_quantity,
                        "sell_fill_price": sell_fill_price,
                        "sell_quantity": sell_quantity,
                        "pl_abs": pl_abs,
                        "pl_rel": pl_rel,
                        "timestamp": sell_time
                    }
                    model_helper.set_database(
                        collection="actions",
                        document=id,
                        data={
                            "status": "complete",
                            "associated_action": order,
                            "associated_tweet_followup_id": tweet_id if success else "failed"
                        }
                    )
    
# CREATE TASK QUEUE ORDER AND FIRESTORE ENTRY
@scheduler_fn.on_schedule(schedule="0 4 * * *", timeout_sec=300)
def schedule_orders(req: https_fn.Request) -> https_fn.Response:

    # Creates orders after retrieving data
    orders_exec_limit = 5
    orders_exec = 0
    orders = formulate_orders()

    # Get additional info about orders and schedules them
    for order in orders:

        # Analyzes stock via AI
        if orders_exec < orders_exec_limit:
            try:
                order.analyzeAI()
                order.updateDatabase()
                if order.elgible:
                    order.scheduleTask()
                    order.postTweet()
                    if order.status == "scheduled":
                        orders_exec += 1
                time.sleep(1)
                order.updateDatabase()
                model_helper.log(str(order))
            except Exception as error:
                model_helper.log(f"SCHEDULE ORDERS ERROR: {error}")
                continue
        else:
            break

# check_orders()