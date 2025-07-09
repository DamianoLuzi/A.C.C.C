import json
import random
from decimal import Decimal
import logging
import time
import urllib3
from datetime import datetime
from boto3.dynamodb.conditions import Key
from urllib.parse import urlencode

BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
FORECAST_CACHE_EXPIRY_SECONDS = 3 * 60 * 60  # 3 hours

logger = logging.getLogger()
logger.setLevel(logging.INFO)

http = urllib3.PoolManager()


def convert_floats_to_decimal(obj):
    if isinstance(obj, list):
        return [convert_floats_to_decimal(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def convert_decimals_to_float(obj):
    if isinstance(obj, list):
        return [convert_decimals_to_float(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

def extract_cities(event):

    try:
        if 'detail' in event:
            return event['detail'].get('cities', None)
        if event.get("requestContext", {}).get("http"):
            method = event["requestContext"]["http"].get("method", "GET")
            logger.info(f"Handling API Gateway  {method} request")
            if method == "GET":
                query = event.get("queryStringParameters", {})
                cities_raw = query.get("cities")
                if isinstance(cities_raw, str):
                    extracted = [city.strip() for city in cities_raw.split(',')]
                    logger.info(f"extract_cities: Successfully extracted from GET query: {extracted}")
                    return extracted
                else:
                    logger.warning(f"extract_cities: 'cities' not a string: {type(cities_raw)}")        
            elif method == "POST":
                body = json.loads(event.get("body", "{}"))
                cities = body.get("cities")
                if cities:
                    logger.info(f"extract_cities: Successfully extracted from POST body: {cities}")
                    return cities
    except Exception as e:
        logger.warning(f"extract_cities: City extraction failed: {e}")
    return None


def fetch_weather_for_city(city, key):
    try:
        query_params = urlencode({
            'q': city,
            'appid': key,
            'units': 'metric'
        })
        url = f"{BASE_URL}?{query_params}"

        start = time.time()
        response = http.request('GET', url)
        latency = (time.time() - start) * 1000

        if response.status == 200:
            data = json.loads(response.data.decode('utf-8'))
            logger.info(f"Weather data fetched: {data}")
            return {
                'city': city,
                'country': data['sys'].get('country'),
                'temperature': data['main']['temp'],
                'feels_like': data['main'].get('feels_like'),
                'humidity': data['main']['humidity'],
                'pressure': data['main']['pressure'],
                'wind_speed': data['wind']['speed'],
                'clouds': data['clouds']['all'],
                'condition': data['weather'][0]['main'],
                'description': data['weather'][0]['description'],
                'latency': latency,
                'status_code': 200,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "current"
            }
        else:
            return {'city': city, 'status_code': response.status, 'latency': latency, 'error': True}
    except Exception as e:
        logger.exception(f"Exception fetching current weather for {city}: {e}")
        return {'city': city, 'status_code': 500, 'latency': None, 'error': True}

def get_cached_forecast_from_dynamo(city, ftable):
    try:
        logger.info(f"Attempting forecast cache retrieval from DynamoDB for {city}")
        response = ftable.query(
            KeyConditionExpression=Key('city').eq(city),
            ScanIndexForward=False,  
            Limit=1
        )
        items = response.get('Items')
        item = items[0] if items else None
        if item:
            logger.info(f"Forecast cache hit for {city}")
            ts = datetime.fromisoformat(item['timestamp'])
            if (datetime.utcnow() - ts).total_seconds() < FORECAST_CACHE_EXPIRY_SECONDS:
                return item
            logger.info(f"Forecast cache HIT with STALE data for {city}")
    except Exception as e:
        logger.warning(f"Exception during DynamoDB cache check {city}: {e}")
    logger.info(f"Forecast cache MISS for {city}")
    return None

def fetch_forecast_for_city(city, key):
    try:
        query_params = urlencode({
            'q': city,
            'appid': key,
            'units': 'metric'
        })
        url = f"{FORECAST_URL}?{query_params}"

        start = time.time()
        response = http.request('GET', url)
        latency = (time.time() - start) * 1000

        if response.status == 200:
            data = json.loads(response.data.decode('utf-8'))
            return {
                'city': city,
                'forecast_data': data,
                'latency': latency,
                'status_code': 200,
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'forecast'
            }
        else:
            return {'city': city, 'status_code': response.status, 'latency': latency, 'error': True}
    except Exception as e:
        logger.exception(f"Exception fetching forecast for {city}: {e}")
        return {'city': city, 'status_code': 500, 'latency': None, 'error': True}
