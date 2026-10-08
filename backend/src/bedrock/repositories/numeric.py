from decimal import Decimal


def plain(value: Decimal) -> Decimal:
    """Numeric(28, 10) comes back padded ("391035000000.0000000000"); drop the padding, without
    ever switching to exponent notation (`391035000000` rather than `3.91035E+11`)."""
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value.normalize()
