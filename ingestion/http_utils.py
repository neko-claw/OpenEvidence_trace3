"""带重试与限速的 HTTP 请求工具。"""
from __future__ import annotations

import time
import logging

import requests

log = logging.getLogger("ingestion.http")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _request(method: str, url: str, *, params=None, headers=None,
             sleep: float = 0.4, retries: int = 4, timeout: int = 30,
             allow_404: bool = False):
    """发送请求；sleep 参数在每次请求前生效，用于全局限速。"""
    last_exc = None
    for attempt in range(1, retries + 1):
        if attempt > 1:
            time.sleep(sleep * (2 ** (attempt - 1)))
        else:
            time.sleep(sleep)
        try:
            resp = requests.request(method, url, params=params, headers=headers,
                                    timeout=timeout)
            if resp.status_code in RETRYABLE_STATUS:
                log.warning("HTTP %s for %s (attempt %d/%d)",
                            resp.status_code, url, attempt, retries)
                time.sleep(sleep * (2 ** attempt))
                continue
            if resp.status_code == 404 and allow_404:
                return None
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:  # 网络错误
            last_exc = exc
            log.warning("request error for %s (attempt %d/%d): %s",
                        url, attempt, retries, exc)
            time.sleep(sleep * (2 ** attempt))
    raise RuntimeError(f"request failed after {retries} retries: {url}") from last_exc


def fetch_json(url: str, *, params=None, headers=None, sleep: float = 0.4,
               retries: int = 4, timeout: int = 30):
    resp = _request("GET", url, params=params, headers=headers,
                    sleep=sleep, retries=retries, timeout=timeout)
    return resp.json()


def fetch_text(url: str, *, params=None, headers=None, sleep: float = 0.4,
               retries: int = 4, timeout: int = 60):
    resp = _request("GET", url, params=params, headers=headers,
                    sleep=sleep, retries=retries, timeout=timeout)
    return resp.text


def fetch_text_or_none(url: str, *, params=None, headers=None, sleep: float = 0.4,
                       retries: int = 2, timeout: int = 60):
    resp = _request("GET", url, params=params, headers=headers,
                    sleep=sleep, retries=retries, timeout=timeout, allow_404=True)
    return resp.text if resp is not None else None
