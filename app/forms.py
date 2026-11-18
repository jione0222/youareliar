"""등록 화면과 관리자 '고치기' 화면이 같이 쓰는 입력값 정리."""
import re


def normalize_phone(text: str) -> str:
    """전화번호를 010-1234-5678 모양으로 맞춘다. 이상한 번호면 ValueError."""
    digits = re.sub(r"\D", "", text)
    if not digits.startswith("0") or not 9 <= len(digits) <= 11:
        raise ValueError(text)
    if digits.startswith("02"):  # 서울 지역번호는 두 자리
        return f"{digits[:2]}-{digits[2:-4]}-{digits[-4:]}"
    return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
