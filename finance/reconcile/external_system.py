import dataclasses
import datetime
import decimal


@dataclasses.dataclass
class ExternalExpense:
    id: str
    trade_date: datetime.date
    amount: decimal.Decimal
    description: str
