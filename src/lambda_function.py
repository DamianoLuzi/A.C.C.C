import json
import logging
import boto3
import time
import os
from datetime import datetime
from helpers import *

# Initializing logging level for observabililty
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Creating clients for AWS resources
cloudwatch = boto3.client('cloudwatch')
ssm = boto3.client('ssm')
FORECAST_TABLE_NAME = os.environ.get('DDBForecastTable')
CURRENT_TABLE_NAME = os.environ.get('DDBCurrWeatherTable')
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')
S3_BUCKET_NAME = os.environ.get('S3OWBucket')
response = ssm.get_parameter(Name='OWAPIkey', WithDecryption=True)
OPENWEATHER_API_KEY = response['Parameter']['Value']
ftable = dynamodb.Table(FORECAST_TABLE_NAME)
ctable = dynamodb.Table(CURRENT_TABLE_NAME)

cold_start = True


def lambda_handler(event, context):
    global cold_start
    start_time = time.time()
    payload_size = len(json.dumps(event).encode('utf-8'))
    errors = 0
    results = []
    logger.info(f"Extracting cities from received event: {event}")
    cities = extract_cities(event)
    logger.info(f"Extracted cities: {cities}")
    weather_metrics = []
    now = datetime.utcnow()
    year, month, day = now.year, f"{now.month:02d}", f"{now.day:02d}"
    timestamp = int(now.timestamp())

    if not cities:
        logger.error("No cities found in the event.")
        errors += 1
        weather_metrics.append({'MetricName': 'NoCitiesError', 'Value': 1, 'Unit': 'Count'})
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No cities found in the event.'})
        }

    for city in cities:
        logger.info(f"Fetching current weather for {city}")
        current = fetch_weather_for_city(city, OPENWEATHER_API_KEY)

        # Attempt to retrieve from cache
        logger.info(f"Attempting to get cached forecast for {city}")
        forecast_data = None
        forecast = get_cached_forecast_from_dynamo(city, ftable)
        if not forecast:
            forecast = fetch_forecast_for_city(city, OPENWEATHER_API_KEY)
            if 'error' not in forecast:
                forecast_data = forecast
                try:
                    forecast['forecast_data'] = convert_floats_to_decimal(forecast['forecast_data'])
                    forecast['timestamp'] = forecast['timestamp']
                    forecast['type'] = 'forecast'
                    item = convert_floats_to_decimal(forecast)
                    ftable.put_item(Item=item)
                    logger.info(f"Cached/Inserted forecast for {city} in Dynamo")
                except Exception as e:
                    logger.error(f"Failed to cache/update forecast for {city} in DynamoDB: {e}")
                    errors += 1
                    weather_metrics.append({'MetricName': 'ForecastDynamoError', 'Value': 1, 'Unit': 'Count'})
                try:
                    converted_forecast = convert_decimals_to_float(forecast_data)
                    s3.put_object(
                        Bucket=S3_BUCKET_NAME,
                        Key=f"weather_data/forecast/city={city}/year={year}/month={month}/day={day}/{timestamp}.json",
                        Body=json.dumps(converted_forecast),
                        ContentType='application/json'
                    )
                    logger.info(f"Uploaded forecast for {city} to S3.")
                except Exception as e:
                    logger.error(f"Failed to upload forecast for {city} to S3: {e}")
                    errors += 1
                    weather_metrics.append({'MetricName': 'ForecastS3Error', 'Value': 1, 'Unit': 'Count'})
            else:
                errors += 1
                logger.error(f"Failed to fetch forecast for {city}.")
                weather_metrics.append({'MetricName': 'ForecastFetchError', 'Value': 1, 'Unit': 'Count'})
        else:
            logger.info(f"Forecast for {city} retrieved from cache.")
            forecast_data = forecast
        results.append(forecast_data)
        if current and 'error' not in current:
            results.append(current)
            try:
                item = {
                    'city': current['city'],
                    'timestamp': current['timestamp'],
                    'country': current.get('country'),
                    'temperature': Decimal(str(current['temperature'])),
                    'feels_like': Decimal(str(current['feels_like'])),
                    'humidity': Decimal(str(current['humidity'])),
                    'pressure': Decimal(str(current['pressure'])),
                    'wind_speed': Decimal(str(current['wind_speed'])),
                    'clouds': Decimal(str(current['clouds'])),
                    'condition': current.get('condition'),
                    'description': current.get('description'),
                    'latency': Decimal(str(current['latency'])),
                    'status_code': current.get('status_code'),
                    'type': current['type']
                }
                ctable.put_item(Item=item)
                logger.info(f"Inserted current into DynamoDB for {current['city']}")
            except Exception as e:
                logger.error(f"Failed to insert into DynamoDB for {current['city']}: {e}")
                weather_metrics.append({'MetricName': 'CurrentDynamoError', 'Value': 1, 'Unit': 'Count'})
            try:
                converted_curr = convert_decimals_to_float(current)
                s3.put_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=f"weather_data/current/city={city}/year={year}/month={month}/day={day}/{timestamp}.json",
                    Body=json.dumps(converted_curr),
                    ContentType='application/json'
                )
                logger.info(f"Uploaded current weather for {city} to S3.")
            except Exception as e:
                logger.error(f"Failed to upload current weather for {city} to S3: {e}")
                errors += 1
                weather_metrics.append({'MetricName': 'CurrentWeatherS3Error', 'Value': 1, 'Unit': 'Count'})

            dimensions = [
                {'Name': 'City', 'Value': current['city']},
                {'Name': 'Country', 'Value': current.get('country')}
            ]
            weather_metrics.extend([
                {'MetricName': 'Temperature', 'Value': current['temperature'], 'Unit': 'None', 'Dimensions': dimensions},
                {'MetricName': 'FeelsLike', 'Value': current['feels_like'], 'Unit': 'None', 'Dimensions': dimensions},
                {'MetricName': 'Humidity', 'Value': current['humidity'], 'Unit': 'None', 'Dimensions': dimensions},
                {'MetricName': 'Pressure', 'Value': current['pressure'] / 1000.0, 'Unit': 'None', 'Dimensions': dimensions},
                {'MetricName': 'WindSpeed', 'Value': current['wind_speed'], 'Unit': 'None', 'Dimensions': dimensions},
                {'MetricName': 'CloudCoverage', 'Value': current['clouds'], 'Unit': 'None', 'Dimensions': dimensions},
            ])
        else:
            errors += 1
            weather_metrics.append({'MetricName': 'ErrorCount', 'Value': 1, 'Unit': 'Count'})
    end_time = time.time()
    duration = (end_time - start_time) * 1000
    

    core_metrics = [
        {
            'MetricName': 'ExecutionDuration',
            'Dimensions': [{'Name': 'FunctionName', 'Value': context.function_name}],
            'Unit': 'Milliseconds',
            'Value': duration
        },
        {
            'MetricName': 'ColdStart',
            'Unit': 'Count',
            'Value': 1 if cold_start else 0
        },
        {
            'MetricName': 'PayloadSize',
            'Unit': 'Bytes',
            'Value': payload_size
        }
    ]

    # Send metrics to CloudWatch
    logger.info(f"Publishing to OpenWeather/Core")
    cloudwatch.put_metric_data(Namespace='OpenWeather/Core', MetricData=core_metrics)
    if weather_metrics:
        logger.info(f"Publishing metrics to OpenWeather/WeatherData for {cities}")
        cloudwatch.put_metric_data(Namespace='OpenWeather/WeatherData', MetricData=weather_metrics)


    cold_start = False
    cr = convert_decimals_to_float(results)
    return {
        'statusCode': 200 if errors == 0 else 207,
        'body': json.dumps(cr)
    }