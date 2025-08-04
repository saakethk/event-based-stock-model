
# DEPENDENCIES
import model_helper
from datetime import datetime, timedelta
import os
import json
import uuid
from firebase_admin import firestore, functions

# EARNINGS OBJECT
class EarningsObject:

    def __init__(self, symbol: str, date: str, time: str, rev: str, eps_est: str):
        self.symbol = symbol
        self.date = datetime.strptime(date, "%Y-%m-%d")
        self.rev = float(rev) if rev is not None else 0
        match time:
            case "bmo": # Before market open
                self.time = timedelta(hours=9, minutes=30)
            case "amc": # After market close
                self.time = timedelta(hours=33, minutes=30)
            case "dmh": # During market hours
                self.time = timedelta(hours=14)
            case _:
                self.time = "na"
        self.buy_time = self.date + self.time if isinstance(self.time, timedelta) else self.date
        self.eps_est = float(eps_est if eps_est != None else 0)
        if self.time != "na" and self.buy_time > datetime.now() and self.eps_est > 0:
            self.elgible = True
        else:
            self.elgible = False
    def __str__(self):
        return f"{self.symbol} - {self.date} - {self.buy_time}"

# IPO OBJECT
class IpoObject:

    def __init__(self, symbol: str, name: str, date: str, expected_price: str):
        self.symbol = symbol
        self.name = name
        self.date = datetime.strptime(date, "%Y-%m-%d")
        self.price = expected_price.split("-")
        if len(self.price) < 2:
            self.expected_price = float(self.price[0])
        else:
            self.upper_price, self.lower_price = self.price
            self.expected_price = (float(self.upper_price) + float(self.lower_price)) /2
        self.buy_time = self.date + timedelta(hours=14)
        
    def __str__(self):
        return f"{self.symbol} - {self.date} - {self.expected_price} - {self.buy_time}"

# ORDER OBJECT
class Order:

    def __init__(self, symbol: str, object: IpoObject | EarningsObject):
        self.id = str(uuid.uuid1())
        self.symbol = symbol
        self.object = object
        if isinstance(object, IpoObject):
            self.type = "ipo" 
            self.price = self.object.expected_price
            self.name = self.object.name
        else:
            self.type = "earnings"
            self.price = self.getCurrStockPrice()
            self.name = self.getCompanyName()
        self.execute_time = self.object.buy_time - timedelta(minutes=5)
        self.execute_time = self.execute_time + timedelta(hours=4) # timezone adjustment for central server time
        self.elgible = True if self.price != None else False

    def getCompanyName(self):
        success, company_profile = model_helper.get_data_finnhub(
            url="api/v1/stock/profile2",
            params={
                "token": os.getenv("STOCKS_API_KEY"),
                "symbol": self.symbol
            }
        )
        if not success:
            model_helper.log(f"FAILED TO GET COMPANY INFO: {company_profile}")
        return company_profile["name"]

    def getCurrStockPrice(self):
        success, stock_price = model_helper.get_data_alpaca(
            url=f"/v2/stocks/{self.symbol}/snapshot",
            market=True
        )
        if not success:
            model_helper.log(f"FAILED TO GET STOCK PRICE: {stock_price}")
        return float(stock_price["dailyBar"]["vw"]) if (success and "dailyBar" in stock_price) else None
    
    def getNews(self):
        success, news = model_helper.get_data_news(
            url="v2/everything",
            params={
                "searchIn": "title",
                "q": f"{self.name} OR {self.symbol}",
                "apiKey": os.getenv("NEWS_EXTRA_API_KEY"),
                "sortBy": "relevancy",
                "language": "en",
                "from": model_helper.get_timestamp(with_time=False, delta=180),
                "pageSize": 10
            }
        )
        if not success:
            model_helper.log(f"FAILED TO GET NEWS: {news}")
        return news["articles"]
    
    def analyzeAI(self):
        self.news = self.getNews()
        self.sources = [article["url"] for article in self.news]
        if len(self.news) > 0:
            try:
                res = model_helper.ask_llm(
                    prompt=f"""Review the following list of articles which mention {self.name} 
                    and write a concise 100-150 word summary of all the articles combined without mentioning 'the articles'. 
                    Also choose one of the following stances (bearish, bullish, neutral) and defend it. 
                    Return the response in a structured json output which matches the following: 
                    {{ summary: __________, stance: ______________, defense: ______________ }}. 
                    Articles: {self.news}""",
                )
                res = json.loads(res[res.index("{"): res.index("}")+1])
                self.overview = res["summary"]
                self.stance = res["stance"]
                self.defense = res["defense"]
                match self.stance:
                    case "bearish":
                        self.price_upper = 1.05
                        self.price_lower = .95
                    case "bullish":
                        self.price_upper = 1.1
                        self.price_lower = .9
                    case _:
                        self.price_upper = 1.02
                        self.price_lower = 0.98
                self.status = "order_created"
            except Exception as error:
                model_helper.log(f"AI ANALYSIS FAILED: {error}")
                self.status = "canceled_ai_analy_fail"
                self.elgible = False
        else:
            model_helper.log(f"INSUFFICIENT NUMBER OF ARTICLES TO ANALYZE")
            self.status = "canceled_insuff_articles"
            self.elgible = False
    
    def updateDatabase(self):
        if self.elgible:
            model_helper.set_database(
                collection="actions",
                document=self.id,
                data=self.getDict()
            )

    def scheduleTask(self):
        if self.elgible:
            model_helper.queue_task(
                function_id="createstockorder",
                data={
                    "data": {
                        "id": self.id,
                        "symbol": self.symbol,
                        "amount": 1,
                        "current_price": self.price,
                        "upper": self.price_upper,
                        "lower": self.price_lower,
                        "lower_safety": self.price_lower - 0.01,
                    }
                },
                execute_time=self.execute_time
            )
            self.status = "scheduled"

    def getDict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "type": self.type,
            "pred_spread": {
                "curr_price": self.price,
                "upper": self.price_upper,
                "lower": self.price_lower
            },
            "execute_time": self.execute_time,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "analysis": {
                "stance": self.stance,
                "overview": self.overview,
                "defense": self.defense,
                "sources": self.sources
            },
            "status": self.status
        }
    
    def __str__(self):
        return f"{self.symbol} - {self.execute_time} - {self.type} - {self.price}"
