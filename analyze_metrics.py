import requests
import pandas as pd
import os
import sys
import datetime
try:
    from nixtla import NixtlaClient
except ImportError as e:
    print(f"Failed to import nixtla: {e}", flush=True)
    exit(1)
try:
    from prometheus_client import start_http_server, Gauge, Counter
except ImportError as e:
    print(f"Failed to import prometheus_client: {e}", flush=True)
    exit(1)
import time
import json

# Force flush print statements for Docker logs
sys.stdout.flush()

# Initialize Nixtla client
api_key = os.getenv('NIXTLA_API_KEY')
if not api_key:
    print("NIXTLA_API_KEY environment variable not set", flush=True)
    exit(1)
nixtla_client = NixtlaClient(api_key=api_key)
if not nixtla_client.validate_api_key():
    print("Invalid Nixtla API key", flush=True)
    exit(1)
print("Nixtla client initialized successfully", flush=True)

# Prometheus metrics
ANALYSIS_REQUESTS = Counter('timegpt_analysis_requests', 'Total TimeGPT analysis requests')
LATENCY_FORECAST = Gauge('timegpt_latency_forecast', 'Forecasted latency by TimeGPT')
ANOMALY_COUNT = Counter('timegpt_anomaly_count', 'Number of anomalies detected by TimeGPT')

def query_prometheus(query, start_time, end_time, step='15s'):
    url = "http://prometheus:9090/api/v1/query_range"
    params = {
        "query": query,
        "start": start_time.isoformat(),
        "end": end_time.isoformat(),
        "step": step
    }
    try:
        print(f"Querying Prometheus: {url} with params: {params}", flush=True)
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"Prometheus response: {json.dumps(data, indent=2)}", flush=True)
        if 'data' not in data:
            print(f"Error: 'data' key missing in Prometheus response: {data}", flush=True)
            return {}
        return data
    except requests.RequestException as e:
        print(f"Prometheus query failed: {e}", flush=True)
        return {}

def prepare_timeseries(data, metric):
    if not data:
        print(f"No data returned for {metric}", flush=True)
        return None
    results = data.get('data', {}).get('result', [])
    if not results:
        print(f"No results in Prometheus response for {metric}: {data}", flush=True)
        return None
    try:
        timestamps = [datetime.datetime.fromtimestamp(float(item[0]), tz=datetime.timezone.utc) for item in results[0]['values']]
        values = [float(item[1]) for item in results[0]['values']]
        return pd.DataFrame({'ds': timestamps, 'y': values})
    except (IndexError, KeyError, ValueError) as e:
        print(f"Failed to parse timeseries for {metric}: {e}", flush=True)
        return None

def analyze_metrics():
    ANALYSIS_REQUESTS.inc()
    
    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(hours=1)
    
    queries = {
        "latency": 'avg(rate(http_server_requests_seconds_sum{application="user-system"}[5m]) / rate(http_server_requests_seconds_count{application="user-system"}[5m]))',
        "error_rate": 'rate(http_server_requests_seconds_count{application="user-system",outcome="SERVER_ERROR"}[5m])',
        "heap_usage": 'jvm_memory_used_bytes{application="user-system",area="heap"}',
        "gc_pauses": 'rate(jvm_gc_pause_seconds_sum{application="user-system"}[5m])'
    }
    
    analysis_results = {}
    for metric, query in queries.items():
        data = query_prometheus(query, start_time, end_time)
        df = prepare_timeseries(data, metric)
        if df is None:
            continue
            
        try:
            print(f"Running TimeGPT forecast for {metric}", flush=True)
            forecast = nixtla_client.forecast(df=df, h=12, freq='15s', model='timegpt-1')
            print(f"Running TimeGPT anomaly detection for {metric}", flush=True)
            anomalies = nixtla_client.detect_anomalies(df=df, freq='15s')['anomaly'].sum()
            analysis_results[metric] = {
                'forecast': forecast['TimeGPT'].mean(),
                'anomalies': anomalies
            }
            
            if metric == 'latency':
                LATENCY_FORECAST.set(forecast['TimeGPT'].mean())
            ANOMALY_COUNT.inc(anomalies)
        except Exception as e:
            print(f"TimeGPT analysis failed for {metric}: {e}", flush=True)
    
    summary = "TimeGPT Analysis of Spring Boot Metrics:\n"
    for metric, result in analysis_results.items():
        summary += f"- {metric.capitalize()}:\n"
        summary += f"  Forecasted Value: {result['forecast']:.4f}\n"
        summary += f"  Anomalies Detected: {result['anomalies']}\n"
    
    try:
        with open("/app/analysis.txt", "w") as f:
            f.write(summary)
        print("Wrote analysis to /app/analysis.txt", flush=True)
    except Exception as e:
        print(f"Failed to write analysis.txt: {e}", flush=True)
    
    return summary

if __name__ == "__main__":
    try:
        start_http_server(8001)
        print("TimeGPT analysis server running on port 8001", flush=True)
        # Test Prometheus connectivity immediately
        print("Testing Prometheus connectivity with 'up' query", flush=True)
        test_data = query_prometheus("up", datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5), datetime.datetime.now(datetime.timezone.utc))
    except Exception as e:
        print(f"Failed to start Prometheus server or test query: {e}", flush=True)
        exit(1)
    
    while True:
        try:
            print(analyze_metrics(), flush=True)
        except Exception as e:
            print(f"Error during analysis: {e}", flush=True)
        time.sleep(30)  # Reduced for testing