from enum import Enum


class DialogState(str, Enum):
    START = "START"
    SELECT_TOUR = "SELECT_TOUR"
    SELECT_DATE = "SELECT_DATE"
    VIEW_DAY = "VIEW_DAY"       # Просмотр доступности даты + кнопка «Забронировать»
    CONSENT = "CONSENT"         # Согласие на обработку персональных данных
    INPUT_NAME = "INPUT_NAME"
    INPUT_PHONE = "INPUT_PHONE"
    INPUT_PEOPLE_COUNT = "INPUT_PEOPLE_COUNT"
    CONFIRM = "CONFIRM"