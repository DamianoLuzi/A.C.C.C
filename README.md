# Getting started

This section provides a guide to manually setting up the AWS resources for the project.

1.  **Prerequisites:**
    * An AWS Account with sufficient permissions.
    * (Optional) AWS CLI configured.
    * Access to OpenWeather API and an API key.

2.  **Deployment Steps (Conceptual):**
    * **Clone the Repository:** `git clone <repository-url>`
    * **Configure API Key:** Store your OpenWeather API key securely in AWS Systems Manager Parameter Store under the name `/OWAPIkey`. Ensure your Lambda's IAM role has `ssm:GetParameter` permission for this resource.
    * **Deploy Lambda Function:** Deploy the Lambda function code (`2.1. AWS Lambda` section provides snippets and permissions). This function will handle data fetching, caching in DynamoDB, and storage in S3.
        * Ensure the Lambda's IAM role has necessary `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query` permissions on your target S3 buckets and DynamoDB tables.
        * Include CloudWatch `PutMetricData` permission for custom metrics.
    * **Set up DynamoDB Tables:** Create two DynamoDB tables (e.g., `DDBForecastTable`, `DDBCurrWeatherTable`) in On-Demand mode.
    * **Configure S3 Buckets:** Create S3 bucket(s) for raw JSON data, ensuring the `weather_data/current/city={city}/...` and `weather_data/forecast/city={city}/...` partitioning structure is followed by the Lambda.
    * **Deploy API Gateway:** Configure an HTTP API Gateway with a `GET` route to invoke your Lambda function for on-demand requests.
    * **Configure EventBridge Schedule:** Set up an EventBridge rule to periodically invoke your Lambda function (e.g., daily) for automated data collection.
    * **Set up CloudWatch Alarms & SNS:** Configure CloudWatch alarms (e.g., Lambda timeout, S3 ListBuckets threshold) and connect them to an SNS topic for email notifications.

3.  **Data Lake Cataloging & Visualization:**
    * **Run AWS Glue Crawler:** Once data is in S3, configure and run an AWS Glue Crawler pointing to your `weather_data/` prefixes in S3. This will create tables like `current_weather_data` and `forecast_weather_data` in your Glue Data Catalog.
    * **Refine Schema (if needed):** Access the Glue Data Catalog via the AWS console or Athena. Manually adjust any schema definitions if Glue Crawlers misinferred data types for complex or inconsistent fields, ensuring accuracy for queries.
    * **Connect QuickSight to Athena:** In QuickSight, create a new dataset using Athena, selecting the tables created by your Glue Crawler. Choose **SPICE** for high-performance dashboards or **Direct Query** for real-time data.
    * **Build Dashboards:** Utilize QuickSight to create time-series charts, geospatial maps, and other visualizations from your weather data.

---

## Testing & Validation

* **Lambda & API Gateway:** Verify via **Postman** for on-demand requests and **CloudWatch Logs** for request formats, successful API calls, and debugging.
* **EventBridge Schedule:** Confirm recurring Lambda invocations and payload processing through **CloudWatch Dashboards** and manual event simulations.
* **End-to-End System:** Validate the entire data pipeline from Lambda ingestion to S3/DynamoDB, successful Glue Crawler runs, accurate Athena querying, and finally, correct QuickSight visualization.
