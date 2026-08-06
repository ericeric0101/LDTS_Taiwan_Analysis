from __future__ import annotations
import hashlib, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote

class Client:
    def __init__(self, raw_dir="data/raw", delay=3, timeout=30, user_agent="LDTSResearchBot/0.1", verify=True):
        self.raw_dir, self.delay, self.timeout, self.verify = Path(raw_dir), delay, timeout, verify
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session(); self.session.headers["User-Agent"] = user_agent

    def get(self, url: str, force=False) -> tuple[str, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()[:20]
        path = self.raw_dir / f"{key}.html"
        if path.exists() and not force: return path.read_text(encoding="utf-8"), path
        response = self.session.get(url, timeout=self.timeout, verify=self.verify)
        response.raise_for_status(); text = response.content.decode(response.encoding or "utf-8", errors="replace")
        path.write_text(text, encoding="utf-8"); time.sleep(self.delay)
        return text, path

    def save(self, url: str, text: str, label: str) -> Path:
        key = hashlib.sha256((url + label + text[:100]).encode()).hexdigest()[:20]
        path = self.raw_dir / f"{key}_{label}.html"
        path.write_text(text, encoding="utf-8")
        return path

    def cached_label(self, label: str) -> Path | None:
        matches = sorted(self.raw_dir.glob(f"*_{label}.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0] if matches else None

    def aspnet_postback(self, url: str, html: str, event_target: str, extra: dict[str, str] | None = None) -> str:
        soup = BeautifulSoup(html, "lxml")
        data = {}
        for node in soup.select("input[type=hidden][name]"):
            data[node["name"]] = node.get("value", "")
        data["__EVENTTARGET"] = event_target
        data["__EVENTARGUMENT"] = ""
        if extra:
            data.update(extra)
        response = self.session.post(url, data=data, timeout=self.timeout, verify=self.verify)
        response.raise_for_status()
        text = response.content.decode(response.encoding or "utf-8", errors="replace")
        time.sleep(self.delay)
        return text

    @staticmethod
    def pager_targets(html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        targets = []
        for link in soup.select("#ContentPlaceHolder1_DataPager1 a[href]"):
            href = unquote(link.get("href", ""))
            marker = "__doPostBack('"
            if marker in href:
                target = href.split(marker, 1)[1].split("'", 1)[0]
                if target not in targets and link.get_text(strip=True) not in {"第一頁", "上一頁", "下一頁", "最後頁"}:
                    targets.append(target)
        return targets

    @staticmethod
    def next_page_target(html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        for link in soup.select("#ContentPlaceHolder1_DataPager1 a[href]"):
            if link.get_text(strip=True) != "下一頁":
                continue
            href = unquote(link.get("href", ""))
            marker = "__doPostBack('"
            if marker in href:
                return href.split(marker, 1)[1].split("'", 1)[0]
        return None

    @staticmethod
    def current_page_number(html: str) -> int | None:
        soup = BeautifulSoup(html, "lxml")
        current = soup.select_one("#ContentPlaceHolder1_DataPager1 .current")
        try:
            return int(current.get_text(strip=True)) if current else None
        except ValueError:
            return None
