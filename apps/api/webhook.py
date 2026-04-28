"""Basic webhook alert notifications"""
import os
import requests
from datetime import datetime


WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")


def send_alert(title: str, message: str, level: str = "warning"):
    """Send alert via webhook (Slack/Discord/custom)"""
    if not WEBHOOK_URL:
        print(f"[ALERT] {level.upper()}: {title} — {message} (no webhook configured)")
        return

    payload = {
        "text": f"*[{level.upper()}] {title}*\n{message}\n_Timestamp: {datetime.utcnow().isoformat()}_",
        # Slack format; adapt for Discord/other
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"⚠️ {title}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
        ],
    }

    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        print(f"[ALERT] Sent: {title} (status={resp.status_code})")
    except Exception as e:
        print(f"[ALERT] Failed to send: {e}")


def alert_ocr_failure(filename: str, error: str):
    send_alert("OCR Failure", f"File: `{filename}`\nError: {error}", "error")


def alert_high_latency(query: str, latency_ms: float, threshold_ms: float = 10000):
    if latency_ms > threshold_ms:
        send_alert("High Latency", f"Query: `{query[:80]}`\nLatency: {latency_ms:.0f}ms (threshold: {threshold_ms:.0f}ms)", "warning")


def alert_low_quality(query: str, recall: float, threshold: float = 0.3):
    if recall < threshold:
        send_alert("Low Retrieval Quality", f"Query: `{query[:80]}`\nRecall@5: {recall:.2f} (threshold: {threshold:.2f})", "warning")
