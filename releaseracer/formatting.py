import datetime
import traceback


def get_traceback(error):
    return ''.join(traceback.format_exception(
        type(error), error, error.__traceback__, limit=7
    ))


def format_size(byte_amount: int) -> str:
    return f'{round(byte_amount / (10 ** 6), 2)} MB ({byte_amount:,} bytes)'


def format_datetime(dt: datetime.datetime, *, twenty_four=False) -> str:
    return dt.strftime('%d/%m ' + ('%H:%M' if twenty_four else '%I:%M %p'))

