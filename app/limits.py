"""하루 사용 한도: Claude처럼 돈이 드는 기능을 하루에 몇 번까지만 쓰게 막는다.

서버를 인터넷에 계속 열어 두면, 누가 장난으로 등록이나 검색을 마구 해서 사용료를 다 써 버릴 수 있다.
그래서 날짜마다 몇 번 썼는지 세고, 한도를 넘으면 그날은 더 쓰지 않는다(다음 날 0부터 다시 센다).
"""
import threading
from datetime import datetime

from . import config


class LimitReached(Exception):
    """오늘 쓸 수 있는 횟수를 다 썼을 때."""


class DailyLimit:
    def __init__(self, name: str, limit_getter):
        self.name = name
        self.limit_getter = limit_getter  # 설정값을 그때그때 읽는다(시험할 때 바꾸기 쉽게)
        self.day = None
        self.count = 0
        self.lock = threading.Lock()

    def exhausted(self) -> bool:
        """오늘 한도를 다 썼는지 (쓰지는 않고 확인만)."""
        today = datetime.now(config.TIMEZONE).date()
        with self.lock:
            return self.day == today and self.count >= self.limit_getter()

    def take(self) -> None:
        """한 번 쓴다. 오늘 한도를 넘었으면 LimitReached."""
        today = datetime.now(config.TIMEZONE).date()  # 한국 날짜 기준
        with self.lock:
            if self.day != today:
                self.day, self.count = today, 0
            if self.count >= self.limit_getter():
                raise LimitReached(f"오늘 {self.name} 한도({self.limit_getter()}번)를 다 썼어요.")
            self.count += 1


describe_limit = DailyLimit("Claude 사진 정리", lambda: config.DESCRIBE_DAILY_LIMIT)
rerank_limit = DailyLimit("Claude 재순위", lambda: config.RERANK_DAILY_LIMIT)
